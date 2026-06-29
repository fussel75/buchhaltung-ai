from asyncio import run
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from starlette.datastructures import Headers, UploadFile

from app.services import storage as storage_service
from app.services.storage import UploadRejectedError, effective_content_type, store_original_document


def upload_file(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


class StorageTests(TestCase):
    def test_store_original_document_streams_and_hashes_file(self):
        with TemporaryDirectory() as directory:
            settings = SimpleNamespace(storage_root=Path(directory), max_upload_size_bytes=1024)
            content = b"%PDF-1.7 test"
            with patch.object(storage_service, "get_settings", return_value=settings):
                stored = run(store_original_document(upload_file("rechnung.pdf", "application/pdf", content), "demo mandant"))

            stored_path = settings.storage_root / stored.storage_path
            self.assertTrue(stored_path.is_file())
            self.assertEqual(stored_path.read_bytes(), content)
            self.assertEqual(stored.sha256, sha256(content).hexdigest())
            self.assertEqual(stored.size_bytes, len(content))
            self.assertEqual(stored.content_type, "application/pdf")
            self.assertIn("demo-mandant", str(stored.storage_path))

    def test_store_original_document_normalizes_octet_stream_pdf_by_suffix(self):
        with TemporaryDirectory() as directory:
            settings = SimpleNamespace(storage_root=Path(directory), max_upload_size_bytes=1024)
            content = b"%PDF-1.7 from mail"
            with patch.object(storage_service, "get_settings", return_value=settings):
                stored = run(
                    store_original_document(upload_file("773934-606.pdf", "application/octet-stream", content), "demo")
                )

            self.assertEqual(stored.content_type, "application/pdf")

    def test_effective_content_type_preserves_specific_content_type(self):
        self.assertEqual(effective_content_type("rechnung.pdf", "application/xml"), "application/xml")
        self.assertEqual(effective_content_type("rechnung.pdf", "application/octet-stream"), "application/pdf")

    def test_store_original_document_rejects_disallowed_extension(self):
        with TemporaryDirectory() as directory:
            settings = SimpleNamespace(storage_root=Path(directory), max_upload_size_bytes=1024)
            with patch.object(storage_service, "get_settings", return_value=settings):
                with self.assertRaises(UploadRejectedError) as context:
                    run(store_original_document(upload_file("script.exe", "application/octet-stream", b"bad"), "demo"))

            self.assertEqual(context.exception.status_code, 415)
            self.assertEqual(list(settings.storage_root.rglob("*")), [])

    def test_store_original_document_rejects_oversized_file_and_removes_temporary_file(self):
        with TemporaryDirectory() as directory:
            settings = SimpleNamespace(storage_root=Path(directory), max_upload_size_bytes=4)
            with patch.object(storage_service, "get_settings", return_value=settings):
                with self.assertRaises(UploadRejectedError) as context:
                    run(store_original_document(upload_file("rechnung.pdf", "application/pdf", b"12345"), "demo"))

            self.assertEqual(context.exception.status_code, 413)
            files = [path for path in settings.storage_root.rglob("*") if path.is_file()]
            self.assertEqual(files, [])
