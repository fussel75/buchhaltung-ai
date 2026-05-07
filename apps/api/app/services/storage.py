from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from shutil import copy2
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


def _safe_tenant_segment(tenant_id: str) -> str:
    segment = sub(r"[^a-zA-Z0-9._-]+", "-", tenant_id.strip()).strip(".-")
    return segment or "unknown-tenant"


async def store_original_document(file: UploadFile, tenant_id: str) -> StoredDocument:
    settings = get_settings()
    now = datetime.now(UTC)
    content = await file.read()
    digest = sha256(content).hexdigest()
    suffix = _safe_suffix(file.filename)

    relative_dir = Path(_safe_tenant_segment(tenant_id)) / "originals" / f"{now:%Y}" / f"{now:%m}"
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


def delete_stored_document(stored: StoredDocument) -> None:
    delete_stored_document_path(str(stored.storage_path))


def delete_stored_document_path(storage_path: str) -> None:
    settings = get_settings()
    target = settings.storage_root / storage_path
    if target.exists():
        target.unlink()


def rename_stored_document(storage_path: str, normalized_filename: str) -> Path:
    settings = get_settings()
    source = settings.storage_root / storage_path
    if not source.exists():
        return Path(storage_path)

    target_name = _safe_filename(normalized_filename, source.suffix)
    target = source.with_name(target_name)
    if target.exists() and target != source and target.stat().st_size == source.stat().st_size:
        return target.relative_to(settings.storage_root)

    counter = 2
    while target.exists() and target != source:
        target = source.with_name(f"{target.stem} ({counter}){target.suffix}")
        counter += 1

    if target != source:
        try:
            source.rename(target)
        except PermissionError:
            copy2(source, target)
    return target.relative_to(settings.storage_root)


def _safe_filename(filename: str, fallback_suffix: str) -> str:
    suffix = Path(filename).suffix or fallback_suffix
    stem = Path(filename).stem if Path(filename).suffix else filename
    stem = sub(r'[<>:"/\\|?*]+', " ", stem)
    stem = sub(r"\s+", " ", stem).strip().rstrip(".")
    if not stem:
        stem = "rechnung"
    return f"{stem[:180]}{suffix.lower()}"

