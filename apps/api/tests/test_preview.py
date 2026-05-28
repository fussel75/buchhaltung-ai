from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory

import fitz

from app.services import storage as storage_service
from app.services.preview import (
    MAX_PREVIEW_EDGE_PIXELS,
    MAX_PREVIEW_TEXT_CHARS,
    PreviewError,
    _safe_zoom,
    extract_pdf_preview_text,
    pdf_page_count,
    render_pdf_preview_page,
)


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

    def test_pdf_preview_extracts_selectable_page_text(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "invoice.pdf"
            self._write_pdf(pdf_path, pages=2)

            with patch.object(storage_service, "get_settings", return_value=SimpleNamespace(storage_root=root)):
                preview = extract_pdf_preview_text("invoice.pdf", 2)

            self.assertEqual(preview.page_count, 2)
            self.assertEqual(preview.page_number, 2)
            self.assertFalse(preview.truncated)
            self.assertIn("Testrechnung Seite 2", preview.text)

    def test_pdf_preview_text_is_limited(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "invoice.pdf"
            self._write_pdf_with_many_lines(pdf_path, line_count=500)

            with patch.object(storage_service, "get_settings", return_value=SimpleNamespace(storage_root=root)):
                preview = extract_pdf_preview_text("invoice.pdf", 1)

            self.assertTrue(preview.truncated)
            self.assertLessEqual(len(preview.text), MAX_PREVIEW_TEXT_CHARS)

    def _write_pdf(self, path: Path, pages: int, text: str | None = None) -> None:
        pdf = fitz.open()
        for index in range(pages):
            page = pdf.new_page(width=595, height=842)
            page.insert_text((72, 96), text or f"Testrechnung Seite {index + 1}", fontsize=18)
        pdf.save(path)
        pdf.close()

    def _write_pdf_with_many_lines(self, path: Path, line_count: int) -> None:
        pdf = fitz.open()
        page = pdf.new_page(width=595, height=max(842, 24 * line_count + 48))
        for line_index in range(line_count):
            page.insert_text(
                (36, 32 + line_index * 24),
                f"Sehr lange Testzeile {line_index:04d} " + ("X" * 120),
                fontsize=9,
            )
        pdf.save(path)
        pdf.close()
