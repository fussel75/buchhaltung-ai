from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import get_settings


@dataclass(frozen=True)
class StoredDocument:
    original_filename: str
    content_type: str
    sha256: str
    size_bytes: int
    storage_path: Path


def _safe_suffix(filename: str | None) -> str:
    if not filename:
        return ".bin"
    suffix = Path(filename).suffix.lower()
    return suffix if suffix else ".bin"


async def store_original_document(file: UploadFile, tenant_id: str) -> StoredDocument:
    settings = get_settings()
    now = datetime.now(UTC)
    content = await file.read()
    digest = sha256(content).hexdigest()
    suffix = _safe_suffix(file.filename)

    relative_dir = Path(tenant_id) / "originals" / f"{now:%Y}" / f"{now:%m}"
    target_dir = settings.storage_root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / f"{digest[:16]}-{uuid4().hex}{suffix}"
    target.write_bytes(content)

    return StoredDocument(
        original_filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        sha256=digest,
        size_bytes=len(content),
        storage_path=target.relative_to(settings.storage_root),
    )

