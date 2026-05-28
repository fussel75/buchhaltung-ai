from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory

import fitz

from app.services import storage as storage_service
from app.services.preview import MAX_PREVIEW_EDGE_PIXELS, PreviewError, _safe_zoom, pdf_page_count, render_pdf_preview_page


class PdfPreviewTest(TestCase):
    def test_pdf_preview_renders_requested_page_as_png(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "invoice.pdf"
            self._write_pdf(pdf_path, pages=2)

            with patch.object(storage_service, "get_settings", return_value=SimpleNamespace(storage_root=root)):
                self.assertEqual(pdf_page_count("invoice.pdf"), 2)
                preview = render_pdf_preview_page("invoice.pdf", 2)

            self.assertEqual(preview.page_count, 2)
            self.assertEqual(preview.page_number, 2)
            self.assertTrue(preview.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(preview.png_bytes), 1000)

    def test_pdf_preview_rejects_missing_page(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "invoice.pdf"
            self._write_pdf(pdf_path, pages=1)

            with patch.object(storage_service, "get_settings", return_value=SimpleNamespace(storage_root=root)):
                with self.assertRaises(PreviewError):
                    render_pdf_preview_page("invoice.pdf", 2)

    def test_preview_zoom_is_limited_for_large_pages(self):
        self.assertLessEqual(_safe_zoom(6000, 8000, 3.0) * 8000, MAX_PREVIEW_EDGE_PIXELS)
        self.assertEqual(_safe_zoom(595, 842, 3.0), 3.0)

    def _write_pdf(self, path: Path, pages: int) -> None:
        pdf = fitz.open()
        for index in range(pages):
            page = pdf.new_page(width=595, height=842)
            page.insert_text((72, 96), f"Testrechnung Seite {index + 1}", fontsize=18)
        pdf.save(path)
        pdf.close()
