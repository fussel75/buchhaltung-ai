from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from re import finditer, search, sub
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

from app.services.storage import resolve_stored_document_path


MAX_TEXT_LENGTH = 120_000
MAX_ACCOUNT_HINTS = 80


@dataclass(frozen=True)
class BwaAnalysis:
    period: str | None
    account_hints: list[dict[str, Any]]
    warnings: list[str]
    text_excerpt: str


def analyze_bwa_file(storage_path: str, original_filename: str, content_type: str | None = None) -> BwaAnalysis:
    path = resolve_stored_document_path(storage_path)
    suffix = Path(original_filename or path.name).suffix.lower()
    warnings: list[str] = []

    if suffix == ".pdf" or content_type == "application/pdf":
        text = _extract_pdf_text(path, warnings)
    elif suffix == ".xlsx":
        text = _extract_xlsx_text(path, warnings)
    else:
        text = _extract_plain_text(path, warnings)

    normalized_text = _normalize_text(text)
    return BwaAnalysis(
        period=_detect_period(normalized_text),
        account_hints=_account_hints(normalized_text),
        warnings=warnings,
        text_excerpt=normalized_text[:4000],
    )


def _extract_pdf_text(path: Path, warnings: list[str]) -> str:
    try:
        reader = PdfReader(str(path))
        parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(parts).strip()
    except Exception as error:  # pragma: no cover - pypdf internals vary
        warnings.append(f"PDF-Text konnte nicht gelesen werden: {error}")
        return ""
    if not text:
        warnings.append("PDF enthält keinen direkt lesbaren Text. OCR ist für BWA-Import noch nicht aktiv.")
    return text


def _extract_plain_text(path: Path, warnings: list[str]) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    warnings.append("Textdatei konnte nur mit Ersatzzeichen gelesen werden.")
    return raw.decode("utf-8", errors="replace")


def _extract_xlsx_text(path: Path, warnings: list[str]) -> str:
    try:
        with ZipFile(path) as workbook:
            shared_strings = _xlsx_shared_strings(workbook)
            sheet_names = sorted(name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet"))
            rows: list[str] = []
            for sheet_name in sheet_names:
                xml = workbook.read(sheet_name)
                root = ElementTree.fromstring(xml)
                for row in root.findall(".//{*}row"):
                    cells = [_xlsx_cell_text(cell, shared_strings) for cell in row.findall("{*}c")]
                    if any(cells):
                        rows.append(" ".join(cell for cell in cells if cell))
            return "\n".join(rows)
    except Exception as error:  # pragma: no cover - invalid xlsx files differ
        warnings.append(f"Excel-Datei konnte nicht gelesen werden: {error}")
        return ""


def _xlsx_shared_strings(workbook: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(".//{*}si"):
        values.append("".join(text.text or "" for text in item.findall(".//{*}t")))
    return values


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    value = cell.find("{*}v")
    if value is None or value.text is None:
        return ""
    raw_value = value.text.strip()
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(raw_value)]
        except (IndexError, ValueError):
            return raw_value
    return raw_value


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = sub(r"[ \t]+", " ", text)
    text = sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_LENGTH]


def _detect_period(text: str) -> str | None:
    patterns = [
        r"\b(20\d{2})[-/.](0[1-9]|1[0-2])\b",
        r"\b(0[1-9]|1[0-2])[-/.](20\d{2})\b",
        r"\b(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(20\d{2})\b",
    ]
    for pattern in patterns:
        match = search(pattern, text, flags=2)
        if not match:
            continue
        groups = match.groups()
        if groups[0].startswith("20"):
            return f"{groups[0]}-{groups[1]}"
        if groups[0].isdigit():
            return f"{groups[1]}-{groups[0]}"
        return f"{groups[1]}-{_month_number(groups[0])}"
    return None


def _month_number(month_name: str) -> str:
    months = {
        "januar": "01",
        "februar": "02",
        "märz": "03",
        "april": "04",
        "mai": "05",
        "juni": "06",
        "juli": "07",
        "august": "08",
        "september": "09",
        "oktober": "10",
        "november": "11",
        "dezember": "12",
    }
    return months.get(month_name.lower(), "01")


def _account_hints(text: str) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        hint = _account_hint_from_line(line)
        if not hint:
            continue
        key = (hint["account"], hint["label"].lower())
        if key in seen:
            continue
        seen.add(key)
        hints.append(hint)
        if len(hints) >= MAX_ACCOUNT_HINTS:
            break
    return hints


def _account_hint_from_line(line: str) -> dict[str, Any] | None:
    cleaned = sub(r"\s+", " ", line).strip()
    if not cleaned:
        return None
    match = search(r"\b(\d{3,8})\b\s+(.+)", cleaned)
    if not match:
        return None
    account = match.group(1)
    rest = match.group(2).strip()
    if len(account) < 4 and not any(character.isalpha() for character in rest):
        return None
    amounts = [_parse_amount(value.group(0)) for value in finditer(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+\.\d{2}", rest)]
    amounts = [amount for amount in amounts if amount is not None]
    label = sub(r"\s+-?\d{1,3}(?:\.\d{3})*,\d{2}.*$", "", rest)
    label = sub(r"\s+-?\d+\.\d{2}.*$", "", label).strip(" -;\t")
    if not label or len(label) < 3:
        return None
    return {
        "account": account,
        "label": label[:120],
        "amounts": [str(amount) for amount in amounts[:6]],
    }


def _parse_amount(value: str) -> Decimal | None:
    normalized = value.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
