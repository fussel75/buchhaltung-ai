from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.services.storage import StoredDocument, rename_stored_document


def _connect() -> psycopg.Connection:
    settings = get_settings()
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def init_database() -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                create table if not exists documents (
                    id uuid primary key,
                    tenant_id text not null,
                    original_filename text not null,
                    content_type text not null,
                    sha256 text not null,
                    size_bytes integer not null,
                    storage_path text not null,
                    status text not null,
                    duplicate_of uuid references documents(id),
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (tenant_id, sha256)
                )
                """
            )
            cursor.execute("alter table documents add column if not exists normalized_filename text")
            cursor.execute(
                """
                create index if not exists documents_tenant_created_idx
                    on documents (tenant_id, created_at desc)
                """
            )
            cursor.execute(
                """
                create table if not exists document_extractions (
                    id uuid primary key,
                    document_id uuid not null references documents(id) on delete cascade,
                    tenant_id text not null,
                    supplier_name text,
                    invoice_number text,
                    invoice_date date,
                    service_period text,
                    net_amount numeric(12, 2),
                    tax_amount numeric(12, 2),
                    gross_amount numeric(12, 2),
                    currency text not null default 'EUR',
                    confidence numeric(5, 4) not null,
                    warnings jsonb not null default '[]'::jsonb,
                    raw_result jsonb not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (document_id)
                )
                """
            )
            cursor.execute(
                """
                create table if not exists audit_events (
                    id uuid primary key,
                    tenant_id text not null,
                    actor text not null,
                    event_type text not null,
                    document_id uuid references documents(id) on delete set null,
                    details jsonb not null default '{}'::jsonb,
                    created_at timestamptz not null
                )
                """
            )
            cursor.execute(
                """
                create index if not exists audit_events_tenant_created_idx
                    on audit_events (tenant_id, created_at desc)
                """
            )
            cursor.execute(
                """
                create table if not exists users (
                    id uuid primary key,
                    email text not null unique,
                    password_hash text not null,
                    display_name text not null,
                    role text not null check (role in ('admin', 'user')),
                    is_active boolean not null default true,
                    created_at timestamptz not null,
                    last_login_at timestamptz
                )
                """
            )
            cursor.execute(
                """
                create unique index if not exists users_email_idx
                    on users (lower(email))
                """
            )
            cursor.execute(
                """
                create table if not exists sessions (
                    id text primary key,
                    user_id uuid not null references users(id) on delete cascade,
                    expires_at timestamptz not null,
                    created_at timestamptz not null
                )
                """
            )
            cursor.execute(
                """
                create index if not exists sessions_expires_at_idx
                    on sessions (expires_at)
                """
            )


def create_document_record(tenant_id: str, stored: StoredDocument) -> tuple[dict[str, Any], bool]:
    now = datetime.now(UTC)
    document_id = uuid4()
    audit_event_type = "document.uploaded"
    audit_document_id: UUID | None = None

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into documents (
                    id,
                    tenant_id,
                    original_filename,
                    content_type,
                    normalized_filename,
                    sha256,
                    size_bytes,
                    storage_path,
                    status,
                    created_at,
                    updated_at
                )
                values (%s, %s, %s, %s, null, %s, %s, %s, 'review_pending', %s, %s)
                on conflict (tenant_id, sha256) do nothing
                returning *
                """,
                (
                    document_id,
                    tenant_id,
                    stored.original_filename,
                    stored.content_type,
                    stored.sha256,
                    stored.size_bytes,
                    str(stored.storage_path),
                    now,
                    now,
                ),
            )
            inserted = cursor.fetchone()
            if inserted:
                document = _serialize_document(inserted)
                audit_document_id = inserted["id"]
                is_duplicate = False
            else:
                cursor.execute(
                    """
                    select *
                    from documents
                    where tenant_id = %s and sha256 = %s
                    """,
                    (tenant_id, stored.sha256),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("Duplicate document lookup failed after insert conflict.")

                document = _serialize_document(existing)
                audit_document_id = existing["id"]
                audit_event_type = "document.duplicate_detected"
                is_duplicate = True

    insert_audit_event(
        tenant_id=tenant_id,
        event_type=audit_event_type,
        document_id=audit_document_id,
        details={"sha256": stored.sha256, "original_filename": stored.original_filename},
    )
    return document, is_duplicate


def list_documents(tenant_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    d.*,
                    to_jsonb(e.*) as extraction
                from documents d
                left join document_extractions e on e.document_id = d.id
                where d.tenant_id = %s
                order by d.created_at desc
                limit 100
                """,
                (tenant_id,),
            )
            return [_serialize_document(row) for row in cursor.fetchall()]


def get_document(document_id: UUID) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    d.*,
                    to_jsonb(e.*) as extraction
                from documents d
                left join document_extractions e on e.document_id = d.id
                where d.id = %s
                """,
                (document_id,),
            )
            row = cursor.fetchone()
            return _serialize_document(row) if row else None


def delete_document(document_id: UUID) -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None:
        return None

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.deleted",
        document_id=document_id,
        details={
            "original_filename": document["original_filename"],
            "sha256": document["sha256"],
            "storage_path": document["storage_path"],
        },
    )

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("delete from documents where id = %s", (document_id,))

    return document


def save_document_extraction(
    document_id: UUID,
    tenant_id: str,
    extraction: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    extraction_id = uuid4()
    warnings = extraction.get("warnings", [])
    normalized_filename = extraction.get("normalized_filename")
    normalized_storage_path = None
    if normalized_filename:
        current_document = get_document(document_id)
        if current_document:
            normalized_storage_path = rename_stored_document(
                storage_path=current_document["storage_path"],
                normalized_filename=normalized_filename,
            )

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into document_extractions (
                    id,
                    document_id,
                    tenant_id,
                    supplier_name,
                    invoice_number,
                    invoice_date,
                    service_period,
                    net_amount,
                    tax_amount,
                    gross_amount,
                    currency,
                    confidence,
                    warnings,
                    raw_result,
                    created_at,
                    updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (document_id) do update set
                    supplier_name = excluded.supplier_name,
                    invoice_number = excluded.invoice_number,
                    invoice_date = excluded.invoice_date,
                    service_period = excluded.service_period,
                    net_amount = excluded.net_amount,
                    tax_amount = excluded.tax_amount,
                    gross_amount = excluded.gross_amount,
                    currency = excluded.currency,
                    confidence = excluded.confidence,
                    warnings = excluded.warnings,
                    raw_result = excluded.raw_result,
                    updated_at = excluded.updated_at
                returning *
                """,
                (
                    extraction_id,
                    document_id,
                    tenant_id,
                    extraction.get("supplier_name"),
                    extraction.get("invoice_number"),
                    extraction.get("invoice_date"),
                    extraction.get("service_period"),
                    extraction.get("net_amount"),
                    extraction.get("tax_amount"),
                    extraction.get("gross_amount"),
                    extraction.get("currency", "EUR"),
                    extraction.get("confidence", Decimal("0.50")),
                    Jsonb(warnings),
                    Jsonb(_json_safe_extraction(extraction)),
                    now,
                    now,
                ),
            )
            saved = cursor.fetchone()
            cursor.execute(
                """
                update documents
                set
                    status = 'extracted',
                    normalized_filename = coalesce(%s, normalized_filename),
                    storage_path = coalesce(%s, storage_path),
                    updated_at = %s
                where id = %s
                returning *
                """,
                (
                    normalized_filename,
                    str(normalized_storage_path) if normalized_storage_path else None,
                    now,
                    document_id,
                ),
            )
            document = cursor.fetchone()

    insert_audit_event(
        tenant_id=tenant_id,
        event_type="document.extraction_completed",
        document_id=document_id,
        details={"confidence": str(extraction.get("confidence", "")), "warnings": warnings},
    )
    serialized = _serialize_document(document)
    serialized["extraction"] = _serialize_extraction(saved)
    return serialized


def insert_audit_event(
    tenant_id: str,
    event_type: str,
    document_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    actor: str = "system",
) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into audit_events (id, tenant_id, actor, event_type, document_id, details, created_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    tenant_id,
                    actor,
                    event_type,
                    document_id,
                    Jsonb(details or {}),
                    datetime.now(UTC),
                ),
            )


def count_users() -> int:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select count(*) as count from users")
            return int(cursor.fetchone()["count"])


def create_user(
    email: str,
    password_hash: str,
    display_name: str,
    role: str = "user",
    is_active: bool = True,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into users (
                    id,
                    email,
                    password_hash,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    last_login_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, null)
                returning *
                """,
                (
                    uuid4(),
                    email.strip().lower(),
                    password_hash,
                    display_name.strip() or email.strip().lower(),
                    role,
                    is_active,
                    now,
                ),
            )
            return _serialize_user(cursor.fetchone())


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from users
                where lower(email) = lower(%s)
                limit 1
                """,
                (email.strip(),),
            )
            row = cursor.fetchone()
            return _serialize_user(row, include_password_hash=True) if row else None


def get_user_by_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select u.*
                from sessions s
                join users u on u.id = s.user_id
                where s.id = %s
                    and s.expires_at > %s
                    and u.is_active = true
                limit 1
                """,
                (session_id, datetime.now(UTC)),
            )
            row = cursor.fetchone()
            return _serialize_user(row) if row else None


def create_session(session_id: str, user_id: UUID, expires_at: datetime) -> None:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into sessions (id, user_id, expires_at, created_at)
                values (%s, %s, %s, %s)
                """,
                (session_id, user_id, expires_at, now),
            )
            cursor.execute(
                """
                update users
                set last_login_at = %s
                where id = %s
                """,
                (now, user_id),
            )


def renew_session(session_id: str, expires_at: datetime) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update sessions
                set expires_at = %s
                where id = %s
                """,
                (expires_at, session_id),
            )


def delete_session(session_id: str) -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("delete from sessions where id = %s", (session_id,))


def delete_expired_sessions() -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("delete from sessions where expires_at <= %s", (datetime.now(UTC),))


def _serialize_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "original_filename": row["original_filename"],
        "normalized_filename": row.get("normalized_filename"),
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "storage_path": row["storage_path"],
        "status": row["status"],
        "duplicate_of": str(row["duplicate_of"]) if row["duplicate_of"] else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "extraction": _serialize_extraction(row["extraction"]) if row.get("extraction") else None,
    }


def _serialize_extraction(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "tenant_id": row["tenant_id"],
        "supplier_name": row["supplier_name"],
        "invoice_number": row["invoice_number"],
        "invoice_date": _serialize_date(row["invoice_date"]),
        "service_period": row["service_period"],
        "net_amount": str(row["net_amount"]) if row["net_amount"] is not None else None,
        "tax_amount": str(row["tax_amount"]) if row["tax_amount"] is not None else None,
        "gross_amount": str(row["gross_amount"]) if row["gross_amount"] is not None else None,
        "currency": row["currency"],
        "confidence": float(row["confidence"]),
        "warnings": row["warnings"],
        "raw_result": row.get("raw_result") or {},
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_user(row: dict[str, Any], include_password_hash: bool = False) -> dict[str, Any]:
    user = {
        "id": str(row["id"]),
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "last_login_at": _serialize_date(row["last_login_at"]),
    }
    if include_password_hash:
        user["password_hash"] = row["password_hash"]
    return user


def _serialize_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in extraction.items()
    }
