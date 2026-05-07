from typing import Any

from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.services.database import create_document_record, list_documents
from app.services.extraction import run_mock_extraction
from app.services.storage import delete_stored_document, store_original_document

router = APIRouter()


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("demo-mandant"),
) -> dict[str, Any]:
    tenant_id = _normalize_tenant_id(tenant_id)
    stored = await store_original_document(file=file, tenant_id=tenant_id)
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
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict[str, list[dict[str, Any]]]:
    tenant_id = _normalize_tenant_id(tenant_id)
    return {"documents": list_documents(tenant_id=tenant_id)}


@router.post("/{document_id}/extract")
def extract_document(document_id: UUID) -> dict[str, Any]:
    return {"document": run_mock_extraction(document_id)}

