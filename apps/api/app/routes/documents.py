from fastapi import APIRouter, File, Form, UploadFile

from app.services.storage import store_original_document

router = APIRouter()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("demo-mandant"),
) -> dict[str, str | int]:
    stored = await store_original_document(file=file, tenant_id=tenant_id)
    return {
        "tenant_id": tenant_id,
        "original_filename": stored.original_filename,
        "content_type": stored.content_type,
        "sha256": stored.sha256,
        "size_bytes": stored.size_bytes,
        "storage_path": str(stored.storage_path),
        "status": "stored",
    }

