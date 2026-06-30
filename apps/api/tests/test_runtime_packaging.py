from pathlib import Path


def test_api_image_installs_tesseract_for_pdf_ocr():
    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")

    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-deu" in dockerfile
