from pathlib import Path
from unittest.mock import Mock, patch

from app.services.runtime_diagnostics import _parse_tesseract_languages, ocr_runtime_status


def test_api_image_installs_tesseract_for_pdf_ocr():
    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")

    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-deu" in dockerfile


def test_parse_tesseract_languages_skips_header():
    assert _parse_tesseract_languages("List of available languages in /x:\neng\ndeu\n") == ["eng", "deu"]


def test_ocr_runtime_status_reports_tesseract_languages():
    completed = Mock(returncode=0, stdout="List of available languages in /x:\neng\ndeu\n", stderr="")

    with (
        patch("app.services.runtime_diagnostics.shutil.which", return_value="/usr/bin/tesseract"),
        patch("app.services.runtime_diagnostics.subprocess.run", return_value=completed),
        patch("app.services.runtime_diagnostics._pymupdf_available", return_value=True),
    ):
        status = ocr_runtime_status()

    assert status["pymupdf_available"] is True
    assert status["tesseract_available"] is True
    assert status["languages"] == ["eng", "deu"]
    assert status["german_available"] is True
    assert status["error"] is None
