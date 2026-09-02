from uuid import UUID

from fastapi import HTTPException

from app.services.database import (
    claim_document_for_bulk_job,
    document_extraction_health,
    finish_document_bulk_job,
    get_document,
    mark_document_bulk_job_item,
    mark_document_bulk_job_running,
    prepare_document_review,
    release_document_bulk_claim,
    summarize_reextraction_health_changes,
)
from app.services.extraction import run_ai_extraction, run_mock_extraction


_CANCELLED_BULK_JOBS: set[UUID] = set()


def request_bulk_job_stop(job_id: UUID) -> None:
    _CANCELLED_BULK_JOBS.add(job_id)


def run_document_bulk_job(job_id: UUID, actor: str = "system") -> None:
    job = mark_document_bulk_job_running(job_id)
    if job is None or job["status"] not in {"queued", "running"}:
        return

    health_entries: list[dict] = []
    cancelled = False
    try:
        for item in job["items"]:
            if job_id in _CANCELLED_BULK_JOBS:
                cancelled = True
                break
            document_id = UUID(item["document_id"])
            mark_document_bulk_job_item(job_id, document_id, "running")
            claim = claim_document_for_bulk_job(document_id, job_id, _expected_status(job["action"]))
            if claim is None:
                mark_document_bulk_job_item(job_id, document_id, "skipped", "Beleg ist nicht mehr im passenden Status.")
                if job["action"] in {"reextract", "ai_extract"}:
                    health_entries.append(
                        {
                            "document_id": str(document_id),
                            "status": "skipped",
                            "error": "Beleg ist nicht mehr im passenden Status.",
                        }
                    )
                continue
            before_health = document_extraction_health(get_document(document_id)) if job["action"] in {"reextract", "ai_extract"} else None
            try:
                _run_document_bulk_action(job["action"], document_id, actor, job_id, before_health=before_health)
            except Exception as error:  # noqa: BLE001 - keep one bad document from stopping the batch
                mark_document_bulk_job_item(job_id, document_id, "failed", _error_message(error))
                if job["action"] in {"reextract", "ai_extract"}:
                    health_entries.append(
                        {
                            "document_id": str(document_id),
                            "status": "failed",
                            "before": before_health,
                            "error": _error_message(error),
                        }
                    )
            else:
                mark_document_bulk_job_item(job_id, document_id, "succeeded")
                if job["action"] in {"reextract", "ai_extract"}:
                    health_entries.append(
                        {
                            "document_id": str(document_id),
                            "status": "succeeded",
                            "before": before_health,
                            "after": document_extraction_health(get_document(document_id)),
                        }
                    )
            finally:
                release_document_bulk_claim(document_id, job_id)
        if cancelled:
            _finish_bulk_job(job_id, "failed", job["action"], health_entries, "Manuell abgebrochen.")
        else:
            _finish_bulk_job(job_id, "completed", job["action"], health_entries)
    except Exception as error:  # noqa: BLE001 - persist fatal job errors for the UI
        _finish_bulk_job(job_id, "failed", job["action"], health_entries, _error_message(error))
    finally:
        _CANCELLED_BULK_JOBS.discard(job_id)


def _run_document_bulk_action(
    action: str,
    document_id: UUID,
    actor: str,
    job_id: UUID,
    *,
    before_health: dict | None = None,
) -> None:
    if action == "extract":
        document = get_document(document_id)
        run_mock_extraction(
            document_id,
            processing_job_id=job_id,
            allow_ai=_should_allow_bulk_ai(document, before_health),
            allow_ocr=_should_allow_initial_ocr(document),
        )
        return
    if action == "reextract":
        document = get_document(document_id)
        run_mock_extraction(
            document_id,
            processing_job_id=job_id,
            force=True,
            actor=actor,
            allow_ai=_should_allow_bulk_ai(document, before_health),
            allow_ocr=True,
        )
        return
    if action == "ai_extract":
        run_ai_extraction(document_id, actor=actor)
        return
    if action == "prepare_review":
        document = prepare_document_review(document_id, actor=actor)
        if document is None:
            raise ValueError("document with extraction not found")
        return
    raise ValueError("unsupported bulk action")


def _should_allow_initial_ocr(document: dict | None) -> bool:
    if not document:
        return False
    filename = str(document.get("original_filename") or "").lower()
    markers = (
        "pdf nicht lesbar",
        "nicht lesbar",
        "freistellung",
        "freistellungsbescheinigung",
        "freistellungsauftrag",
        "bescheinigung",
        "nachweis",
        "steuerbescheid",
        "kst bescheid",
        "gewst bescheid",
        "gewerbesteuer",
        "tankbeleg",
        "bareinlage",
    )
    return any(marker in filename for marker in markers)


def _should_allow_bulk_ai(document: dict | None, before_health: dict | None) -> bool:
    if before_health:
        if before_health.get("problem_count", 0) > 0:
            return True
        if before_health.get("is_general_cost") or before_health.get("is_assignment_unresolved"):
            return True
        if before_health.get("needs_assignment_review") or before_health.get("is_supplier_unresolved"):
            return True
        if before_health.get("ai_status") == "failed":
            return True
    if not document:
        return False
    extraction = document.get("extraction") if isinstance(document.get("extraction"), dict) else {}
    raw_result = extraction.get("raw_result") if isinstance(extraction.get("raw_result"), dict) else {}
    warnings = extraction.get("warnings") or raw_result.get("warnings") or []
    if warnings:
        return True
    try:
        confidence = float(extraction.get("confidence") or raw_result.get("confidence") or 1)
    except (TypeError, ValueError):
        confidence = 1
    if confidence < 0.90:
        return True
    if raw_result.get("assignment_type") in {"assignment_unresolved", "general_cost"}:
        return True
    return _should_allow_initial_ocr(document)


def _expected_status(action: str) -> str | list[str]:
    if action == "extract":
        return "review_pending"
    if action == "reextract":
        return ["extracted", "review_ready"]
    if action == "ai_extract":
        return ["extracted", "review_ready"]
    if action == "prepare_review":
        return "extracted"
    raise ValueError("unsupported bulk action")


def _error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)
    return str(error) or error.__class__.__name__


def _bulk_job_summary(action: str, health_entries: list[dict]) -> dict:
    if action not in {"reextract", "ai_extract"}:
        return {}
    return summarize_reextraction_health_changes(health_entries, action=action)


def _finish_bulk_job(
    job_id: UUID,
    status: str,
    action: str,
    health_entries: list[dict],
    error: str | None = None,
) -> None:
    summary = _bulk_job_summary(action, health_entries)
    if summary:
        finish_document_bulk_job(job_id, status, error, summary=summary)
        return
    if error is not None:
        finish_document_bulk_job(job_id, status, error)
        return
    finish_document_bulk_job(job_id, status)
