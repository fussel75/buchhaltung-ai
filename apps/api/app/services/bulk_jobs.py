from uuid import UUID

from fastapi import HTTPException

from app.services.database import (
    claim_document_for_bulk_job,
    finish_document_bulk_job,
    get_document_bulk_job,
    mark_document_bulk_job_item,
    mark_document_bulk_job_running,
    prepare_document_review,
    release_document_bulk_claim,
)
from app.services.extraction import run_mock_extraction


def run_document_bulk_job(job_id: UUID, actor: str = "system") -> None:
    job = mark_document_bulk_job_running(job_id)
    if job is None or job["status"] not in {"queued", "running"}:
        return

    try:
        for item in job["items"]:
            document_id = UUID(item["document_id"])
            mark_document_bulk_job_item(job_id, document_id, "running")
            claim = claim_document_for_bulk_job(document_id, job_id, _expected_status(job["action"]))
            if claim is None:
                mark_document_bulk_job_item(job_id, document_id, "skipped", "Beleg ist nicht mehr im passenden Status.")
                continue
            try:
                _run_document_bulk_action(job["action"], document_id, actor, job_id)
            except Exception as error:  # noqa: BLE001 - keep one bad document from stopping the batch
                mark_document_bulk_job_item(job_id, document_id, "failed", _error_message(error))
            else:
                mark_document_bulk_job_item(job_id, document_id, "succeeded")
            finally:
                release_document_bulk_claim(document_id, job_id)
        finish_document_bulk_job(job_id, "completed")
    except Exception as error:  # noqa: BLE001 - persist fatal job errors for the UI
        finish_document_bulk_job(job_id, "failed", _error_message(error))


def _run_document_bulk_action(action: str, document_id: UUID, actor: str, job_id: UUID) -> None:
    if action == "extract":
        run_mock_extraction(document_id, processing_job_id=job_id)
        return
    if action == "prepare_review":
        document = prepare_document_review(document_id, actor=actor)
        if document is None:
            raise ValueError("document with extraction not found")
        return
    raise ValueError("unsupported bulk action")


def _expected_status(action: str) -> str:
    if action == "extract":
        return "review_pending"
    if action == "prepare_review":
        return "extracted"
    raise ValueError("unsupported bulk action")


def _error_message(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)
    return str(error) or error.__class__.__name__
