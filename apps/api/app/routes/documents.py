from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.repositories.documents import (
    create_audit_event,
    create_document,
    create_extraction,
    find_document_by_hash,
    get_document,
    list_documents,
    update_document_status,
)
from app.services.extraction import run_mock_extraction
from app.services.storage import delete_stored_document, store_original_document

router = APIRouter()


@router.get("")
def get_documents(tenant_id: str = "demo-mandant") -> dict[str, list[dict]]:
    return {"documents": list_documents(tenant_id=tenant_id)}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("demo-mandant"),
) -> dict:
    stored = await store_original_document(file=file, tenant_id=tenant_id)
    existing = find_document_by_hash(tenant_id=tenant_id, sha256=stored.sha256)
    if existing:
        delete_stored_document(stored.storage_path)
        create_audit_event(
            tenant_id=tenant_id,
            event_type="document_duplicate_detected",
            entity_type="document",
            entity_id=existing["id"],
            details={"sha256": stored.sha256, "original_filename": stored.original_filename},
        )
        return {"document": existing, "duplicate": True}

    document = create_document(tenant_id=tenant_id, stored=stored)
    create_audit_event(
        tenant_id=tenant_id,
        event_type="document_uploaded",
        entity_type="document",
        entity_id=document["id"],
        details={"sha256": document["sha256"], "original_filename": document["original_filename"]},
    )
    return {
        "document": document,
        "duplicate": False,
    }


@router.post("/{document_id}/extract")
def extract_document(document_id: str) -> dict:
    document = get_document(document_id=document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    create_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document_extraction_started",
        entity_type="document",
        entity_id=document["id"],
    )
    update_document_status(document_id=document["id"], status="extraction_pending")

    result = run_mock_extraction(original_filename=document["original_filename"])
    extraction = create_extraction(
        document_id=document["id"],
        tenant_id=document["tenant_id"],
        provider=result["provider"],
        status=result["status"],
        fields=result["fields"],
        warnings=result["warnings"],
        confidence=result["confidence"],
    )
    update_document_status(document_id=document["id"], status="extracted")
    create_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document_extraction_completed",
        entity_type="document",
        entity_id=document["id"],
        details={"extraction_id": extraction["id"], "provider": extraction["provider"]},
    )

    return {"extraction": extraction}
