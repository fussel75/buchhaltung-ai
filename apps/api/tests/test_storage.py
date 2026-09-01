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
from app.services.storage import (
    UploadRejectedError,
    effective_content_type,
    resolve_existing_stored_document_path,
    store_original_document,
)


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

    def test_resolve_existing_stored_document_path_recovers_by_hash_prefix(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(storage_root=root)
            existing = root / "demo-mandant" / "originals" / "2026" / "06" / "abcdef1234567890-upload.pdf"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"%PDF")

            with patch.object(storage_service, "get_settings", return_value=settings):
                resolved = resolve_existing_stored_document_path(
                    "demo-mandant/originals/2026/06/ERg alt.pdf",
                    tenant_id="demo-mandant",
                    sha256_value="abcdef1234567890fedcba",
                    original_filename="Invoice.pdf",
                )

            self.assertEqual(resolved, existing)

    def test_resolve_existing_stored_document_path_recovers_by_safe_filename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(storage_root=root)
            existing = root / "demo-mandant" / "originals" / "2026" / "08" / "Mahnung Arens Stitz KG 2327409.pdf"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"%PDF")

            with patch.object(storage_service, "get_settings", return_value=settings):
                resolved = resolve_existing_stored_document_path(
                    "demo-mandant/originals/2026/08/ERg ohne Nummer.pdf",
                    tenant_id="demo-mandant",
                    sha256_value=None,
                    original_filename="Mahnung Arens & Stitz KG 2327409.pdf",
                )

            self.assertEqual(resolved, existing)

    def test_resolve_existing_stored_document_path_recovers_by_full_hash_after_rename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(storage_root=root)
            content = b"%PDF renamed content"
            digest = sha256(content).hexdigest()
            existing = root / "demo-mandant" / "originals" / "2026" / "06" / "ERg neu benannt.pdf"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(content)

            with patch.object(storage_service, "get_settings", return_value=settings):
                resolved = resolve_existing_stored_document_path(
                    "demo-mandant/originals/2026/06/ERg alter Name.pdf",
                    tenant_id="demo-mandant",
                    sha256_value=digest,
                    original_filename="Invoice E24-13525-RE.pdf",
                )

            self.assertEqual(resolved, existing)

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
