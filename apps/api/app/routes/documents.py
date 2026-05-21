from decimal import Decimal
from csv import DictWriter
from io import BytesIO, StringIO
from re import sub
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.database import (
    approve_document_review,
    build_booking_export_rows,
    create_document_record,
    delete_document,
    list_documents,
    list_documents_for_month,
    prepare_document_review,
    reopen_document_review,
    ReviewApprovalError,
    select_payment_decision,
    update_booking_suggestion,
    validate_document_review,
)
from app.services.extraction import run_mock_extraction
from app.services.storage import (
    delete_stored_document,
    delete_stored_document_path,
    resolve_stored_document_path,
    store_original_document,
    UploadRejectedError,
)
from app.routes.users import require_document_access, require_tenant_access

router = APIRouter()


class DocumentExportRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=200)
    tenant_id: str | None = None


class BookingSuggestionUpdate(BaseModel):
    booking_type: Literal["incoming_invoice", "credit_note"]
    cost_category: Literal[
        "material",
        "subcontractor",
        "fuel_vehicle",
        "software_subscription",
        "security_subscription",
        "general_overhead",
    ] | None = None
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
    if invalid_documents:
        raise HTTPException(
            status_code=409,
            detail={"message": "Buchungsentwurf blockiert", "documents": invalid_documents},
        )
    rows = build_booking_export_rows(documents)
    if not rows:
        raise HTTPException(status_code=404, detail="no approved booking rows found for export")
    if format == "json":
        return {"rows": rows}

    buffer = StringIO()
    writer = DictWriter(buffer, fieldnames=list(rows[0].keys()), delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    content = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="buchungsentwurf-{tenant_id}-{year}-{month:02d}.csv"'}
    return StreamingResponse(BytesIO(content), media_type="text/csv; charset=utf-8", headers=headers)


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
    )


@router.post("/{document_id}/extract")
def extract_document(document_id: UUID, request: Request) -> dict[str, Any]:
    require_document_access(request, document_id)
    return {"document": run_mock_extraction(document_id)}


@router.post("/{document_id}/review")
def prepare_review(document_id: UUID, request: Request) -> dict[str, Any]:
    require_document_access(request, document_id)
    user = getattr(request.state, "user", None) or {}
    actor = user.get("email") or "system"
    document = prepare_document_review(document_id, actor=actor)
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
        raise HTTPException(status_code=409, detail={"message": "Freigabe blockiert", "errors": error.errors}) from error
    if document is None:
        raise HTTPException(status_code=404, detail="document with extraction not found")
    return {"document": document}


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
    require_document_access(request, document_id)
    user = getattr(request.state, "user", None) or {}
    actor = user.get("email") or "system"
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
    require_document_access(request, document_id)
    document = delete_document(document_id)

    delete_stored_document_path(document["storage_path"])
    return {"document": document, "status": "deleted"}

