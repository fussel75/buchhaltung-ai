from uuid import uuid4

from psycopg.types.json import Jsonb

from app.db import get_connection, row_to_document
from app.services.storage import StoredDocument


def list_documents(tenant_id: str) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    d.*,
                    e.id AS extraction_id,
                    e.provider AS extraction_provider,
                    e.status AS extraction_status,
                    e.fields AS extraction_fields,
                    e.warnings AS extraction_warnings,
                    e.confidence AS extraction_confidence,
                    e.created_at AS extraction_created_at
                FROM documents d
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM document_extractions
                    WHERE document_id = d.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) e ON true
                WHERE d.tenant_id = %s
                ORDER BY d.created_at DESC
                """,
                (tenant_id,),
            )
            return [row_to_document(row) for row in cursor.fetchall()]


def find_document_by_hash(tenant_id: str, sha256: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM documents
                WHERE tenant_id = %s AND sha256 = %s
                LIMIT 1
                """,
                (tenant_id, sha256),
            )
            row = cursor.fetchone()
            return row_to_document(row) if row else None


def create_document(tenant_id: str, stored: StoredDocument) -> dict:
    document_id = str(uuid4())
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documents (
                    id,
                    tenant_id,
                    original_filename,
                    content_type,
                    sha256,
                    size_bytes,
                    storage_path,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'review_pending')
                RETURNING *
                """,
                (
                    document_id,
                    tenant_id,
                    stored.original_filename,
                    stored.content_type,
                    stored.sha256,
                    stored.size_bytes,
                    str(stored.storage_path),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
        return row_to_document(row)


def get_document(document_id: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM documents
                WHERE id = %s
                LIMIT 1
                """,
                (document_id,),
            )
            row = cursor.fetchone()
            return row_to_document(row) if row else None


def update_document_status(document_id: str, status: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE documents
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, document_id),
            )
        connection.commit()


def create_extraction(
    document_id: str,
    tenant_id: str,
    provider: str,
    status: str,
    fields: dict,
    warnings: list[str],
    confidence: float,
) -> dict:
    extraction_id = str(uuid4())
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO document_extractions (
                    id,
                    document_id,
                    tenant_id,
                    provider,
                    status,
                    fields,
                    warnings,
                    confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    extraction_id,
                    document_id,
                    tenant_id,
                    provider,
                    status,
                    Jsonb(fields),
                    Jsonb(warnings),
                    confidence,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
        return {
            "id": row["id"],
            "document_id": row["document_id"],
            "tenant_id": row["tenant_id"],
            "provider": row["provider"],
            "status": row["status"],
            "fields": row["fields"],
            "warnings": row["warnings"],
            "confidence": float(row["confidence"]),
            "created_at": row["created_at"].isoformat(),
        }


def create_audit_event(
    tenant_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
    actor_type: str = "system",
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    id,
                    tenant_id,
                    actor_type,
                    event_type,
                    entity_type,
                    entity_id,
                    details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid4()),
                    tenant_id,
                    actor_type,
                    event_type,
                    entity_type,
                    entity_id,
                    Jsonb(details or {}),
                ),
            )
        connection.commit()
