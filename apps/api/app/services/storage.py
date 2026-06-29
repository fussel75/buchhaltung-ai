from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from shutil import copy2
from uuid import uuid4

from fastapi import UploadFile

from app.config import get_settings

UPLOAD_CHUNK_SIZE = 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".xml"}
ALLOWED_BWA_SUFFIXES = {".pdf", ".csv", ".txt", ".xlsx"}
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/pdf",
    "application/xml",
    "text/xml",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/tiff",
    "application/octet-stream",
}
ALLOWED_BWA_CONTENT_TYPES = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}
CONTENT_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".xml": "application/xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class StoredDocument:
    original_filename: str
    content_type: str
    sha256: str
    size_bytes: int
    storage_path: Path


class UploadRejectedError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _safe_suffix(filename: str | None) -> str:
    if not filename:
        return ".bin"
    suffix = Path(filename).suffix.lower()
    return suffix if suffix else ".bin"


def _safe_tenant_segment(tenant_id: str) -> str:
    segment = sub(r"[^a-zA-Z0-9._-]+", "-", tenant_id.strip()).strip(".-")
    return segment or "unknown-tenant"


async def store_original_document(file: UploadFile, tenant_id: str) -> StoredDocument:
    return await _store_uploaded_file(
        file=file,
        tenant_id=tenant_id,
        bucket="originals",
        allowed_suffixes=ALLOWED_UPLOAD_SUFFIXES,
        allowed_content_types=ALLOWED_UPLOAD_CONTENT_TYPES,
    )


async def store_bwa_document(file: UploadFile, tenant_id: str) -> StoredDocument:
    return await _store_uploaded_file(
        file=file,
        tenant_id=tenant_id,
        bucket="bwa",
        allowed_suffixes=ALLOWED_BWA_SUFFIXES,
        allowed_content_types=ALLOWED_BWA_CONTENT_TYPES,
    )


async def _store_uploaded_file(
    file: UploadFile,
    tenant_id: str,
    bucket: str,
    allowed_suffixes: set[str],
    allowed_content_types: set[str],
) -> StoredDocument:
    settings = get_settings()
    now = datetime.now(UTC)
    suffix = _safe_suffix(file.filename)
    content_type = effective_content_type(file.filename, file.content_type)
    _validate_upload_type(suffix, content_type, allowed_suffixes, allowed_content_types)

    relative_dir = Path(_safe_tenant_segment(tenant_id)) / bucket / f"{now:%Y}" / f"{now:%m}"
    target_dir = settings.storage_root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    temporary_target = target_dir / f".upload-{uuid4().hex}.tmp"
    digest = sha256()
    size_bytes = 0

    try:
        with temporary_target.open("wb") as handle:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_size_bytes:
                    raise UploadRejectedError(
                        f"Datei ist größer als das Upload-Limit von {_format_bytes(settings.max_upload_size_bytes)}.",
                        status_code=413,
                    )
                digest.update(chunk)
                handle.write(chunk)

        if size_bytes == 0:
            raise UploadRejectedError("Leere Dateien können nicht hochgeladen werden.")

        hex_digest = digest.hexdigest()
        target = target_dir / f"{hex_digest[:16]}-{uuid4().hex}{suffix}"
        temporary_target.replace(target)
    except Exception:
        temporary_target.unlink(missing_ok=True)
        raise

    return StoredDocument(
        original_filename=file.filename or "unknown",
        content_type=content_type,
        sha256=hex_digest,
        size_bytes=size_bytes,
        storage_path=target.relative_to(settings.storage_root),
    )


def effective_content_type(filename: str | None, content_type: str | None) -> str:
    return _safe_content_type(content_type, _safe_suffix(filename))


def _safe_content_type(content_type: str | None, suffix: str | None = None) -> str:
    normalized = "application/octet-stream"
    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
    if normalized == "application/octet-stream" and suffix:
        return CONTENT_TYPE_BY_SUFFIX.get(suffix.lower(), normalized)
    return normalized


def _validate_upload_type(
    suffix: str,
    content_type: str,
    allowed_suffixes: set[str],
    allowed_content_types: set[str],
) -> None:
    if suffix not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise UploadRejectedError(f"Dateityp nicht erlaubt. Erlaubt sind: {allowed}.", status_code=415)
    if content_type not in allowed_content_types:
        raise UploadRejectedError(f"Content-Type nicht erlaubt: {content_type}.", status_code=415)


def _format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.0f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} Bytes"


def delete_stored_document(stored: StoredDocument) -> None:
    delete_stored_document_path(str(stored.storage_path))


def delete_stored_document_path(storage_path: str) -> None:
    settings = get_settings()
    target = resolve_stored_document_path(storage_path)
    if target.exists():
        target.unlink()


def rename_stored_document(storage_path: str, normalized_filename: str) -> Path:
    settings = get_settings()
    source = resolve_stored_document_path(storage_path)
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


def resolve_stored_document_path(storage_path: str) -> Path:
    settings = get_settings()
    root = settings.storage_root.resolve()
    target = (root / storage_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("storage path escapes storage root")
    return target


def _safe_filename(filename: str, fallback_suffix: str) -> str:
    suffix = Path(filename).suffix or fallback_suffix
    stem = Path(filename).stem if Path(filename).suffix else filename
    stem = sub(r'[<>:"/\\|?*]+', " ", stem)
    stem = sub(r"\s+", " ", stem).strip().rstrip(".")
    if not stem:
        stem = "rechnung"
    return f"{stem[:180]}{suffix.lower()}"

