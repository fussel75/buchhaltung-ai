from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
from re import search, sub
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.config import get_settings
from app.services.cost_categories import VALID_COST_CATEGORIES
from app.services.database import list_assignment_units


AI_EXTRACTABLE_DOCUMENT_TYPES = {
    "incoming_invoice",
    "credit_note",
    "fuel_receipt",
    "tax_exemption_certificate",
    "reverse_charge_certificate",
    "other",
}

AI_MERGE_FIELDS = {
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "customer_number",
    "document_type",
    "cost_category",
    "assignment_code",
    "assignment_kind",
    "project_number",
    "net_amount",
    "tax_amount",
    "gross_amount",
    "currency",
    "due_date",
    "discount_due_date",
    "discount_base",
    "discount_amount",
    "discounted_payable_amount",
    "item_summary",
}

TOP_LEVEL_FIELDS = {
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "service_period",
    "net_amount",
    "tax_amount",
    "gross_amount",
    "currency",
}

MONEY_FIELDS = {
    "net_amount",
    "tax_amount",
    "gross_amount",
    "discount_base",
    "discount_amount",
    "discounted_payable_amount",
}

DATE_FIELDS = {"invoice_date", "due_date", "discount_due_date"}


def maybe_enhance_extraction_with_ai(
    *,
    document: dict[str, Any],
    extraction: dict[str, Any],
    pdf_text: str | None,
    force: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ai_extraction_enabled or not settings.ai_extraction_api_key:
        return extraction
    if not force and not _should_run_ai(extraction, settings.ai_extraction_min_confidence):
        return extraction

    try:
        assignment_units = list_assignment_units(document["tenant_id"])
        ai_payload = _call_ai_extractor(
            document=document,
            extraction=extraction,
            pdf_text=pdf_text or "",
            assignment_units=assignment_units,
            settings=settings,
        )
        return _merge_ai_payload(
            extraction=extraction,
            ai_payload=ai_payload,
            assignment_units=assignment_units,
            model=settings.ai_extraction_model,
        )
    except Exception as error:  # noqa: BLE001 - extraction must keep working without the AI provider
        enriched = deepcopy(extraction)
        warnings = list(enriched.get("warnings") or [])
        warnings.append(f"KI-Extraktion nicht verfügbar: {_short_error(error)}.")
        enriched["warnings"] = warnings
        raw_result = dict(enriched.get("raw_result") or enriched)
        raw_result["ai_extraction"] = {
            "status": "failed",
            "error": _short_error(error),
            "model": settings.ai_extraction_model,
            "provider": "openai_compatible",
        }
        enriched["raw_result"] = raw_result
        return enriched


def _should_run_ai(extraction: dict[str, Any], min_confidence: float) -> bool:
    raw_result = extraction.get("raw_result") or extraction
    confidence = _decimal_or_none(extraction.get("confidence"))
    if confidence is not None and confidence < Decimal(str(min_confidence)):
        return True
    if raw_result.get("source") in {"mock", "unreadable_pdf"}:
        return True
    if raw_result.get("assignment_type") == "assignment_unresolved":
        return True
    for field_name in ("supplier_name", "invoice_number", "invoice_date", "gross_amount"):
        if not extraction.get(field_name) and not raw_result.get(field_name):
            return True
    if raw_result.get("document_type") in {"tax_exemption_certificate", "reverse_charge_certificate"}:
        return False
    return False


def _call_ai_extractor(
    *,
    document: dict[str, Any],
    extraction: dict[str, Any],
    pdf_text: str,
    assignment_units: list[dict[str, Any]],
    settings: Any,
) -> dict[str, Any]:
    base_url = settings.ai_extraction_base_url.rstrip("/") + "/"
    endpoint = urljoin(base_url, "chat/completions")
    body = {
        "model": settings.ai_extraction_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": _user_prompt(
                    document=document,
                    extraction=extraction,
                    pdf_text=pdf_text[: settings.ai_extraction_max_text_chars],
                    assignment_units=assignment_units,
                ),
            },
        ],
    }
    request = Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.ai_extraction_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("AI_EXTRACTION_HTTP_REFERER", "https://buha.fristd-bau.net"),
            "X-Title": "buchhaltung-ai",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.ai_extraction_timeout_seconds) as response:  # noqa: S310 - configured trusted endpoint
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"AI provider HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"AI provider unreachable: {error.reason}") from error

    content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("AI provider returned no content")
    return _parse_json_object(content)


def _system_prompt() -> str:
    return (
        "Du bist ein sehr genauer deutscher Buchhaltungs-Extraktor. "
        "Lies Rechnungen, Gutschriften, Tankbelege und steuerliche Nachweise. "
        "Erfinde keine Werte. Wenn ein Wert nicht im Text steht, nutze null. "
        "Nutze Projektstammdaten nur, wenn Text, Kommission, Adresse, Projektnummer, Projektname, Bauherr oder Alias plausibel passt. "
        "Antworte ausschliesslich als JSON-Objekt."
    )


def _user_prompt(
    *,
    document: dict[str, Any],
    extraction: dict[str, Any],
    pdf_text: str,
    assignment_units: list[dict[str, Any]],
) -> str:
    project_context = [
        {
            "code": unit.get("code"),
            "project_number": unit.get("project_number"),
            "order_number": unit.get("order_number"),
            "customer_number": unit.get("customer_number"),
            "name": unit.get("label"),
            "address": _assignment_address(unit),
            "client_name": unit.get("client_name"),
            "description": unit.get("description"),
            "aliases": unit.get("aliases") or [],
            "kind": unit.get("kind"),
            "is_active": unit.get("is_active"),
        }
        for unit in assignment_units[:120]
        if unit.get("is_active")
    ]
    schema = {
        "document_type": "incoming_invoice|credit_note|fuel_receipt|tax_exemption_certificate|reverse_charge_certificate|other|null",
        "supplier_name": "string|null",
        "invoice_number": "string|null",
        "customer_number": "string|null",
        "invoice_date": "YYYY-MM-DD|null",
        "due_date": "YYYY-MM-DD|null",
        "discount_due_date": "YYYY-MM-DD|null",
        "net_amount": "decimal string|null",
        "tax_amount": "decimal string|null",
        "gross_amount": "decimal string|null",
        "discount_base": "decimal string|null",
        "discount_amount": "decimal string|null",
        "discounted_payable_amount": "decimal string|null",
        "currency": "EUR",
        "cost_category": "material|subcontractor|fuel_vehicle|software_subscription|security_subscription|general_overhead|null",
        "assignment_code": "Projektname/Code aus Projektliste|null",
        "project_number": "Projektnummer aus Projektliste|null",
        "assignment_kind": "construction_project|construction_or_dropoff_site|location|cost_object|vehicle|subscription|department|null",
        "item_summary": "erste relevante Positionszeile oder Leistung|null",
        "normalized_filename": "Dateinamenvorschlag|null",
        "confidence": "0.0 bis 1.0",
        "evidence": ["kurze Belege aus Text, die die Entscheidung belegen"],
        "warnings": ["Unsicherheiten"],
    }
    return json.dumps(
        {
            "task": "Extrahiere und verbessere die vorhandenen Belegdaten. Gib nur Felder aus, die durch den Text oder Projektliste belegbar sind.",
            "document": {
                "original_filename": document.get("original_filename"),
                "content_type": document.get("content_type"),
                "size_bytes": document.get("size_bytes"),
            },
            "current_extraction": _json_safe(extraction),
            "allowed_cost_categories": sorted(VALID_COST_CATEGORIES),
            "project_masterdata": project_context,
            "expected_json_schema": schema,
            "pdf_text": pdf_text,
        },
        ensure_ascii=False,
        indent=2,
    )


def _merge_ai_payload(
    *,
    extraction: dict[str, Any],
    ai_payload: dict[str, Any],
    assignment_units: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    enriched = deepcopy(extraction)
    raw_result = dict(enriched.get("raw_result") or enriched)
    normalized_ai = _normalize_ai_payload(ai_payload, assignment_units)
    accepted: dict[str, Any] = {}

    for field_name in AI_MERGE_FIELDS:
        if field_name not in normalized_ai:
            continue
        value = normalized_ai[field_name]
        if value in (None, ""):
            continue
        current_value = enriched.get(field_name) if field_name in TOP_LEVEL_FIELDS else raw_result.get(field_name)
        if _should_replace_value(field_name, current_value, value, raw_result):
            accepted[field_name] = value
            if field_name in TOP_LEVEL_FIELDS:
                enriched[field_name] = value
            raw_result[field_name] = value

    if accepted.get("assignment_code"):
        raw_result.pop("project_code", None)
        raw_result["assignment_type"] = "assigned"
    if "document_type" in accepted and accepted["document_type"] == "credit_note":
        raw_result["document_type"] = "credit_note"

    ai_confidence = _decimal_or_none(normalized_ai.get("confidence"))
    current_confidence = _decimal_or_none(enriched.get("confidence")) or Decimal("0.50")
    if ai_confidence is not None and accepted:
        enriched["confidence"] = max(current_confidence, min(ai_confidence, Decimal("0.98")))

    warnings = list(enriched.get("warnings") or [])
    warnings.extend(str(item) for item in normalized_ai.get("warnings") or [] if item)
    if accepted:
        warnings.append("KI-Extraktion hat unsichere Felder ergänzt; fachlich prüfen.")
    enriched["warnings"] = _unique(warnings)
    raw_result["ai_extraction"] = {
        "status": "applied" if accepted else "no_changes",
        "model": model,
        "accepted_fields": sorted(accepted.keys()),
        "confidence": str(ai_confidence) if ai_confidence is not None else None,
        "evidence": normalized_ai.get("evidence") or [],
        "warnings": normalized_ai.get("warnings") or [],
    }
    raw_result["source"] = _source_with_ai(raw_result.get("source"))
    enriched["raw_result"] = raw_result
    return enriched


def _normalize_ai_payload(ai_payload: dict[str, Any], assignment_units: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {key: ai_payload.get(key) for key in AI_MERGE_FIELDS | {"confidence", "evidence", "warnings", "normalized_filename"}}
    document_type = payload.get("document_type")
    if document_type not in AI_EXTRACTABLE_DOCUMENT_TYPES:
        payload["document_type"] = None
    if payload.get("cost_category") not in VALID_COST_CATEGORIES:
        payload["cost_category"] = None
    if payload.get("currency"):
        payload["currency"] = str(payload["currency"]).strip().upper()[:3]
    for field_name in MONEY_FIELDS:
        payload[field_name] = _decimal_or_none(payload.get(field_name))
    for field_name in DATE_FIELDS:
        payload[field_name] = _date_or_none(payload.get(field_name))
    payload["confidence"] = _decimal_or_none(payload.get("confidence"))
    assignment = _resolve_assignment(payload, assignment_units)
    if assignment:
        payload["assignment_code"] = _assignment_code(assignment)
        payload["assignment_kind"] = assignment.get("kind")
        payload["project_number"] = assignment.get("project_number")
    else:
        payload["assignment_code"] = None
        payload["project_number"] = None
        payload["assignment_kind"] = None
    payload["evidence"] = [str(item)[:300] for item in payload.get("evidence") or [] if item][:8]
    payload["warnings"] = [str(item)[:300] for item in payload.get("warnings") or [] if item][:8]
    for field_name in ("supplier_name", "invoice_number", "customer_number", "item_summary"):
        if payload.get(field_name) is not None:
            payload[field_name] = str(payload[field_name]).strip()[:500] or None
    return payload


def _resolve_assignment(payload: dict[str, Any], assignment_units: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        payload.get("project_number"),
        payload.get("assignment_code"),
    ]
    normalized_candidates = {_normalize_lookup(value) for value in candidates if value}
    for assignment in assignment_units:
        values = {
            assignment.get("project_number"),
            assignment.get("code"),
            assignment.get("label"),
            *list(assignment.get("aliases") or []),
        }
        if normalized_candidates & {_normalize_lookup(value) for value in values if value}:
            return assignment
    return None


def _assignment_code(assignment: dict[str, Any]) -> str | None:
    code = assignment.get("code")
    label = assignment.get("label")
    if code and _looks_like_project_number(code) and label and not _looks_like_project_number(label):
        return label
    return code


def _assignment_address(unit: dict[str, Any]) -> str | None:
    address = unit.get("address_line")
    postal_code = unit.get("postal_code")
    city = unit.get("city")
    if address and postal_code and city:
        return f"{address}, {postal_code} {city}"
    return address


def _should_replace_value(field_name: str, current_value: Any, new_value: Any, raw_result: dict[str, Any]) -> bool:
    if field_name in {"assignment_code", "project_number", "assignment_kind"}:
        return bool(new_value) and (not current_value or raw_result.get("assignment_type") == "assignment_unresolved")
    if current_value in (None, "", "-", "MOCK"):
        return True
    if field_name == "invoice_number" and str(current_value).startswith("MOCK-"):
        return True
    if field_name == "supplier_name" and _looks_like_filename_guess(str(current_value)):
        return True
    if field_name in MONEY_FIELDS and _decimal_or_none(current_value) is None:
        return True
    return False


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = search(r"\{[\s\S]*\}", content)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI response is not a JSON object")
    return parsed


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip().replace("EUR", "").replace("€", "").strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _date_or_none(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if search(r"^20\d{2}-\d{2}-\d{2}$", text):
        return text
    match = search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if match:
        day, month, year = match.groups()
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _normalize_lookup(value: Any) -> str:
    return sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _looks_like_project_number(value: str | None) -> bool:
    return bool(value and search(r"^\d{2}-\d{5}$", value.strip()))


def _looks_like_filename_guess(value: str) -> bool:
    compact = _normalize_lookup(value)
    return bool(search(r"\d", compact)) and not any(marker in compact for marker in ("gmbh", "ohg", "kg", "ag"))


def _source_with_ai(source: Any) -> str:
    source_text = str(source or "rules")
    return source_text if source_text.endswith("+ai") else f"{source_text}+ai"


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _short_error(error: Exception) -> str:
    return sub(r"\s+", " ", str(error) or error.__class__.__name__)[:300]
