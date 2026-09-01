from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.services.ai_extraction import maybe_enhance_extraction_with_ai


AGENT_VERSION = "steuerberater-agent-v1"


def run_tax_advisor_agent(
    *,
    document: dict[str, Any],
    extraction: dict[str, Any],
    pdf_text: str | None,
    pdf_images: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ai_extraction_enabled or not settings.ai_extraction_api_key:
        return extraction

    before = deepcopy(extraction)
    context = _agent_context(document=document, extraction=extraction, pdf_text=pdf_text, pdf_images=pdf_images)
    result = maybe_enhance_extraction_with_ai(
        document=document,
        extraction=extraction,
        pdf_text=pdf_text,
        pdf_images=pdf_images,
        force=force,
    )
    return _with_agent_trace(result=result, before=before, context=context)


def _agent_context(
    *,
    document: dict[str, Any],
    extraction: dict[str, Any],
    pdf_text: str | None,
    pdf_images: list[str] | None,
) -> dict[str, Any]:
    raw_result = extraction.get("raw_result") if isinstance(extraction.get("raw_result"), dict) else {}
    text_value = str(pdf_text or "")
    return {
        "document": {
            "id": str(document.get("id") or ""),
            "tenant_id": document.get("tenant_id"),
            "original_filename": document.get("original_filename"),
            "content_type": document.get("content_type"),
        },
        "input": {
            "pdf_text_source": getattr(pdf_text, "source", raw_result.get("pdf_text_source") or "unknown"),
            "pdf_text_length": len(text_value.strip()),
            "vision_pages": len(pdf_images or []),
        },
        "before": {
            "document_type": raw_result.get("document_type"),
            "assignment_type": raw_result.get("assignment_type"),
            "assignment_code": raw_result.get("assignment_code") or raw_result.get("project_code"),
            "problem_reasons": extraction.get("problem_reasons") or raw_result.get("problem_reasons") or [],
            "warnings": extraction.get("warnings") or raw_result.get("warnings") or [],
        },
        "workflow": [
            "read_pdf_text_or_ocr",
            "inspect_rendered_pages_when_needed",
            "classify_document_type",
            "extract_accounting_fields",
            "match_assignment_masterdata",
            "validate_required_fields_for_document_type",
            "propose_filename_and_booking_context",
        ],
    }


def _with_agent_trace(*, result: dict[str, Any], before: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(result)
    raw_result = dict(enriched.get("raw_result") or enriched)
    ai_trace = raw_result.get("ai_extraction") if isinstance(raw_result.get("ai_extraction"), dict) else {}
    raw_result["tax_advisor_agent"] = {
        "version": AGENT_VERSION,
        "status": ai_trace.get("status") or "checked",
        "model": ai_trace.get("model"),
        "used_vision": bool(ai_trace.get("used_vision")),
        "accepted_fields": ai_trace.get("accepted_fields") or [],
        "field_changes": _field_changes(before, enriched),
        "context": context,
    }
    enriched["raw_result"] = raw_result
    return enriched


def _field_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    before_raw = before.get("raw_result") if isinstance(before.get("raw_result"), dict) else {}
    after_raw = after.get("raw_result") if isinstance(after.get("raw_result"), dict) else {}
    fields = {
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
    changes = []
    for field_name in sorted(fields):
        before_value = before.get(field_name, before_raw.get(field_name))
        after_value = after.get(field_name, after_raw.get(field_name))
        if _comparable(before_value) != _comparable(after_value):
            changes.append(field_name)
    return changes


def _comparable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
