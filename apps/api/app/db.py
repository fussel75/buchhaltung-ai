from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


@contextmanager
def get_connection():
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        yield connection


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    storage_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'review_pending',
                    duplicate_of TEXT REFERENCES documents(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (tenant_id, sha256)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_tenant_created
                ON documents (tenant_id, created_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS document_extractions (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    tenant_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fields JSONB NOT NULL DEFAULT '{}'::jsonb,
                    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
                    confidence NUMERIC(5, 4) NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_document_extractions_document_created
                ON document_extractions (document_id, created_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_events_entity_created
                ON audit_events (entity_type, entity_id, created_at DESC)
                """
            )
        connection.commit()


def row_to_document(row: dict[str, Any]) -> dict[str, Any]:
    document = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "storage_path": row["storage_path"],
        "status": row["status"],
        "duplicate_of": row["duplicate_of"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }
    if "extraction_id" in row and row["extraction_id"]:
        document["extraction"] = {
            "id": row["extraction_id"],
            "provider": row["extraction_provider"],
            "status": row["extraction_status"],
            "fields": row["extraction_fields"],
            "warnings": row["extraction_warnings"],
            "confidence": float(row["extraction_confidence"]),
            "created_at": row["extraction_created_at"].isoformat(),
        }
    else:
        document["extraction"] = None
    return document
