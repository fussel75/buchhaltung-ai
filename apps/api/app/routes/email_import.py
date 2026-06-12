from fastapi import APIRouter, HTTPException, Query, Request, status

from app.routes.users import require_admin, require_tenant_access
from app.services.email_import import EmailImportConfigurationError, import_email_attachments

router = APIRouter()


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


@router.post("/run")
async def run_email_import(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
    limit: int | None = Query(None, ge=1, le=100),
) -> dict:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    require_admin(request)
    require_tenant_access(request, normalized_tenant_id)
    try:
        result = await import_email_attachments(normalized_tenant_id, limit=limit)
    except EmailImportConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return result
