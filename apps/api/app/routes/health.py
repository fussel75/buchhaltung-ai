from fastapi import APIRouter

from app.services.runtime_diagnostics import ocr_runtime_status

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ocr")
def health_ocr() -> dict[str, object]:
    return {"status": "ok", "ocr": ocr_runtime_status()}

