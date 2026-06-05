from decimal import Decimal
from csv import DictWriter
from datetime import date
from io import BytesIO, StringIO
from re import sub
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.cost_categories import CostCategory
from app.services.database import (
    approve_document_review,
    BulkJobConflictError,
    build_booking_export_rows,
    create_document_bulk_job,
    create_document_record,
    delete_document,
    get_document_bulk_job,
    list_document_bulk_jobs,
    list_documents,
    list_documents_for_month,
    prepare_document_review,
    reopen_document_review,
    ReviewApprovalError,
    select_payment_decision,
    update_booking_suggestion,
    update_document_extraction,
    validate_booking_export_rows,
    validate_document_review,
    validate_document_review_details,
)
from app.services.bulk_jobs import run_document_bulk_job
from app.services.extraction import run_mock_extraction
from app.services.preview import PreviewError, extract_pdf_preview_text, pdf_page_count, render_pdf_preview_page
from app.services.storage import (
    delete_stored_document,
    delete_stored_document_path,
    resolve_stored_document_path,
    store_original_document,
    UploadRejectedError,
)
from app.routes.users import require_admin, require_document_access, require_tenant_access

router = APIRouter()


class DocumentExportRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=200)
    tenant_id: str | None = None


class DocumentBulkJobRequest(BaseModel):
    tenant_id: str
    document_ids: list[UUID] = Field(min_length=1, max_length=500)


class DocumentReextractRequest(BaseModel):
    confirm: bool = False


class BookingSuggestionUpdate(BaseModel):
    booking_type: Literal["incoming_invoice", "credit_note"]
    cost_category: CostCategory | None = None
    assignment_code: str | None = Field(default=None, max_length=80)
    assignment_kind: Literal[
        "construction_project",
        "construction_or_dropoff_site",
        "location",
        "cost_object",
        "vehicle",
        "subscription",
        "department",
    ] | None = None
    description: str | None = Field(default=None, max_length=500)
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    currency: str = Field(default="EUR", pattern="^[A-Z]{3}$", max_length=3)

    def normalized(self) -> dict[str, Any]:
        assignment_code = self.assignment_code.strip() if self.assignment_code else None
        description = self.description.strip() if self.description else None
        return {
            "booking_type": self.booking_type,
            "cost_category": self.cost_category,
            "assignment_code": assignment_code or None,
            "assignment_kind": self.assignment_kind,
            "description": description or None,
            "net_amount": self.net_amount,
            "tax_amount": self.tax_amount,
            "gross_amount": self.gross_amount,
            "currency": self.currency,
        }


class PaymentDecisionUpdate(BaseModel):
    payment_type: Literal["full_amount", "cash_discount", "credit_note_settlement"]


class ExtractionUpdate(BaseModel):
    supplier_name: str | None = Field(default=None, max_length=300)
    invoice_number: str | None = Field(default=None, max_length=120)
    invoice_date: date | None = None
    service_period: str | None = Field(default=None, max_length=120)
    customer_number: str | None = Field(default=None, max_length=120)
    document_type: Literal["incoming_invoice", "credit_note"] | None = None
    cost_category: CostCategory | None = None
    assignment_code: str | None = Field(default=None, max_length=80)
    assignment_kind: Literal[
        "construction_project",
        "construction_or_dropoff_site",
        "location",
        "cost_object",
        "vehicle",
        "subscription",
        "department",
    ] | None = None
    net_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$", max_length=3)
    due_date: date | None = None
    discount_due_date: date | None = None
    discount_base: Decimal | None = None
    discount_amount: Decimal | None = None
    discounted_payable_amount: Decimal | None = None
    item_summary: str | None = Field(default=None, max_length=500)

    def normalized(self) -> dict[str, Any]:
        values = self.model_dump(exclude_unset=True)
        for key, value in list(values.items()):
            if isinstance(value, str):
                values[key] = value.strip() or None
        return values


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


def _download_filename(document: dict[str, Any]) -> str:
    return _safe_visible_filename(
        document.get("normalized_filename")
        or document.get("original_filename")
        or f"{document['id']}.pdf"
    )


def _safe_visible_filename(filename: str) -> str:
    cleaned = sub(r'[<>:"/\\|?*]+', " ", filename)
    cleaned = sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "beleg.pdf"


def _safe_archive_name(filename: str, fallback_suffix: str = ".pdf") -> str:
    stemmed = sub(r'[<>:"/\\|?*]+', " ", filename)
    stemmed = sub(r"\s+", " ", stemmed).strip().rstrip(".")
    if not stemmed:
        stemmed = "beleg"
    if "." not in stemmed and fallback_suffix:
        stemmed = f"{stemmed}{fallback_suffix}"
    return stemmed[:220]


def _zip_documents(documents: list[dict[str, Any]], archive_name: str) -> StreamingResponse:
    if not documents:
        raise HTTPException(status_code=404, detail="no documents found for export")

    seen_names: dict[str, int] = {}
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for document in documents:
            path = resolve_stored_document_path(document["storage_path"])
            if not path.is_file():
                raise HTTPException(status_code=404, detail=f"stored file missing for document {document['id']}")

            archive_name_for_file = _safe_archive_name(_download_filename(document), path.suffix)
            duplicate_count = seen_names.get(archive_name_for_file, 0)
            seen_names[archive_name_for_file] = duplicate_count + 1
            if duplicate_count:
                archive_path = f"{path.stem} ({duplicate_count + 1}){path.suffix}"
                archive_name_for_file = _safe_archive_name(archive_path, path.suffix)

            archive.write(path, archive_name_for_file)

    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{archive_name}"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


def _actor(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return user.get("email") or "system"


def _ensure_not_processing(document: dict[str, Any]) -> None:
    if document.get("processing_job_id"):
        raise HTTPException(status_code=409, detail="Beleg wird gerade von einem Bulk-Job verarbeitet.")


def _validated_bulk_documents(
    request: Request,
    payload: DocumentBulkJobRequest,
    action: Literal["extract", "prepare_review"],
) -> tuple[str, list[UUID]]:
    tenant_id = _normalize_tenant_id(payload.tenant_id)
    require_tenant_access(request, tenant_id)
    document_ids = list(dict.fromkeys(payload.document_ids))
    invalid_documents: list[dict[str, str]] = []

    for document_id in document_ids:
        document = require_document_access(request, document_id)
        if document["tenant_id"] != tenant_id:
            invalid_documents.append({"document_id": str(document_id), "reason": "Beleg gehört nicht zum Mandanten."})
            continue
        if action == "extract":
            if document["status"] != "review_pending" or document.get("extraction"):
                invalid_documents.append({"document_id": str(document_id), "reason": "Beleg ist nicht offen für Extraktion."})
        elif document["status"] != "extracted" or not document.get("extraction") or document.get("booking_suggestions"):
            invalid_documents.append({"document_id": str(document_id), "reason": "Beleg ist nicht bereit für Vorschläge."})

    if invalid_documents:
        raise HTTPException(
            status_code=409,
            detail={"message": "Bulk-Job blockiert", "documents": invalid_documents},
        )
    return tenant_id, document_ids


def _start_bulk_job(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: DocumentBulkJobRequest,
    action: Literal["extract", "prepare_review"],
) -> dict[str, Any]:
    tenant_id, document_ids = _validated_bulk_documents(request, payload, action)
    actor = _actor(request)
    try:
        job = create_document_bulk_job(
            tenant_id=tenant_id,
            action=action,
            document_ids=document_ids,
            actor=actor,
        )
    except BulkJobConflictError as error:
        raise HTTPException(status_code=409, detail="Aktiver Bulk-Job für diesen Mandanten läuft bereits.") from error

    background_tasks.add_task(run_document_bulk_job, UUID(job["id"]), actor)
    return {"job": job}


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Form("demo-mandant"),
) -> dict[str, Any]:
    tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, tenant_id)
    try:
        stored = await store_original_document(file=file, tenant_id=tenant_id)
    except UploadRejectedError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    document, is_duplicate = create_document_record(tenant_id=tenant_id, stored=stored)
    if is_duplicate:
        delete_stored_document(stored)

    return {
        "document": document,
        "status": "duplicate" if is_duplicate else "review_pending",
        "is_duplicate": is_duplicate,
    }


@router.get("")
def get_documents(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict[str, list[dict[str, Any]]]:
    tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, tenant_id)
    return {"documents": list_documents(tenant_id=tenant_id)}


@router.post("/export")
def export_documents(payload: DocumentExportRequest, request: Request) -> StreamingResponse:
    documents: list[dict[str, Any]] = []
    expected_tenant_id = _normalize_tenant_id(payload.tenant_id) if payload.tenant_id else None
    if expected_tenant_id:
        require_tenant_access(request, expected_tenant_id)
    for document_id in payload.document_ids:
        document = require_document_access(request, document_id)
        if expected_tenant_id and document["tenant_id"] != expected_tenant_id:
            raise HTTPException(status_code=400, detail="document does not belong to tenant")
        documents.append(document)

    tenant_part = expected_tenant_id or documents[0]["tenant_id"]
    return _zip_documents(documents, f"belege-{tenant_part}-auswahl.zip")


@router.get("/export/month")
def export_documents_for_month(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
) -> StreamingResponse:
    tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, tenant_id)
    documents = list_documents_for_month(tenant_id=tenant_id, year=year, month=month)
    return _zip_documents(documents, f"belege-{tenant_id}-{year}-{month:02d}.zip")


@router.get("/export/bookings", response_model=None)
def export_booking_rows(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    format: Literal["csv", "json"] = Query("csv"),
) -> Any:
    tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, tenant_id)
    documents = list_documents_for_month(tenant_id=tenant_id, year=year, month=month)
    invalid_documents = []
    for document in documents:
        if document.get("status") != "review_approved":
            continue
        errors = validate_document_review(document)
        if errors:
            invalid_documents.append(
                {
                    "document_id": document.get("id"),
                    "filename": document.get("original_filename"),
                    "errors": errors,
                }
            )
    rows = build_booking_export_rows(documents)
    export_issues = validate_booking_export_rows(rows)
    if format == "json":
        if not rows:
            raise HTTPException(status_code=404, detail="no approved booking rows found for export")
        return {
            "rows": rows,
            "invalid_documents": invalid_documents,
            "export_issues": export_issues,
            "is_blocked": bool(invalid_documents or export_issues),
        }

    if invalid_documents or export_issues:
        documents_detail = invalid_documents + [
            {
                "document_id": issue.get("document_id"),
                "filename": issue.get("filename"),
                "errors": issue.get("errors") or [],
            }
            for issue in export_issues
        ]
        raise HTTPException(
            status_code=409,
            detail={"message": "Buchungsentwurf blockiert", "documents": documents_detail},
        )
    if not rows:
        raise HTTPException(status_code=404, detail="no approved booking rows found for export")

    buffer = StringIO()
    writer = DictWriter(buffer, fieldnames=list(rows[0].keys()), delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(_csv_safe_rows(rows))
    content = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="buchungsentwurf-{tenant_id}-{year}-{month:02d}.csv"'}
    return StreamingResponse(BytesIO(content), media_type="text/csv; charset=utf-8", headers=headers)


def _csv_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _csv_safe_value(key, value) for key, value in row.items()} for row in rows]


def _csv_safe_value(fieldname: str, value: Any) -> Any:
    if not isinstance(value, str) or value == "":
        return value
    stripped = value.lstrip()
    dangerous_start = ("=", "+", "@")
    if _is_csv_text_field(fieldname):
        dangerous_start = ("=", "+", "-", "@")
    if stripped and stripped[0] in dangerous_start:
        return f"'{value}"
    if value[0] in ("\t", "\r", "\n") or ord(value[0]) < 32:
        return f"'{value}"
    return value


def _is_csv_text_field(fieldname: str) -> bool:
    numeric_suffixes = ("_amount", "_percent", "_rate", "_delta")
    date_fields = {"invoice_date", "payment_due_date"}
    if fieldname in date_fields:
        return False
    return not fieldname.endswith(numeric_suffixes)


@router.post("/bulk/extract", status_code=status.HTTP_202_ACCEPTED)
def start_bulk_extraction(
    payload: DocumentBulkJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    return _start_bulk_job(request, background_tasks, payload, "extract")


@router.post("/bulk/review", status_code=status.HTTP_202_ACCEPTED)
def start_bulk_review_preparation(
    payload: DocumentBulkJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    return _start_bulk_job(request, background_tasks, payload, "prepare_review")


@router.get("/bulk-jobs")
def list_bulk_jobs(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, tenant_id)
    return {"jobs": list_document_bulk_jobs(tenant_id=tenant_id, limit=limit)}


@router.get("/bulk-jobs/{job_id}")
def get_bulk_job(job_id: UUID, request: Request) -> dict[str, Any]:
    job = get_document_bulk_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="bulk job not found")
    require_tenant_access(request, job["tenant_id"])
    return {"job": job}


@router.get("/{document_id}/file")
def get_document_file(
    document_id: UUID,
    request: Request,
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
) -> FileResponse:
    document = require_document_access(request, document_id)

    path = resolve_stored_document_path(document["storage_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="stored file missing")

    return FileResponse(
        path,
        media_type=document.get("content_type") or "application/pdf",
        filename=_download_filename(document),
        content_disposition_type=disposition,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{document_id}/preview")
def get_document_preview_meta(document_id: UUID, request: Request) -> dict[str, Any]:
    document = require_document_access(request, document_id)
    if document.get("content_type") != "application/pdf":
        raise HTTPException(status_code=415, detail="Vorschau-Metadaten sind nur für PDFs verfügbar.")

    try:
        page_count = pdf_page_count(document["storage_path"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="stored file missing") from None
    except PreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"page_count": page_count}


@router.get("/{document_id}/preview/pages/{page_number}")
def get_document_preview_page(document_id: UUID, page_number: int, request: Request) -> StreamingResponse:
    document = require_document_access(request, document_id)
    if document.get("content_type") != "application/pdf":
        raise HTTPException(status_code=415, detail="Vorschau-Seiten sind nur für PDFs verfügbar.")

    try:
        preview = render_pdf_preview_page(document["storage_path"], page_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="stored file missing") from None
    except PreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    headers = {
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
        "X-Preview-Page": str(preview.page_number),
        "X-Preview-Page-Count": str(preview.page_count),
    }
    return StreamingResponse(BytesIO(preview.png_bytes), media_type="image/png", headers=headers)


@router.get("/{document_id}/preview/pages/{page_number}/text")
def get_document_preview_page_text(document_id: UUID, page_number: int, request: Request) -> JSONResponse:
    document = require_document_access(request, document_id)
    if document.get("content_type") != "application/pdf":
        raise HTTPException(status_code=415, detail="Vorschau-Text ist nur für PDFs verfügbar.")

    try:
        preview = extract_pdf_preview_text(document["storage_path"], page_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="stored file missing") from None
    except PreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return JSONResponse(
        {
            "page_count": preview.page_count,
            "page_number": preview.page_number,
            "text": preview.text,
            "truncated": preview.truncated,
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{document_id}/extract")
def extract_document(document_id: UUID, request: Request) -> dict[str, Any]:
    require_document_access(request, document_id)
    return {"document": run_mock_extraction(document_id, actor=_actor(request))}


@router.post("/{document_id}/reextract")
def reextract_document(document_id: UUID, payload: DocumentReextractRequest, request: Request) -> dict[str, Any]:
    require_admin(request)
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Neu-Extraktion erfordert explizite Bestätigung.")
    document = require_document_access(request, document_id)
    _ensure_not_processing(document)
    return {"document": run_mock_extraction(document_id, force=True, actor=_actor(request))}


@router.post("/{document_id}/review")
def prepare_review(document_id: UUID, request: Request) -> dict[str, Any]:
    document = require_document_access(request, document_id)
    _ensure_not_processing(document)
    actor = _actor(request)
    document = prepare_document_review(document_id, actor=actor)
    if document is None:
        raise HTTPException(status_code=404, detail="document with extraction not found")
    return {"document": document}


@router.patch("/{document_id}/extraction")
def patch_document_extraction(
    document_id: UUID,
    payload: ExtractionUpdate,
    request: Request,
) -> dict[str, Any]:
    document = require_document_access(request, document_id)
    _ensure_not_processing(document)
    actor = _actor(request)
    try:
        document = update_document_extraction(
            document_id=document_id,
            values=payload.normalized(),
            actor=actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if document is None:
        raise HTTPException(status_code=404, detail="document with extraction not found")
    return {"document": document}


@router.post("/{document_id}/approve")
def approve_document(document_id: UUID, request: Request) -> dict[str, Any]:
    require_document_access(request, document_id)
    user = getattr(request.state, "user", None) or {}
    actor = user.get("email") or "system"
    try:
        document = approve_document_review(document_id, actor=actor)
    except ReviewApprovalError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": "Freigabe blockiert", "errors": error.errors, "details": error.details},
        ) from error
    if document is None:
        raise HTTPException(status_code=404, detail="document with extraction not found")
    return {"document": document}


@router.get("/{document_id}/review-validation")
def get_review_validation(document_id: UUID, request: Request) -> dict[str, Any]:
    document = require_document_access(request, document_id)
    details = []
    if document.get("status") != "review_ready":
        details.append(
            {
                "code": "invalid_review_status",
                "message": "Finale Freigabe ist nur im Status Vorschlag möglich.",
                "field": "status",
            }
        )
    details.extend(validate_document_review_details(document))
    return {
        "errors": [detail["message"] for detail in details],
        "details": details,
        "is_ready": len(details) == 0,
    }


@router.post("/{document_id}/reopen-review")
def reopen_review(document_id: UUID, request: Request) -> dict[str, Any]:
    require_document_access(request, document_id)
    user = getattr(request.state, "user", None) or {}
    actor = user.get("email") or "system"
    document = reopen_document_review(document_id, actor=actor)
    if document is None:
        raise HTTPException(status_code=404, detail="approved review not found")
    return {"document": document}


@router.patch("/{document_id}/booking-suggestions/{suggestion_id}")
def update_document_booking_suggestion(
    document_id: UUID,
    suggestion_id: UUID,
    payload: BookingSuggestionUpdate,
    request: Request,
) -> dict[str, Any]:
    require_document_access(request, document_id)
    user = getattr(request.state, "user", None) or {}
    actor = user.get("email") or "system"
    try:
        document = update_booking_suggestion(
            document_id=document_id,
            suggestion_id=suggestion_id,
            values=payload.normalized(),
            actor=actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if document is None:
        raise HTTPException(status_code=404, detail="booking suggestion not found")
    return {"document": document}


@router.post("/{document_id}/payment-decision")
def update_document_payment_decision(
    document_id: UUID,
    payload: PaymentDecisionUpdate,
    request: Request,
) -> dict[str, Any]:
    document = require_document_access(request, document_id)
    _ensure_not_processing(document)
    actor = _actor(request)
    try:
        document = select_payment_decision(
            document_id=document_id,
            payment_type=payload.payment_type,
            actor=actor,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if document is None:
        raise HTTPException(status_code=404, detail="document with extraction not found")
    return {"document": document}


@router.delete("/{document_id}")
def remove_document(document_id: UUID, request: Request) -> dict[str, Any]:
    current_document = require_document_access(request, document_id)
    _ensure_not_processing(current_document)
    document = delete_document(document_id)

    delete_stored_document_path(document["storage_path"])
    return {"document": document, "status": "deleted"}

