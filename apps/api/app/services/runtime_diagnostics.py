from __future__ import annotations

import shutil
import subprocess
from typing import Any


def ocr_runtime_status() -> dict[str, Any]:
    tesseract_path = shutil.which("tesseract")
    languages: list[str] = []
    tesseract_error: str | None = None

    if tesseract_path:
        try:
            completed = subprocess.run(
                [tesseract_path, "--list-langs"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                languages = _parse_tesseract_languages(completed.stdout)
            else:
                tesseract_error = (completed.stderr or completed.stdout or "tesseract failed").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            tesseract_error = str(exc)

    return {
        "pymupdf_available": _pymupdf_available(),
        "tesseract_available": bool(tesseract_path),
        "tesseract_path": tesseract_path,
        "languages": languages,
        "german_available": "deu" in languages,
        "error": tesseract_error,
    }


def _pymupdf_available() -> bool:
    try:
        import fitz  # noqa: F401
    except ImportError:
        return False
    return True


def _parse_tesseract_languages(output: str) -> list[str]:
    languages = []
    for line in output.splitlines():
        value = line.strip()
        if not value or value.lower().startswith("list of"):
            continue
        languages.append(value)
    return languages
