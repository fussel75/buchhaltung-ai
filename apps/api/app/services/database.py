from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from re import search as re_search, sub
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.services.cost_categories import COST_CATEGORY_LABELS, VALID_COST_CATEGORIES, split_cost_category_values
from app.services.storage import StoredDocument, rename_stored_document

VALID_ACCOUNTING_FRAMEWORKS = {"SKR03", "SKR04"}
BULK_JOB_ACTIONS = {"extract", "reextract", "prepare_review"}
BULK_JOB_ACTIVE_STATUSES = {"queued", "running"}


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
            cursor.execute("alter table documents add column if not exists processing_job_id uuid")
            cursor.execute("alter table documents add column if not exists processing_started_at timestamptz")
            cursor.execute(
                """
                create index if not exists documents_tenant_created_idx
                    on documents (tenant_id, created_at desc)
                """
            )
            cursor.execute(
                """
                create index if not exists documents_processing_job_idx
                    on documents (processing_job_id)
                    where processing_job_id is not null
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
                create table if not exists document_booking_suggestions (
                    id uuid primary key,
                    document_id uuid not null references documents(id) on delete cascade,
                    tenant_id text not null,
                    line_no integer not null,
                    booking_type text not null,
                    cost_category text,
                    assignment_code text,
                    assignment_project_number text,
                    assignment_kind text,
                    description text,
                    net_amount numeric(12, 2),
                    tax_amount numeric(12, 2),
                    gross_amount numeric(12, 2),
                    currency text not null default 'EUR',
                    status text not null default 'suggested',
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (document_id, line_no)
                )
                """
            )
            cursor.execute(
                """
                create index if not exists document_booking_suggestions_document_idx
                    on document_booking_suggestions (document_id, line_no)
                """
            )
            cursor.execute(
                """
                create table if not exists document_payment_decisions (
                    id uuid primary key,
                    document_id uuid not null references documents(id) on delete cascade,
                    tenant_id text not null,
                    payment_type text not null,
                    label text not null,
                    due_date date,
                    amount numeric(12, 2),
                    discount_base numeric(12, 2),
                    discount_percent numeric(5, 2),
                    discount_amount numeric(12, 2),
                    currency text not null default 'EUR',
                    status text not null default 'selected',
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (document_id)
                )
                """
            )
            cursor.execute(
                """
                create index if not exists document_payment_decisions_document_idx
                    on document_payment_decisions (document_id)
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
                    allowed_tenant_ids jsonb not null default '[]'::jsonb,
                    is_active boolean not null default true,
                    created_at timestamptz not null,
                    last_login_at timestamptz
                )
                """
            )
            cursor.execute("alter table users add column if not exists allowed_tenant_ids jsonb not null default '[]'::jsonb")
            cursor.execute("update users set allowed_tenant_ids = '[\"*\"]'::jsonb where role = 'admin'")
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
            cursor.execute(
                """
                create table if not exists tenant_profiles (
                    tenant_id text primary key,
                    display_name text not null,
                    industry text not null,
                    assignment_label_singular text not null,
                    assignment_label_plural text not null,
                    assignment_code_label text not null,
                    assignment_code_prefix text,
                    default_assignment_kind text not null,
                    allow_multiple_assignments boolean not null default true,
                    accounting_framework text not null default 'SKR03',
                    default_credit_account text,
                    default_tax_key text,
                    default_tax_rate numeric(5, 2),
                    default_discount_account text,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            cursor.execute("alter table tenant_profiles add column if not exists accounting_framework text not null default 'SKR03'")
            cursor.execute("alter table tenant_profiles add column if not exists default_credit_account text")
            cursor.execute("alter table tenant_profiles add column if not exists default_tax_key text")
            cursor.execute("alter table tenant_profiles add column if not exists default_tax_rate numeric(5, 2)")
            cursor.execute("alter table tenant_profiles add column if not exists default_discount_account text")
            cursor.execute(
                """
                create table if not exists tenant_assignment_units (
                    id uuid primary key,
                    tenant_id text not null,
                    code text not null,
                    label text not null,
                    kind text not null,
                    project_number text,
                    order_number text,
                    customer_number text,
                    description text,
                    client_name text,
                    source_status text,
                    address_line text,
                    postal_code text,
                    city text,
                    external_id text,
                    revenue_relevant boolean not null default false,
                    aliases jsonb not null default '[]'::jsonb,
                    is_active boolean not null default true,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (tenant_id, code)
                )
                """
            )
            cursor.execute("alter table tenant_assignment_units add column if not exists project_number text")
            cursor.execute("alter table tenant_assignment_units add column if not exists order_number text")
            cursor.execute("alter table tenant_assignment_units add column if not exists customer_number text")
            cursor.execute("alter table tenant_assignment_units add column if not exists description text")
            cursor.execute("alter table tenant_assignment_units add column if not exists client_name text")
            cursor.execute("alter table tenant_assignment_units add column if not exists source_status text")
            cursor.execute("alter table tenant_assignment_units add column if not exists address_line text")
            cursor.execute("alter table tenant_assignment_units add column if not exists postal_code text")
            cursor.execute("alter table tenant_assignment_units add column if not exists city text")
            cursor.execute("alter table tenant_assignment_units add column if not exists external_id text")
            cursor.execute(
                """
                create index if not exists tenant_assignment_units_tenant_idx
                    on tenant_assignment_units (tenant_id, is_active, kind)
                """
            )
            cursor.execute(
                """
                create table if not exists tenant_supplier_rules (
                    id uuid primary key,
                    tenant_id text not null,
                    match_text text not null,
                    supplier_name text not null,
                    customer_number text,
                    default_cost_category text,
                    default_assignment_code text,
                    is_active boolean not null default true,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            cursor.execute(
                """
                create index if not exists tenant_supplier_rules_tenant_idx
                    on tenant_supplier_rules (tenant_id, is_active)
                """
            )
            cursor.execute(
                """
                create table if not exists tenant_accounting_rules (
                    id uuid primary key,
                    tenant_id text not null,
                    name text not null,
                    supplier_match_text text,
                    cost_category text,
                    debit_account text not null,
                    credit_account text not null,
                    tax_key text,
                    tax_rate numeric(5, 2),
                    discount_account text,
                    is_active boolean not null default true,
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            cursor.execute(
                """
                create index if not exists tenant_accounting_rules_tenant_idx
                    on tenant_accounting_rules (tenant_id, is_active, cost_category)
                """
            )
            cursor.execute("alter table document_booking_suggestions add column if not exists assignment_project_number text")
            cursor.execute(
                """
                create table if not exists tenant_bwa_imports (
                    id uuid primary key,
                    tenant_id text not null,
                    original_filename text not null,
                    content_type text not null,
                    sha256 text not null,
                    size_bytes integer not null,
                    storage_path text not null,
                    period text,
                    account_hints jsonb not null default '[]'::jsonb,
                    warnings jsonb not null default '[]'::jsonb,
                    text_excerpt text,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (tenant_id, sha256)
                )
                """
            )
            cursor.execute(
                """
                create index if not exists tenant_bwa_imports_tenant_created_idx
                    on tenant_bwa_imports (tenant_id, created_at desc)
                """
            )
            cursor.execute(
                """
                create table if not exists document_bulk_jobs (
                    id uuid primary key,
                    tenant_id text not null,
                    action text not null,
                    status text not null,
                    requested_total integer not null default 0,
                    processed_count integer not null default 0,
                    succeeded_count integer not null default 0,
                    failed_count integer not null default 0,
                    error text,
                    created_by text not null,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    started_at timestamptz,
                    finished_at timestamptz,
                    check (action in ('extract', 'reextract', 'prepare_review')),
                    check (status in ('queued', 'running', 'completed', 'failed'))
                )
                """
            )
            cursor.execute(
                """
                do $$
                declare
                    action_constraint record;
                begin
                    for action_constraint in
                        select conname
                        from pg_constraint
                        where conrelid = 'document_bulk_jobs'::regclass
                            and contype = 'c'
                            and pg_get_constraintdef(oid) like '%action%'
                    loop
                        execute format('alter table document_bulk_jobs drop constraint %I', action_constraint.conname);
                    end loop;

                    alter table document_bulk_jobs
                        add constraint document_bulk_jobs_action_check
                        check (action in ('extract', 'reextract', 'prepare_review'));
                end $$;
                """
            )
            cursor.execute(
                """
                create table if not exists document_bulk_job_items (
                    id uuid primary key,
                    job_id uuid not null references document_bulk_jobs(id) on delete cascade,
                    document_id uuid not null references documents(id) on delete cascade,
                    status text not null,
                    error text,
                    created_at timestamptz not null,
                    updated_at timestamptz not null,
                    unique (job_id, document_id),
                    check (status in ('queued', 'running', 'succeeded', 'failed', 'skipped'))
                )
                """
            )
            cursor.execute(
                """
                create unique index if not exists document_bulk_jobs_active_tenant_action_idx
                    on document_bulk_jobs (tenant_id, action)
                    where status in ('queued', 'running')
                """
            )
            cursor.execute(
                """
                create index if not exists document_bulk_job_items_job_idx
                    on document_bulk_job_items (job_id, status)
                """
            )
    seed_demo_masterdata()


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


def list_documents(tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 1000))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    d.*,
                    to_jsonb(e.*) as extraction,
                    coalesce(
                        (
                            select jsonb_agg(to_jsonb(s.*) order by s.line_no)
                            from document_booking_suggestions s
                            where s.document_id = d.id
                        ),
                        '[]'::jsonb
                    ) as booking_suggestions,
                    to_jsonb(pd.*) as payment_decision
                from documents d
                left join document_extractions e on e.document_id = d.id
                left join document_payment_decisions pd on pd.document_id = d.id
                where d.tenant_id = %s
                order by d.created_at desc
                limit %s
                """,
                (tenant_id, capped_limit),
            )
            return [_serialize_document(row) for row in cursor.fetchall()]


def list_document_ids_for_bulk_action(tenant_id: str, action: str, limit: int = 500) -> list[UUID]:
    if action not in BULK_JOB_ACTIONS:
        raise ValueError("unsupported bulk action")
    capped_limit = max(1, min(limit, 1000))
    if action == "extract":
        where_clause = "d.status = 'review_pending' and e.document_id is null"
    elif action == "reextract":
        where_clause = "d.status in ('extracted', 'review_ready') and e.document_id is not null"
    else:
        where_clause = "d.status = 'extracted' and e.document_id is not null and not exists (select 1 from document_booking_suggestions s where s.document_id = d.id)"

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                select d.id
                from documents d
                left join document_extractions e on e.document_id = d.id
                where d.tenant_id = %s
                    and {where_clause}
                    and d.processing_job_id is null
                order by d.created_at desc
                limit %s
                """,
                (tenant_id, capped_limit),
            )
            return [row["id"] for row in cursor.fetchall()]


def list_documents_for_month(tenant_id: str, year: int, month: int) -> list[dict[str, Any]]:
    start_date = date(year, month, 1)
    end_date = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    d.*,
                    to_jsonb(e.*) as extraction,
                    coalesce(
                        (
                            select jsonb_agg(to_jsonb(s.*) order by s.line_no)
                            from document_booking_suggestions s
                            where s.document_id = d.id
                        ),
                        '[]'::jsonb
                    ) as booking_suggestions,
                    to_jsonb(pd.*) as payment_decision
                from documents d
                left join document_extractions e on e.document_id = d.id
                left join document_payment_decisions pd on pd.document_id = d.id
                where d.tenant_id = %s
                    and coalesce(e.invoice_date, d.created_at::date) >= %s
                    and coalesce(e.invoice_date, d.created_at::date) < %s
                order by coalesce(e.invoice_date, d.created_at::date) desc, d.created_at desc
                limit 500
                """,
                (tenant_id, start_date, end_date),
            )
            return [_serialize_document(row) for row in cursor.fetchall()]


def get_document(document_id: UUID) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    d.*,
                    to_jsonb(e.*) as extraction,
                    coalesce(
                        (
                            select jsonb_agg(to_jsonb(s.*) order by s.line_no)
                            from document_booking_suggestions s
                            where s.document_id = d.id
                        ),
                        '[]'::jsonb
                    ) as booking_suggestions,
                    to_jsonb(pd.*) as payment_decision
                from documents d
                left join document_extractions e on e.document_id = d.id
                left join document_payment_decisions pd on pd.document_id = d.id
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


class BulkJobConflictError(ValueError):
    pass


def create_document_bulk_job(
    tenant_id: str,
    action: str,
    document_ids: list[UUID],
    actor: str = "system",
) -> dict[str, Any]:
    if action not in BULK_JOB_ACTIONS:
        raise ValueError("unsupported bulk action")

    unique_document_ids = list(dict.fromkeys(document_ids))
    if not unique_document_ids:
        raise ValueError("bulk job requires documents")

    now = datetime.now(UTC)
    job_id = uuid4()
    with _connect() as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into document_bulk_jobs (
                        id, tenant_id, action, status, requested_total, processed_count,
                        succeeded_count, failed_count, error, created_by,
                        created_at, updated_at, started_at, finished_at
                    )
                    values (%s, %s, %s, 'queued', %s, 0, 0, 0, null, %s, %s, %s, null, null)
                    returning *
                    """,
                    (job_id, tenant_id, action, len(unique_document_ids), actor, now, now),
                )
                job = cursor.fetchone()
                for document_id in unique_document_ids:
                    cursor.execute(
                        """
                        insert into document_bulk_job_items (
                            id, job_id, document_id, status, error, created_at, updated_at
                        )
                        values (%s, %s, %s, 'queued', null, %s, %s)
                        """,
                        (uuid4(), job_id, document_id, now, now),
                    )
        except psycopg.errors.UniqueViolation as error:
            connection.rollback()
            raise BulkJobConflictError("active bulk job already exists") from error

    insert_audit_event(
        tenant_id=tenant_id,
        event_type=f"document.bulk_{action}_queued",
        actor=actor,
        details={"job_id": str(job_id), "document_count": len(unique_document_ids)},
    )
    serialized = _serialize_bulk_job(job)
    serialized["items"] = _list_document_bulk_job_items(job_id)
    return serialized


def get_document_bulk_job(job_id: UUID) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select * from document_bulk_jobs where id = %s", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None

    job = _serialize_bulk_job(row)
    job["items"] = _list_document_bulk_job_items(job_id)
    return job


def list_document_bulk_jobs(tenant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 50))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from document_bulk_jobs
                where tenant_id = %s
                order by created_at desc, id desc
                limit %s
                """,
                (tenant_id, capped_limit),
            )
            rows = cursor.fetchall()

    return [_serialize_bulk_job(row) for row in rows]


def mark_document_bulk_job_running(job_id: UUID) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_bulk_jobs
                set status = 'running', started_at = coalesce(started_at, %s), updated_at = %s
                where id = %s and status = 'queued'
                returning *
                """,
                (now, now, job_id),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute("select * from document_bulk_jobs where id = %s", (job_id,))
                row = cursor.fetchone()
    if not row:
        return None
    job = _serialize_bulk_job(row)
    job["items"] = _list_document_bulk_job_items(job_id)
    return job


def mark_document_bulk_job_item(
    job_id: UUID,
    document_id: UUID,
    status: str,
    error: str | None = None,
) -> None:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_bulk_job_items
                set status = %s, error = %s, updated_at = %s
                where job_id = %s and document_id = %s
                """,
                (status, error, now, job_id, document_id),
            )
            cursor.execute(
                """
                update document_bulk_jobs
                set
                    processed_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status in ('succeeded', 'failed', 'skipped')
                    ),
                    succeeded_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status = 'succeeded'
                    ),
                    failed_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status in ('failed', 'skipped')
                    ),
                    updated_at = %s
                where id = %s
                """,
                (job_id, job_id, job_id, now, job_id),
            )


def claim_document_for_bulk_job(document_id: UUID, job_id: UUID, expected_status: str | list[str]) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    expected_statuses = [expected_status] if isinstance(expected_status, str) else expected_status
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update documents
                set processing_job_id = %s, processing_started_at = %s, updated_at = %s
                where id = %s and status = any(%s) and processing_job_id is null
                returning *
                """,
                (job_id, now, now, document_id, expected_statuses),
            )
            row = cursor.fetchone()
    return _serialize_document(row) if row else None


def release_document_bulk_claim(document_id: UUID, job_id: UUID) -> None:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update documents
                set processing_job_id = null, processing_started_at = null, updated_at = %s
                where id = %s and processing_job_id = %s
                """,
                (now, document_id, job_id),
            )


def finish_document_bulk_job(job_id: UUID, status: str = "completed", error: str | None = None) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_bulk_jobs
                set
                    status = %s,
                    processed_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status in ('succeeded', 'failed', 'skipped')
                    ),
                    succeeded_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status = 'succeeded'
                    ),
                    failed_count = (
                        select count(*) from document_bulk_job_items
                        where job_id = %s and status in ('failed', 'skipped')
                    ),
                    error = %s,
                    updated_at = %s,
                    finished_at = %s
                where id = %s
                returning *
                """,
                (status, job_id, job_id, job_id, error, now, now, job_id),
            )
            row = cursor.fetchone()
    if not row:
        return None
    job = _serialize_bulk_job(row)
    job["items"] = _list_document_bulk_job_items(job_id)
    return job


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
            cursor.execute("delete from document_booking_suggestions where document_id = %s", (document_id,))
            cursor.execute("delete from document_payment_decisions where document_id = %s", (document_id,))
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


def update_document_extraction(
    document_id: UUID,
    values: dict[str, Any],
    actor: str = "system",
) -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None or not document.get("extraction"):
        return None
    if document.get("status") == "review_approved":
        raise ValueError("approved document cannot be edited")

    current = dict(document["extraction"])
    raw_result = dict(current.get("raw_result") or {})
    top_level_fields = {
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "service_period",
        "net_amount",
        "tax_amount",
        "gross_amount",
        "currency",
    }
    raw_fields = {
        "customer_number",
        "document_type",
        "cost_category",
        "assignment_code",
        "assignment_kind",
        "project_number",
        "due_date",
        "discount_due_date",
        "discount_base",
        "discount_amount",
        "discounted_payable_amount",
        "item_summary",
    }

    for field_name in top_level_fields:
        if field_name in values:
            current[field_name] = values[field_name]
    for field_name in raw_fields:
        if field_name in values:
            raw_result[field_name] = values[field_name]
    if "assignment_code" in values:
        raw_result.pop("project_code", None)
        raw_result["assignment_type"] = _manual_assignment_type(raw_result, values["assignment_code"])
    for amount_field in ("net_amount", "tax_amount", "gross_amount"):
        if amount_field in values:
            raw_result[amount_field] = values[amount_field]
    if any(
        field_name in values
        for field_name in (
            "document_type",
            "gross_amount",
            "currency",
            "due_date",
            "discount_due_date",
            "discount_base",
            "discount_amount",
            "discounted_payable_amount",
        )
    ):
        raw_result.pop("payment_terms", None)

    current["raw_result"] = raw_result
    current["confidence"] = Decimal("1.00")
    current["warnings"] = []
    normalized_filename = _manual_normalized_invoice_filename(document, current)
    normalized_storage_path = None
    if normalized_filename and document.get("storage_path"):
        normalized_storage_path = rename_stored_document(
            storage_path=document["storage_path"],
            normalized_filename=normalized_filename,
        )
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_extractions
                set
                    supplier_name = %s,
                    invoice_number = %s,
                    invoice_date = %s,
                    service_period = %s,
                    net_amount = %s,
                    tax_amount = %s,
                    gross_amount = %s,
                    currency = %s,
                    confidence = %s,
                    warnings = %s,
                    raw_result = %s,
                    updated_at = %s
                where document_id = %s
                returning *
                """,
                (
                    current.get("supplier_name"),
                    current.get("invoice_number"),
                    current.get("invoice_date"),
                    current.get("service_period"),
                    current.get("net_amount"),
                    current.get("tax_amount"),
                    current.get("gross_amount"),
                    current.get("currency") or "EUR",
                    current["confidence"],
                    Jsonb(current["warnings"]),
                    Jsonb(_json_safe_value(raw_result)),
                    now,
                    document_id,
                ),
            )
            cursor.fetchone()
            cursor.execute("delete from document_booking_suggestions where document_id = %s", (document_id,))
            cursor.execute("delete from document_payment_decisions where document_id = %s", (document_id,))
            cursor.execute(
                """
                update documents
                set
                    status = 'extracted',
                    normalized_filename = %s,
                    storage_path = coalesce(%s, storage_path),
                    updated_at = %s
                where id = %s
                """,
                (
                    normalized_filename,
                    normalized_storage_path.as_posix() if normalized_storage_path else None,
                    now,
                    document_id,
                ),
            )

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.extraction_updated",
        document_id=document_id,
        actor=actor,
        details={
            "fields": sorted(values.keys()),
            "old_normalized_filename": document.get("normalized_filename"),
            "new_normalized_filename": normalized_filename,
            "old_storage_path": document.get("storage_path"),
            "new_storage_path": normalized_storage_path.as_posix() if normalized_storage_path else document.get("storage_path"),
        },
    )
    return get_document(document_id)


def _manual_assignment_type(raw_result: dict[str, Any], assignment_code: str | None) -> str:
    if assignment_code:
        return "assigned"
    if len(raw_result.get("allocation_lines") or []) > 1:
        return "assignment_split"
    if raw_result.get("delivery_address") or raw_result.get("assignment_type") == "assignment_unresolved":
        return "assignment_unresolved"
    return "general_cost"


def _manual_normalized_invoice_filename(document: dict[str, Any], extraction: dict[str, Any]) -> str:
    raw_result = extraction.get("raw_result") or {}
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    assignment_code = raw_result.get("assignment_code")
    assignment = get_assignment_unit_by_code(document["tenant_id"], assignment_code)
    assignment_type = raw_result.get("assignment_type")
    if not assignment_type:
        assignment_type = "assigned" if assignment else "general_cost"
    supplier_name = extraction.get("supplier_name") or "Unbekannter Lieferant"
    item_summary = raw_result.get("item_summary") or "Eingangsrechnung"
    return _normalized_invoice_filename(
        invoice_number=extraction.get("invoice_number"),
        assignment=assignment,
        assignment_code=assignment_code,
        assignment_type=assignment_type,
        tenant_profile=tenant_profile,
        supplier_name=supplier_name,
        product_name=item_summary,
        invoice_date=_serialize_date(extraction.get("invoice_date")),
        suffix=_document_suffix(document),
    )


def _normalized_invoice_filename(
    invoice_number: str | None,
    assignment: dict[str, Any] | None,
    assignment_code: str | None,
    assignment_type: str,
    tenant_profile: dict[str, Any],
    supplier_name: str,
    product_name: str,
    invoice_date: str | None,
    suffix: str,
) -> str:
    parts = [
        f"ERg {invoice_number or 'ohne Nummer'}",
        _filename_assignment_label(assignment, assignment_code, assignment_type, tenant_profile),
        supplier_name,
        product_name,
        invoice_date or "ohne Datum",
    ]
    return ", ".join(_filename_part(part) for part in parts) + suffix


def _document_suffix(document: dict[str, Any]) -> str:
    original_suffix = Path(str(document.get("original_filename") or "")).suffix
    storage_suffix = Path(str(document.get("storage_path") or "")).suffix
    return (original_suffix or storage_suffix or ".pdf").lower()


def _filename_part(value: str) -> str:
    cleaned = sub(r'[<>:"/\\|?*]+', " ", value)
    cleaned = sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "-"


def _filename_assignment_label(
    assignment: dict[str, Any] | None,
    assignment_code: str | None,
    assignment_type: str,
    tenant_profile: dict[str, Any],
) -> str:
    if assignment:
        code = _display_assignment_code(assignment)
        prefix = tenant_profile.get("assignment_code_prefix")
        if prefix:
            return f"{prefix} {code}"
        return f"{tenant_profile['assignment_label_singular']} {code}"
    if assignment_code:
        prefix = tenant_profile.get("assignment_code_prefix")
        if prefix:
            return f"{prefix} {assignment_code}"
        return f"{tenant_profile['assignment_label_singular']} {assignment_code}"
    if assignment_type == "assignment_split":
        return f"{tenant_profile['assignment_label_plural']} aufgeteilt"
    if assignment_type == "assignment_unresolved":
        return f"{tenant_profile['assignment_label_singular']} ungeklärt"
    return "Allgemeine Kosten"


def _display_assignment_code(assignment: dict[str, Any]) -> str:
    code = assignment.get("code")
    label = assignment.get("label")
    if code and _looks_like_project_number(code) and label and not _looks_like_project_number(label):
        return label
    return code or label or "-"


def _looks_like_project_number(value: str | None) -> bool:
    return bool(value and re_search(r"^\d{2,4}-\d{3,}$", value.strip()))


def approve_document_review(document_id: UUID, actor: str = "system") -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None or not document.get("extraction"):
        return None

    if document.get("status") != "review_ready":
        raise ReviewApprovalError(
            ["Finale Freigabe ist nur im Status Vorschlag möglich."],
            details=[
                {
                    "code": "invalid_status",
                    "message": "Finale Freigabe ist nur im Status Vorschlag möglich.",
                    "status": document.get("status"),
                }
            ],
        )

    approval_details = validate_document_review_details(document)
    approval_errors = [detail["message"] for detail in approval_details]
    if approval_errors:
        raise ReviewApprovalError(approval_errors, details=approval_details)

    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_booking_suggestions
                set status = 'approved', updated_at = %s
                where document_id = %s
                """,
                (now, document_id),
            )
            cursor.execute(
                """
                update documents
                set status = 'review_approved', updated_at = %s
                where id = %s
                """,
                (now, document_id),
            )

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.review_approved",
        document_id=document_id,
        actor=actor,
        details={"suggestion_count": len(document.get("booking_suggestions") or [])},
    )
    return get_document(document_id)


class ReviewApprovalError(ValueError):
    def __init__(self, errors: list[str], details: list[dict[str, Any]] | None = None):
        super().__init__("review approval blocked")
        self.errors = errors
        self.details = details or [{"code": "review_validation", "message": error} for error in errors]


def _cost_category_label(value: str | None) -> str:
    if not value:
        return "-"
    return COST_CATEGORY_LABELS.get(value, value)


def _accounting_rule_context(supplier_name: str | None, cost_category: str | None) -> str:
    return f"Kostenart {_cost_category_label(cost_category)} / Lieferant {supplier_name or '-'}"


def validate_document_review(document: dict[str, Any]) -> list[str]:
    return [detail["message"] for detail in validate_document_review_details(document)]


def validate_document_review_export_details(document: dict[str, Any]) -> list[dict[str, Any]]:
    export_document = {**document, "status": "review_approved"}
    rows = build_booking_export_rows([export_document])
    details: list[dict[str, Any]] = []
    for issue in validate_booking_export_rows(rows):
        errors = issue.get("errors") or []
        line_no = issue.get("line_no")
        line_label = f"Zeile {line_no}" if line_no else f"Exportzeile {issue.get('row_index')}"
        row_type = issue.get("row_type")
        row_type_label = _booking_export_row_type_label(row_type)
        details.append(
            enrich_review_validation_detail(
                {
                    "code": "export_validation",
                    "message": f"{line_label} ({row_type_label}): Exportprüfung blockiert: {', '.join(errors)}.",
                    "line_no": line_no,
                    "row_index": issue.get("row_index"),
                    "row_type": row_type,
                    "row_type_label": row_type_label,
                    "invoice_number": issue.get("invoice_number"),
                    "filename": issue.get("filename"),
                    "export_errors": errors,
                }
            )
        )
    return details


def _booking_export_row_type_label(row_type: str | None) -> str:
    return {
        "cost": "Kostenzeile",
        "payment_adjustment": "Skonto/Zahlungsdifferenz",
    }.get(row_type or "", row_type or "Exportzeile")


def validate_booking_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        row_issues = _booking_export_row_issues(row)
        if row_issues:
            issue_codes = [_booking_export_issue_code(issue) for issue in row_issues]
            issue_categories = unique_preserving_order([_booking_export_issue_category(code) for code in issue_codes])
            issues.append(
                {
                    "row_index": index,
                    "document_id": row.get("document_id"),
                    "filename": row.get("original_filename"),
                    "invoice_number": row.get("invoice_number"),
                    "line_no": row.get("line_no"),
                    "row_type": row.get("row_type"),
                    "errors": row_issues,
                    "error_codes": issue_codes,
                    "error_categories": issue_categories,
                }
            )
    return issues


def _booking_export_row_issues(row: dict[str, Any]) -> list[str]:
    issues = []
    if row.get("accounting_rule_status") == "ambiguous":
        matches = row.get("accounting_rule_matches") or "-"
        issues.append(f"Kontierungsregel mehrdeutig: {matches}")

    required_fields = {
        "document_id": "Dokument-ID",
        "invoice_number": "Belegnummer",
        "invoice_date": "Belegdatum",
        "supplier_name": "Lieferant",
        "document_type": "Belegart",
        "currency": "Währung",
        "row_type": "Zeilentyp",
        "booking_type": "Buchungsart",
        "description": "Beschreibung",
        "cost_category": "Kostenart",
    }
    for field_name, label in required_fields.items():
        if row.get(field_name) in (None, ""):
            issues.append(f"{label} fehlt")

    if row.get("accounting_rule_status") != "ambiguous":
        for field_name, label in (
            ("debit_account", "Aufwandskonto"),
            ("credit_account", "Gegenkonto"),
            ("accounting_rule", "Kontierungsregel"),
        ):
            if row.get(field_name) in (None, ""):
                issues.append(f"{label} fehlt")

    if row.get("row_type") == "payment_adjustment":
        for field_name, label in (
            ("payable_delta", "Zahlungsdifferenz"),
            ("gross_amount", "Brutto-Differenz"),
            ("net_amount", "Netto-Differenz"),
            ("tax_amount", "USt-Differenz"),
        ):
            if row.get(field_name) in (None, ""):
                issues.append(f"{label} fehlt")
        if row.get("accounting_rule_status") != "ambiguous" and row.get("discount_account") in (None, ""):
            issues.append("Skontokonto fehlt")
    else:
        for field_name, label in (
            ("net_amount", "Netto"),
            ("tax_amount", "USt"),
            ("gross_amount", "Brutto"),
        ):
            if row.get(field_name) in (None, ""):
                issues.append(f"{label} fehlt")

    for field_name, label in (
        ("net_amount", "Netto"),
        ("tax_amount", "USt"),
        ("gross_amount", "Brutto"),
        ("payable_delta", "Zahlungsdifferenz"),
        ("payment_amount", "Zahlbetrag"),
        ("discount_base", "Skonto-Basis"),
        ("discount_percent", "Skonto-Prozent"),
        ("discount_amount", "Skonto"),
        ("tax_rate", "Steuersatz"),
    ):
        value = row.get(field_name)
        if value not in (None, "") and _decimal_or_none(value) is None:
            issues.append(f"{label} ist keine gültige Zahl")

    tax_amount = _decimal_or_none(row.get("tax_amount"))
    if (
        row.get("accounting_rule_status") != "ambiguous"
        and tax_amount
        and tax_amount != Decimal("0.00")
        and not row.get("tax_key")
        and not row.get("tax_rate")
    ):
        issues.append("Steuerangabe fehlt")

    if row.get("row_type") == "payment_adjustment":
        payable_delta = _decimal_or_none(row.get("payable_delta"))
        gross_amount = _decimal_or_none(row.get("gross_amount"))
        net_amount = _decimal_or_none(row.get("net_amount"))
        tax_amount = _decimal_or_none(row.get("tax_amount"))
        if payable_delta is not None and gross_amount is not None and payable_delta != gross_amount:
            issues.append("Zahlungsdifferenz passt nicht zur Brutto-Differenz")
        if net_amount is not None and tax_amount is not None and gross_amount is not None:
            if abs(_round_money(net_amount + tax_amount) - _round_money(gross_amount)) > Decimal("0.01"):
                issues.append("Netto- und USt-Differenz passen nicht zur Brutto-Differenz")

    return unique_preserving_order(issues)


def _booking_export_issue_code(issue: str) -> str:
    normalized = issue.lower()
    if "kontierungsregel mehrdeutig" in normalized:
        return "ambiguous_accounting_rule"
    if "kontierungsregel fehlt" in normalized:
        return "missing_accounting_rule"
    if "aufwandskonto fehlt" in normalized:
        return "missing_debit_account"
    if "gegenkonto fehlt" in normalized:
        return "missing_credit_account"
    if "skontokonto fehlt" in normalized:
        return "missing_discount_account"
    if "steuerangabe fehlt" in normalized:
        return "missing_tax_setting"
    if "keine gültige zahl" in normalized:
        return "invalid_number"
    if "zahlungsdifferenz" in normalized:
        return "invalid_payment_delta"
    if "ust-differenz" in normalized or "netto-differenz" in normalized or "brutto-differenz" in normalized:
        return "missing_payment_delta_amount"
    if "zuordnung" in normalized:
        return "missing_assignment"
    if "belegnummer" in normalized:
        return "missing_invoice_number"
    if "belegdatum" in normalized:
        return "missing_invoice_date"
    if "lieferant" in normalized:
        return "missing_supplier"
    if "kostenart" in normalized:
        return "missing_cost_category"
    return "export_validation"


def _booking_export_issue_category(code: str) -> str:
    if code in {
        "ambiguous_accounting_rule",
        "missing_accounting_rule",
        "missing_debit_account",
        "missing_credit_account",
        "missing_discount_account",
        "tenant_accounting_defaults_used",
    }:
        return "accounting"
    if code in {"invalid_payment_delta", "missing_payment_delta_amount", "payment_decision_default"}:
        return "payment"
    if code in {"missing_assignment", "unknown_assignment"}:
        return "assignment"
    if code in {"missing_tax_setting", "missing_payment_adjustment_tax_split", "invalid_number"}:
        return "tax"
    return "export"


def enrich_review_validation_detail(detail: dict[str, Any]) -> dict[str, Any]:
    code = detail.get("code") or "review_validation"
    field = detail.get("field")
    metadata = _review_validation_metadata(code, field=field, line_no=detail.get("line_no"))
    return {**metadata, **detail}


def _review_validation_metadata(code: str, field: str | None = None, line_no: Any = None) -> dict[str, Any]:
    category = "review"
    action = "review_document"
    target = "review"
    severity = "blocker"

    if code in {
        "missing_accounting_rule",
        "ambiguous_accounting_rule",
        "incomplete_accounting_rule",
        "missing_discount_account",
    }:
        category = "accounting"
        target = "accounting_rules"
        action = "create_accounting_rule" if code == "missing_accounting_rule" else "edit_accounting_rule"
    elif code == "missing_payment_decision":
        category = "payment"
        target = "payment_terms"
        action = "choose_payment_decision"
    elif code in {"missing_booking_suggestions", "split_total_mismatch", "invalid_cost_category"}:
        category = "booking"
        target = "booking_lines"
        action = "edit_booking_lines"
    elif code == "missing_assignment":
        category = "assignment"
        target = "booking_lines"
        action = "edit_booking_line"
    elif code == "unknown_assignment":
        category = "assignment"
        target = "assignment_units"
        action = "create_assignment_unit"
    elif code in {"low_confidence", "open_warnings", "structured_validation_failed"}:
        category = "extraction"
        target = "extraction"
        action = "review_extraction"
    elif code == "export_validation":
        category = "export"
        target = "booking_export"
        action = "fix_export_blocker"
    elif code == "invalid_review_status":
        category = "status"
        target = "review_status"
        action = "open_review"
    elif field in {"supplier_name", "invoice_number", "invoice_date", "document_type", "currency"}:
        category = "extraction"
        target = "extraction"
        action = "edit_extraction_field"
    elif field in {"net_amount", "tax_amount", "gross_amount"} and line_no is None:
        category = "extraction"
        target = "extraction"
        action = "edit_extraction_field"
    elif field in {"booking_type", "cost_category", "description", "net_amount", "tax_amount", "gross_amount"}:
        category = "booking"
        target = "booking_lines"
        action = "edit_booking_line"

    return {
        "category": category,
        "severity": severity,
        "action": action,
        "target": target,
    }


def unique_preserving_order(values: list[str]) -> list[str]:
    seen = set()
    unique_values = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


ASSIGNMENT_RELEVANT_COST_CATEGORIES = {"material", "subcontractor"}


def _assignment_resolution_hint(raw_result: dict[str, Any]) -> str | None:
    return (
        raw_result.get("customer_reference")
        or raw_result.get("delivery_address")
        or raw_result.get("project_name")
    )


def _requires_assignment_resolution(suggestion: dict[str, Any], raw_result: dict[str, Any]) -> bool:
    if raw_result.get("assignment_type") != "assignment_unresolved":
        return False
    cost_category = suggestion.get("cost_category") or raw_result.get("cost_category")
    if cost_category not in ASSIGNMENT_RELEVANT_COST_CATEGORIES:
        return False
    return bool(_assignment_resolution_hint(raw_result))


def validate_document_review_details(document: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    extraction = document.get("extraction") or {}
    raw_result = extraction.get("raw_result") or {}
    suggestions = document.get("booking_suggestions") or []
    supplier_name = extraction.get("supplier_name")
    tenant_defaults = _tenant_accounting_defaults(document.get("tenant_id"))

    def add_error(message: str, code: str = "review_validation", **context: Any) -> None:
        errors.append(enrich_review_validation_detail({"code": code, "message": message, **context}))

    required_extraction_fields = {
        "supplier_name": "Lieferant",
        "invoice_number": "Belegnummer",
        "invoice_date": "Belegdatum",
        "net_amount": "Netto",
        "tax_amount": "USt",
        "gross_amount": "Brutto",
        "currency": "Währung",
    }
    for field_name, label in required_extraction_fields.items():
        if extraction.get(field_name) in (None, ""):
            add_error(f"Pflichtfeld fehlt: {label}.", field=field_name)

    confidence = _decimal_or_none(extraction.get("confidence"))
    if confidence is not None and confidence < Decimal("0.80"):
        add_error("Extraktion ist zu unsicher für finale Freigabe.", code="low_confidence")
    if raw_result.get("document_type") in (None, ""):
        add_error("Pflichtfeld fehlt: Belegart.", field="document_type")
    if extraction.get("warnings"):
        add_error("Offene Extraktionswarnungen müssen vor finaler Freigabe geklärt werden.", code="open_warnings")
    structured_validation = raw_result.get("structured_validation") or {}
    if raw_result.get("structured_validation_errors") or structured_validation.get("status") == "failed":
        add_error("E-Rechnungsvalidierung ist fehlgeschlagen.", code="structured_validation_failed")

    if not suggestions:
        add_error("Keine Buchungsvorschläge vorhanden.", code="missing_booking_suggestions")

    for suggestion in suggestions:
        line_no = suggestion.get("line_no") or "?"
        if not suggestion.get("booking_type"):
            add_error(f"Zeile {line_no}: Belegart fehlt.", line_no=line_no, field="booking_type")
        if not suggestion.get("cost_category"):
            add_error(f"Zeile {line_no}: Kostenart fehlt.", line_no=line_no, field="cost_category")
        if not suggestion.get("description"):
            add_error(f"Zeile {line_no}: Beschreibung fehlt.", line_no=line_no, field="description")
        for amount_field, label in (
            ("net_amount", "Netto"),
            ("tax_amount", "USt"),
            ("gross_amount", "Brutto"),
        ):
            if _decimal_or_none(suggestion.get(amount_field)) is None:
                add_error(f"Zeile {line_no}: {label} fehlt.", line_no=line_no, field=amount_field)

        cost_category = suggestion.get("cost_category")
        accounting_rule = None
        accounting_rule_matches: list[dict[str, Any]] = []
        if cost_category and cost_category not in VALID_COST_CATEGORIES:
            add_error(
                f"Zeile {line_no}: Kostenart unbekannt: {cost_category}.",
                code="invalid_cost_category",
                line_no=line_no,
                field="cost_category",
                cost_category=cost_category,
                cost_category_label=_cost_category_label(cost_category),
            )
            continue
        assignment_code = suggestion.get("assignment_code")
        if assignment_code and not get_assignment_unit_by_code(document.get("tenant_id"), assignment_code):
            add_error(
                f"Zeile {line_no}: Zuordnung {assignment_code} ist nicht in den Stammdaten angelegt.",
                code="unknown_assignment",
                line_no=line_no,
                field="assignment_code",
                assignment_code=assignment_code,
                assignment_kind=suggestion.get("assignment_kind") or raw_result.get("assignment_kind"),
            )
        elif not assignment_code and _requires_assignment_resolution(suggestion, raw_result):
            assignment_hint = _assignment_resolution_hint(raw_result)
            add_error(
                f"Zeile {line_no}: Zuordnung fehlt, obwohl der Beleg einen Projekt-/Zuordnungshinweis enthält.",
                code="missing_assignment",
                line_no=line_no,
                field="assignment_code",
                assignment_hint=assignment_hint,
                assignment_kind=suggestion.get("assignment_kind") or raw_result.get("assignment_kind"),
            )
        if cost_category:
            accounting_rule_matches = find_accounting_rule_matches(
                tenant_id=document.get("tenant_id"),
                supplier_name=supplier_name,
                cost_category=cost_category,
            )
            accounting_rule = accounting_rule_matches[0] if len(accounting_rule_matches) == 1 else None
        if len(accounting_rule_matches) > 1:
            context = _accounting_rule_context(supplier_name, cost_category)
            add_error(
                f"Zeile {line_no}: Mehrere Kontierungsregeln passen für {context}. "
                "Bitte unter Stammdaten die Regeln eindeutiger machen.",
                code="ambiguous_accounting_rule",
                line_no=line_no,
                supplier_name=supplier_name,
                cost_category=cost_category,
                cost_category_label=_cost_category_label(cost_category),
                matching_rules=[
                    {
                        "id": str(rule.get("id")) if rule.get("id") else None,
                        "name": rule.get("name"),
                        "supplier_match_text": rule.get("supplier_match_text"),
                        "cost_category": rule.get("cost_category"),
                        "cost_category_label": _cost_category_label(rule.get("cost_category")),
                    }
                    for rule in accounting_rule_matches
                ],
            )
        elif cost_category and not accounting_rule:
            context = _accounting_rule_context(supplier_name, cost_category)
            bwa_account_hints = find_bwa_account_hints(
                tenant_id=document.get("tenant_id"),
                supplier_name=supplier_name,
                cost_category=cost_category,
            )
            suggested_bwa_account = _best_bwa_expense_account_hint(bwa_account_hints)
            add_error(
                f"Zeile {line_no}: Kontierungsregel fehlt für {context}. "
                "Bitte unter Stammdaten -> Kontierungsregeln anlegen.",
                code="missing_accounting_rule",
                line_no=line_no,
                supplier_name=supplier_name,
                cost_category=cost_category,
                cost_category_label=_cost_category_label(cost_category),
                suggested_name=f"{_cost_category_label(cost_category)} {supplier_name or ''}".strip(),
                bwa_account_hints=bwa_account_hints,
                suggested_debit_account=suggested_bwa_account.get("account") if suggested_bwa_account else None,
                suggested_debit_account_label=suggested_bwa_account.get("label") if suggested_bwa_account else None,
                suggested_debit_account_source="BWA" if suggested_bwa_account else None,
            )
        elif accounting_rule and (
            not accounting_rule.get("debit_account")
            or not (accounting_rule.get("credit_account") or tenant_defaults.get("default_credit_account"))
        ):
            context = _accounting_rule_context(supplier_name, cost_category)
            add_error(
                f"Zeile {line_no}: Kontierungsregel ist unvollständig für {context}. "
                "Aufwandskonto oder Gegenkonto fehlt.",
                code="incomplete_accounting_rule",
                line_no=line_no,
                supplier_name=supplier_name,
                cost_category=cost_category,
                cost_category_label=_cost_category_label(cost_category),
                accounting_rule_id=str(accounting_rule.get("id")) if accounting_rule.get("id") else None,
                accounting_rule_name=accounting_rule.get("name"),
                suggested_name=accounting_rule.get("name") or f"{_cost_category_label(cost_category)} {supplier_name or ''}".strip(),
            )

    if suggestions and (len(suggestions) > 1 or raw_result.get("allocation_lines")):
        for message in _validate_split_totals(suggestions, extraction):
            add_error(message, code="split_total_mismatch")

    payment_terms = _payment_terms_from_extraction(extraction)
    payment_decision = document.get("payment_decision")
    if len(payment_terms) > 1 and not payment_decision:
        add_error(
            "Zahlungsentscheidung fehlt: Skonto/ohne Abzug/Gutschrift-Verrechnung muss gewählt werden.",
            code="missing_payment_decision",
        )
    payment_decision = payment_decision or _default_payment_decision(extraction)
    payment_delta = _payment_delta(extraction, payment_decision)
    if payment_delta is not None and payment_delta != Decimal("0.00") and suggestions:
        for suggestion in suggestions:
            line_no = suggestion.get("line_no") or "?"
            cost_category = suggestion.get("cost_category")
            accounting_rule_matches = find_accounting_rule_matches(
                tenant_id=document.get("tenant_id"),
                supplier_name=supplier_name,
                cost_category=cost_category,
            )
            accounting_rule = accounting_rule_matches[0] if len(accounting_rule_matches) == 1 else None
            if accounting_rule and not (accounting_rule.get("discount_account") or tenant_defaults.get("default_discount_account")):
                add_error(
                    f"Zeile {line_no}: Zahlungsdifferenz/Skonto braucht ein Skontokonto in der Kontierungsregel.",
                    code="missing_discount_account",
                    line_no=line_no,
                    supplier_name=supplier_name,
                    cost_category=cost_category,
                    cost_category_label=_cost_category_label(cost_category),
                    accounting_rule_id=str(accounting_rule.get("id")) if accounting_rule.get("id") else None,
                    accounting_rule_name=accounting_rule.get("name"),
                    suggested_name=accounting_rule.get("name"),
                )

    if not errors:
        errors.extend(validate_document_review_export_details(document))

    return errors


def _validate_split_totals(suggestions: list[dict[str, Any]], extraction: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for amount_field, label in (
        ("net_amount", "Netto"),
        ("tax_amount", "USt"),
        ("gross_amount", "Brutto"),
    ):
        expected = _decimal_or_none(extraction.get(amount_field))
        if expected is None:
            continue
        values = [_decimal_or_none(suggestion.get(amount_field)) for suggestion in suggestions]
        if any(value is None for value in values):
            continue
        actual = sum((value for value in values if value is not None), Decimal("0.00"))
        if abs(_round_money(actual) - _round_money(expected)) > Decimal("0.02"):
            errors.append(f"Split-Summe {label} passt nicht zum Beleggesamtbetrag.")
    return errors


def reopen_document_review(document_id: UUID, actor: str = "system") -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None or not document.get("extraction") or not document.get("booking_suggestions"):
        return None

    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_booking_suggestions
                set status = 'reviewed', updated_at = %s
                where document_id = %s and status = 'approved'
                """,
                (now, document_id),
            )
            cursor.execute(
                """
                update documents
                set status = 'review_ready', updated_at = %s
                where id = %s
                """,
                (now, document_id),
            )

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.review_reopened",
        document_id=document_id,
        actor=actor,
        details={"suggestion_count": len(document.get("booking_suggestions") or [])},
    )
    return get_document(document_id)


def prepare_document_review(document_id: UUID, actor: str = "system") -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None or not document.get("extraction"):
        return None

    extraction = document["extraction"]
    suggestions = _booking_suggestions_from_extraction(document, extraction)
    now = datetime.now(UTC)

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("delete from document_booking_suggestions where document_id = %s", (document_id,))
            for line_no, suggestion in enumerate(suggestions, start=1):
                project_number = _assignment_project_number(document["tenant_id"], suggestion.get("assignment_code"))
                cursor.execute(
                    """
                    insert into document_booking_suggestions (
                        id, document_id, tenant_id, line_no, booking_type, cost_category,
                        assignment_code, assignment_project_number, assignment_kind, description,
                        net_amount, tax_amount, gross_amount, currency, status, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'suggested', %s, %s)
                    """,
                    (
                        uuid4(),
                        document_id,
                        document["tenant_id"],
                        line_no,
                        suggestion["booking_type"],
                        suggestion.get("cost_category"),
                        suggestion.get("assignment_code"),
                        project_number,
                        suggestion.get("assignment_kind"),
                        suggestion.get("description"),
                        suggestion.get("net_amount"),
                        suggestion.get("tax_amount"),
                        suggestion.get("gross_amount"),
                        suggestion.get("currency", "EUR"),
                        now,
                        now,
                    ),
                )
            cursor.execute(
                """
                update documents
                set status = 'review_ready', updated_at = %s
                where id = %s
                """,
                (now, document_id),
            )

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.review_prepared",
        document_id=document_id,
        actor=actor,
        details={"suggestion_count": len(suggestions)},
    )
    return get_document(document_id)


def update_booking_suggestion(
    document_id: UUID,
    suggestion_id: UUID,
    values: dict[str, Any],
    actor: str = "system",
) -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None:
        return None
    if document["status"] == "review_approved":
        raise ValueError("approved document cannot be edited")

    now = datetime.now(UTC)
    assignment_project_number = values.get("project_number") or _assignment_project_number(document["tenant_id"], values.get("assignment_code"))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update document_booking_suggestions
                set
                    booking_type = %s,
                    cost_category = %s,
                    assignment_code = %s,
                    assignment_project_number = %s,
                    assignment_kind = %s,
                    description = %s,
                    net_amount = %s,
                    tax_amount = %s,
                    gross_amount = %s,
                    currency = %s,
                    status = 'reviewed',
                    updated_at = %s
                where id = %s and document_id = %s
                returning *
                """,
                (
                    values.get("booking_type"),
                    values.get("cost_category"),
                    values.get("assignment_code"),
                    assignment_project_number,
                    values.get("assignment_kind"),
                    values.get("description"),
                    values.get("net_amount"),
                    values.get("tax_amount"),
                    values.get("gross_amount"),
                    values.get("currency", "EUR"),
                    now,
                    suggestion_id,
                    document_id,
                ),
            )
            updated = cursor.fetchone()

    if updated is None:
        return None

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.booking_suggestion_updated",
        document_id=document_id,
        actor=actor,
        details={
            "suggestion_id": str(suggestion_id),
            "line_no": updated["line_no"],
            "net_amount": str(updated["net_amount"]) if updated["net_amount"] is not None else None,
            "tax_amount": str(updated["tax_amount"]) if updated["tax_amount"] is not None else None,
            "gross_amount": str(updated["gross_amount"]) if updated["gross_amount"] is not None else None,
        },
    )
    return get_document(document_id)


def select_payment_decision(
    document_id: UUID,
    payment_type: str,
    actor: str = "system",
) -> dict[str, Any] | None:
    document = get_document(document_id)
    if document is None or not document.get("extraction"):
        return None
    if document["status"] == "review_approved":
        raise ValueError("approved document cannot be edited")

    selected_term = _payment_term_by_type(document["extraction"], payment_type)
    if selected_term is None:
        raise ValueError("payment option not available")

    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into document_payment_decisions (
                    id, document_id, tenant_id, payment_type, label, due_date, amount,
                    discount_base, discount_percent, discount_amount, currency, status,
                    created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'selected', %s, %s)
                on conflict (document_id) do update set
                    payment_type = excluded.payment_type,
                    label = excluded.label,
                    due_date = excluded.due_date,
                    amount = excluded.amount,
                    discount_base = excluded.discount_base,
                    discount_percent = excluded.discount_percent,
                    discount_amount = excluded.discount_amount,
                    currency = excluded.currency,
                    status = 'selected',
                    updated_at = excluded.updated_at
                returning *
                """,
                (
                    uuid4(),
                    document_id,
                    document["tenant_id"],
                    selected_term["type"],
                    selected_term["label"],
                    selected_term.get("due_date"),
                    _decimal_or_none(selected_term.get("amount")),
                    _decimal_or_none(selected_term.get("discount_base")),
                    _decimal_or_none(selected_term.get("discount_percent")),
                    _decimal_or_none(selected_term.get("discount_amount")),
                    selected_term.get("currency") or "EUR",
                    now,
                    now,
                ),
            )
            saved = cursor.fetchone()

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.payment_decision_selected",
        document_id=document_id,
        actor=actor,
        details={
            "payment_type": saved["payment_type"],
            "amount": str(saved["amount"]) if saved["amount"] is not None else None,
            "discount_amount": str(saved["discount_amount"]) if saved["discount_amount"] is not None else None,
            "due_date": _serialize_date(saved["due_date"]),
        },
    )
    return get_document(document_id)


def build_booking_export_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    project_number_maps: dict[str, dict[str, str | None]] = {}

    def project_number_for(tenant_id: str | None, suggestion: dict[str, Any] | None) -> str | None:
        if not tenant_id or not suggestion:
            return None
        if suggestion.get("assignment_project_number"):
            return suggestion.get("assignment_project_number")
        assignment_code = _normalize_assignment_code_key(suggestion.get("assignment_code"))
        if not assignment_code:
            return None
        if tenant_id not in project_number_maps:
            project_number_maps[tenant_id] = {
                _normalize_assignment_code_key(unit["code"]): unit.get("project_number")
                for unit in list_assignment_units(tenant_id)
                if _normalize_assignment_code_key(unit["code"])
            }
        return project_number_maps[tenant_id].get(assignment_code)

    for document in documents:
        if document.get("status") != "review_approved":
            continue

        extraction = document.get("extraction") or {}
        raw_result = extraction.get("raw_result") or {}
        selected_payment_decision = document.get("payment_decision")
        payment_decision = selected_payment_decision or _default_payment_decision(extraction)
        supplier_name = extraction.get("supplier_name")
        common = {
            "tenant_id": document.get("tenant_id"),
            "document_id": document.get("id"),
            "original_filename": document.get("original_filename"),
            "normalized_filename": document.get("normalized_filename"),
            "supplier_name": supplier_name,
            "invoice_number": extraction.get("invoice_number"),
            "invoice_date": extraction.get("invoice_date"),
            "document_type": raw_result.get("document_type") or "incoming_invoice",
            "currency": extraction.get("currency") or "EUR",
            "payment_type": payment_decision.get("payment_type") if payment_decision else None,
            "payment_label": payment_decision.get("label") if payment_decision else None,
            "payment_decision_source": "gewählt" if selected_payment_decision else "Standard",
            "payment_due_date": payment_decision.get("due_date") if payment_decision else None,
            "payment_amount": _money_string(payment_decision.get("amount")) if payment_decision else None,
            "discount_base": _money_string(payment_decision.get("discount_base")) if payment_decision else None,
            "discount_percent": _money_string(payment_decision.get("discount_percent")) if payment_decision else None,
            "discount_amount": _money_string(payment_decision.get("discount_amount")) if payment_decision else None,
        }

        for suggestion in document.get("booking_suggestions") or []:
            accounting_rule_fields = _resolve_accounting_rule_export_fields(
                tenant_id=document.get("tenant_id"),
                supplier_name=supplier_name,
                cost_category=suggestion.get("cost_category"),
            )
            row = {
                **common,
                "row_type": "cost",
                "line_no": suggestion.get("line_no"),
                "booking_type": suggestion.get("booking_type"),
                "cost_category": suggestion.get("cost_category"),
                "assignment_kind": suggestion.get("assignment_kind"),
                "assignment_code": suggestion.get("assignment_code"),
                "assignment_project_number": project_number_for(document.get("tenant_id"), suggestion),
                "description": suggestion.get("description"),
                "net_amount": _money_string(suggestion.get("net_amount")),
                "tax_amount": _money_string(suggestion.get("tax_amount")),
                "gross_amount": _money_string(suggestion.get("gross_amount")),
                "payable_delta": None,
                **accounting_rule_fields,
            }
            _set_booking_export_warnings(row)
            rows.append(row)

        rows.extend(_payment_adjustment_export_rows(document, common, extraction, payment_decision, supplier_name, project_number_for))
    return rows


def _payment_adjustment_export_rows(
    document: dict[str, Any],
    common: dict[str, Any],
    extraction: dict[str, Any],
    payment_decision: dict[str, Any] | None,
    supplier_name: str | None,
    project_number_for,
) -> list[dict[str, Any]]:
    payment_delta = _payment_delta(extraction, payment_decision)
    if payment_delta is None or payment_delta == Decimal("0.00"):
        return []

    suggestions = document.get("booking_suggestions") or []
    allocations = _allocate_payment_delta(payment_delta, suggestions)
    if not allocations:
        allocations = [(None, payment_delta)]

    raw_result = extraction.get("raw_result") or {}
    rows = []
    for suggestion, allocated_delta in allocations:
        if allocated_delta == Decimal("0.00"):
            continue
        adjustment_net, adjustment_tax = _payment_adjustment_net_tax(allocated_delta, suggestion, extraction, payment_delta)
        cost_category = suggestion.get("cost_category") if suggestion else None
        accounting_rule_fields = _resolve_accounting_rule_export_fields(
            tenant_id=document.get("tenant_id"),
            supplier_name=supplier_name,
            cost_category=cost_category,
            payment_adjustment=True,
        )
        row = {
            **common,
            "row_type": "payment_adjustment",
            "line_no": suggestion.get("line_no") if suggestion else None,
            "booking_type": suggestion.get("booking_type") if suggestion else raw_result.get("document_type") or "incoming_invoice",
            "cost_category": cost_category or "payment_discount",
            "assignment_kind": suggestion.get("assignment_kind") if suggestion else None,
            "assignment_code": suggestion.get("assignment_code") if suggestion else None,
            "assignment_project_number": project_number_for(document.get("tenant_id"), suggestion),
            "description": payment_decision.get("label") if payment_decision else "Zahlungsdifferenz",
            "net_amount": _money_string(adjustment_net),
            "tax_amount": _money_string(adjustment_tax),
            "gross_amount": _money_string(allocated_delta),
            "payable_delta": _money_string(allocated_delta),
            **accounting_rule_fields,
        }
        _set_booking_export_warnings(row)
        rows.append(row)
    return rows


def _assignment_project_number(tenant_id: str | None, assignment_code: str | None) -> str | None:
    if not tenant_id or not assignment_code:
        return None
    assignment = get_assignment_unit_by_code(tenant_id, assignment_code)
    return assignment.get("project_number") if assignment else None


def _normalize_assignment_code_key(code: str | None) -> str | None:
    if not code:
        return None
    normalized = code.strip().casefold()
    return normalized or None


def _payment_adjustment_net_tax(
    allocated_delta: Decimal,
    suggestion: dict[str, Any] | None,
    extraction: dict[str, Any],
    total_delta: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    explicit_net = _decimal_or_none((extraction.get("raw_result") or {}).get("discount_net_amount"))
    explicit_tax = _decimal_or_none((extraction.get("raw_result") or {}).get("discount_tax_amount"))
    if explicit_net is not None and explicit_tax is not None and total_delta != Decimal("0.00"):
        sign = Decimal("-1") if total_delta < 0 else Decimal("1")
        ratio = allocated_delta / total_delta
        net_amount = _round_money(sign * abs(explicit_net) * ratio)
        tax_amount = _round_money(allocated_delta - net_amount)
        expected_tax = _round_money(sign * abs(explicit_tax) * ratio)
        if abs(tax_amount - expected_tax) <= Decimal("0.01"):
            return net_amount, tax_amount

    basis = suggestion or extraction
    gross_basis = _decimal_or_none(basis.get("gross_amount"))
    net_basis = _decimal_or_none(basis.get("net_amount"))
    tax_basis = _decimal_or_none(basis.get("tax_amount"))
    if gross_basis and net_basis is not None and tax_basis is not None:
        net_amount = _round_money(allocated_delta * net_basis / gross_basis)
        tax_amount = _round_money(allocated_delta - net_amount)
        return net_amount, tax_amount
    return None, None


def _booking_export_warnings(row: dict[str, Any]) -> str:
    return "; ".join(item["message"] for item in _booking_export_warning_items(row))


def _set_booking_export_warnings(row: dict[str, Any]) -> None:
    warning_items = _booking_export_warning_items(row)
    row["export_warnings"] = "; ".join(item["message"] for item in warning_items)
    row["export_warning_codes"] = ";".join(item["code"] for item in warning_items)
    row["export_warning_categories"] = ";".join(
        unique_preserving_order([item["category"] for item in warning_items])
    )


def _booking_export_warning_items(row: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    def add_warning(code: str, message: str) -> None:
        warnings.append(
            {
                "code": code,
                "category": _booking_export_issue_category(code),
                "message": message,
            }
        )

    if row.get("payment_decision_source") == "Standard":
        add_warning("payment_decision_default", "Zahlung nicht manuell gewählt")
    if not row.get("assignment_code"):
        add_warning("missing_assignment", "Zuordnung fehlt")
    if row.get("accounting_rule_status") == "ambiguous":
        matches = row.get("accounting_rule_matches")
        add_warning(
            "ambiguous_accounting_rule",
            f"Kontierungsregel mehrdeutig: {matches}" if matches else "Kontierungsregel mehrdeutig",
        )
    elif not row.get("accounting_rule"):
        add_warning("missing_accounting_rule", "Kontierungsregel fehlt")
    if row.get("row_type") == "payment_adjustment":
        if row.get("net_amount") in (None, "") or row.get("tax_amount") in (None, ""):
            add_warning("missing_payment_adjustment_tax_split", "Skonto-/Vorsteueraufteilung fehlt")
        if not row.get("discount_account"):
            add_warning("missing_discount_account", "Skontokonto fehlt")
    else:
        if not row.get("debit_account"):
            add_warning("missing_debit_account", "Aufwandskonto fehlt")
        if not row.get("credit_account"):
            add_warning("missing_credit_account", "Gegenkonto fehlt")
        if not row.get("tax_key") and not row.get("tax_rate"):
            add_warning("missing_tax_setting", "Steuerangabe prüfen")
    default_sources = []
    if row.get("credit_account_source") == "Mandantenstandard":
        default_sources.append("Gegenkonto")
    if row.get("tax_source") == "Mandantenstandard":
        default_sources.append("Steuer")
    if row.get("discount_account_source") == "Mandantenstandard":
        default_sources.append("Skonto")
    if default_sources:
        add_warning(
            "tenant_accounting_defaults_used",
            f"Mandantenstandard genutzt: {', '.join(default_sources)}",
        )
    return warnings


def _allocate_payment_delta(
    payment_delta: Decimal,
    suggestions: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], Decimal]]:
    weighted_suggestions = [
        (suggestion, _decimal_or_none(suggestion.get("gross_amount")))
        for suggestion in suggestions
    ]
    weighted_suggestions = [(suggestion, amount) for suggestion, amount in weighted_suggestions if amount]
    if not weighted_suggestions:
        return []

    total_gross = sum((amount for _, amount in weighted_suggestions), Decimal("0.00"))
    if total_gross == Decimal("0.00"):
        return []

    allocations: list[tuple[dict[str, Any], Decimal]] = []
    allocated_total = Decimal("0.00")
    for index, (suggestion, gross_amount) in enumerate(weighted_suggestions):
        if index == len(weighted_suggestions) - 1:
            allocated = _round_money(payment_delta - allocated_total)
        else:
            allocated = _round_money(payment_delta * gross_amount / total_gross)
            allocated_total += allocated
        allocations.append((suggestion, allocated))
    return allocations


def _booking_suggestions_from_extraction(document: dict[str, Any], extraction: dict[str, Any]) -> list[dict[str, Any]]:
    raw_result = extraction.get("raw_result") or {}
    booking_type = raw_result.get("document_type") or "incoming_invoice"
    currency = extraction.get("currency") or "EUR"
    cost_category = raw_result.get("cost_category")
    description = raw_result.get("item_summary") or extraction.get("supplier_name") or document["original_filename"]
    allocation_lines = raw_result.get("allocation_lines") or []
    total_net = _decimal_or_none(extraction.get("net_amount"))
    total_tax = _decimal_or_none(extraction.get("tax_amount"))
    tax_ratio = (total_tax / total_net) if total_net and total_tax is not None else Decimal("0")

    if allocation_lines:
        suggestions = []
        for line in allocation_lines:
            net_amount = _decimal_or_none(line.get("amount"))
            tax_amount = _round_money(net_amount * tax_ratio) if net_amount is not None else None
            gross_amount = _round_money(net_amount + tax_amount) if net_amount is not None and tax_amount is not None else None
            suggestions.append(
                {
                    "booking_type": booking_type,
                    "cost_category": line.get("cost_category") or cost_category,
                    "assignment_code": line.get("assignment_code") or line.get("project_code"),
                    "assignment_kind": line.get("assignment_kind") or raw_result.get("assignment_kind"),
                    "description": line.get("description") or description,
                    "net_amount": net_amount,
                    "tax_amount": tax_amount,
                    "gross_amount": gross_amount,
                    "currency": currency,
                }
            )
        return suggestions

    return [
        {
            "booking_type": booking_type,
            "cost_category": cost_category,
            "assignment_code": raw_result.get("assignment_code") or raw_result.get("project_code"),
            "assignment_kind": raw_result.get("assignment_kind"),
            "description": description,
            "net_amount": total_net,
            "tax_amount": total_tax,
            "gross_amount": _decimal_or_none(extraction.get("gross_amount")),
            "currency": currency,
        }
    ]


def _payment_term_by_type(extraction: dict[str, Any], payment_type: str) -> dict[str, Any] | None:
    for term in _payment_terms_from_extraction(extraction):
        if term["type"] == payment_type:
            return term
    return None


def _default_payment_decision(extraction: dict[str, Any]) -> dict[str, Any] | None:
    terms = _payment_terms_from_extraction(extraction)
    if not terms:
        return None
    term = terms[0]
    return {
        "payment_type": term["type"],
        "label": term["label"],
        "due_date": term.get("due_date"),
        "amount": term.get("amount"),
        "discount_base": term.get("discount_base"),
        "discount_percent": term.get("discount_percent"),
        "discount_amount": term.get("discount_amount"),
    }


def _payment_delta(extraction: dict[str, Any], payment_decision: dict[str, Any] | None) -> Decimal | None:
    if not payment_decision:
        return None
    gross_amount = _decimal_or_none(extraction.get("gross_amount"))
    payment_amount = _decimal_or_none(payment_decision.get("amount"))
    if gross_amount is None or payment_amount is None:
        return None
    return _round_money(payment_amount - gross_amount)


def _accounting_export_fields(
    rule: dict[str, Any] | None,
    tenant_defaults: dict[str, Any] | None = None,
    payment_adjustment: bool = False,
) -> dict[str, Any]:
    tenant_defaults = tenant_defaults or {}
    default_credit_account = tenant_defaults.get("default_credit_account")
    default_tax_key = tenant_defaults.get("default_tax_key")
    default_tax_rate = tenant_defaults.get("default_tax_rate")
    default_discount_account = tenant_defaults.get("default_discount_account")
    if not rule:
        return {
            "debit_account": None,
            "credit_account": default_credit_account,
            "tax_key": default_tax_key,
            "tax_rate": _money_string(default_tax_rate),
            "discount_account": default_discount_account,
            "accounting_rule": None,
            "accounting_rule_status": "missing",
            "accounting_rule_matches": None,
            "debit_account_source": None,
            "credit_account_source": "Mandantenstandard" if default_credit_account else None,
            "tax_source": "Mandantenstandard" if default_tax_key or default_tax_rate is not None else None,
            "discount_account_source": "Mandantenstandard" if default_discount_account else None,
        }
    discount_account = rule.get("discount_account") or default_discount_account
    credit_account = rule.get("credit_account") or default_credit_account
    tax_key = rule.get("tax_key") or default_tax_key
    tax_rate = rule.get("tax_rate")
    if tax_rate in (None, ""):
        tax_rate = default_tax_rate
    debit_account = discount_account if payment_adjustment and discount_account else rule.get("debit_account")
    return {
        "debit_account": debit_account,
        "credit_account": credit_account,
        "tax_key": tax_key,
        "tax_rate": _money_string(tax_rate),
        "discount_account": discount_account,
        "accounting_rule": rule["name"],
        "accounting_rule_status": "matched",
        "accounting_rule_matches": None,
        "debit_account_source": "Kontierungsregel" if debit_account else None,
        "credit_account_source": "Kontierungsregel" if rule.get("credit_account") else ("Mandantenstandard" if credit_account else None),
        "tax_source": "Kontierungsregel" if rule.get("tax_key") or rule.get("tax_rate") not in (None, "") else ("Mandantenstandard" if tax_key or tax_rate is not None else None),
        "discount_account_source": "Kontierungsregel" if rule.get("discount_account") else ("Mandantenstandard" if discount_account else None),
    }


def _resolve_accounting_rule_export_fields(
    tenant_id: str | None,
    supplier_name: str | None,
    cost_category: str | None,
    payment_adjustment: bool = False,
) -> dict[str, Any]:
    tenant_defaults = _tenant_accounting_defaults(tenant_id)
    matches = find_accounting_rule_matches(tenant_id, supplier_name, cost_category)
    if len(matches) == 1:
        return _accounting_export_fields(matches[0], tenant_defaults, payment_adjustment=payment_adjustment)
    if len(matches) > 1:
        fields = _accounting_export_fields(None, tenant_defaults, payment_adjustment=payment_adjustment)
        fields["accounting_rule_status"] = "ambiguous"
        fields["accounting_rule_matches"] = ", ".join(rule["name"] for rule in matches)
        return fields
    return _accounting_export_fields(None, tenant_defaults, payment_adjustment=payment_adjustment)


def _tenant_accounting_defaults(tenant_id: str | None) -> dict[str, Any]:
    if not tenant_id:
        return {}
    profile = get_tenant_profile(tenant_id)
    if not profile:
        return {}
    return {
        "default_credit_account": profile.get("default_credit_account"),
        "default_tax_key": profile.get("default_tax_key"),
        "default_tax_rate": profile.get("default_tax_rate"),
        "default_discount_account": profile.get("default_discount_account"),
    }


def _payment_terms_from_extraction(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    raw_result = extraction.get("raw_result") or {}
    terms = raw_result.get("payment_terms") or []
    if terms:
        return [_normalize_payment_term(term) for term in terms]

    gross_amount = raw_result.get("gross_amount") or extraction.get("gross_amount")
    if gross_amount is None:
        return []

    document_type = raw_result.get("document_type") or "incoming_invoice"
    currency = extraction.get("currency") or "EUR"
    fallback_terms = [
        {
            "type": "full_amount",
            "label": "Gutschrift verrechnen" if document_type == "credit_note" else "Ohne Abzug zahlen",
            "due_date": raw_result.get("due_date"),
            "amount": gross_amount,
            "currency": currency,
        }
    ]

    discounted_amount = raw_result.get("discounted_payable_amount")
    discount_amount = raw_result.get("discount_amount")
    discount_due_date = raw_result.get("discount_due_date")
    if document_type == "credit_note" and discount_amount is not None:
        discount_amount = -abs(_decimal_or_none(discount_amount))
    if discounted_amount is None and discount_amount is not None:
        discounted_amount = _decimal_or_none(gross_amount) - abs(_decimal_or_none(discount_amount))
    if discount_due_date and discounted_amount is not None:
        fallback_terms.append(
            {
                "type": "credit_note_settlement" if document_type == "credit_note" else "cash_discount",
                "label": "Verrechnung mit Skonto" if document_type == "credit_note" else "Skontozahlung",
                "due_date": discount_due_date,
                "amount": discounted_amount,
                "discount_base": raw_result.get("discount_base"),
                "discount_percent": raw_result.get("discount_percent"),
                "discount_amount": discount_amount,
                "currency": currency,
            }
        )
    return [_normalize_payment_term(term) for term in fallback_terms]


def _normalize_payment_term(term: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": term["type"],
        "label": term.get("label") or term["type"],
        "due_date": term.get("due_date"),
        "amount": _decimal_or_none(term.get("amount")),
        "discount_base": _decimal_or_none(term.get("discount_base")),
        "discount_percent": _decimal_or_none(term.get("discount_percent")),
        "discount_amount": _decimal_or_none(term.get("discount_amount")),
        "currency": term.get("currency") or "EUR",
    }


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
    allowed_tenant_ids: list[str] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    tenant_ids = _normalize_allowed_tenant_ids(allowed_tenant_ids, role)
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
                    allowed_tenant_ids,
                    is_active,
                    created_at,
                    last_login_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, null)
                returning *
                """,
                (
                    uuid4(),
                    email.strip().lower(),
                    password_hash,
                    display_name.strip() or email.strip().lower(),
                    role,
                    Jsonb(tenant_ids),
                    is_active,
                    now,
                ),
            )
            return _serialize_user(cursor.fetchone())


def list_users() -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from users
                order by created_at desc
                """
            )
            return [_serialize_user(row) for row in cursor.fetchall()]


def update_user(
    user_id: UUID,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password_hash: str | None = None,
    allowed_tenant_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    assignments = []
    values: list[Any] = []
    if display_name is not None:
        assignments.append("display_name = %s")
        values.append(display_name.strip())
    if role is not None:
        assignments.append("role = %s")
        values.append(role)
    if is_active is not None:
        assignments.append("is_active = %s")
        values.append(is_active)
    if password_hash is not None:
        assignments.append("password_hash = %s")
        values.append(password_hash)
    if allowed_tenant_ids is not None or role == "admin":
        assignments.append("allowed_tenant_ids = %s")
        values.append(Jsonb(_normalize_allowed_tenant_ids(allowed_tenant_ids, role or "user")))
    if not assignments:
        return None

    values.append(user_id)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                update users
                set {", ".join(assignments)}
                where id = %s
                returning *
                """,
                values,
            )
            row = cursor.fetchone()
            return _serialize_user(row) if row else None


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


def seed_demo_masterdata() -> None:
    ensure_tenant_profile("demo-mandant")
    existing = list_assignment_units("demo-mandant")
    wewe20 = get_assignment_unit_by_code("demo-mandant", "Wewe20")
    if not wewe20 or not wewe20.get("address_line"):
        create_assignment_unit(
            tenant_id="demo-mandant",
            code="Wewe20",
            label="Weseler Weg 20",
            kind="construction_project",
            project_number="25-00008",
            address_line="Weseler Weg 20",
            postal_code="22045",
            city="Hamburg",
            external_id=None,
            revenue_relevant=True,
            aliases=["Weseler Weg 20", "Weseler Weg 20, 22045 Hamburg"],
        )
    neula51 = get_assignment_unit_by_code("demo-mandant", "Neula51")
    if not neula51 or not neula51.get("address_line"):
        create_assignment_unit(
            tenant_id="demo-mandant",
            code="Neula51",
            label="Neusurenland 51",
            kind="construction_project",
            project_number=None,
            address_line="Neusurenland 51",
            postal_code=None,
            city=None,
            external_id=None,
            revenue_relevant=True,
            aliases=["Neusurenland 51", "Kundenreferenz Neusurenland 51"],
        )
    if existing:
        return
    create_supplier_rule(
        tenant_id="demo-mandant",
        match_text="Holz Junge",
        supplier_name="Holz Junge GmbH",
        customer_number="109324",
        default_cost_category="material",
    )
    create_supplier_rule(
        tenant_id="demo-mandant",
        match_text="Georg Klindworth",
        supplier_name="Georg Klindworth oHG",
        customer_number="0113042/504",
        default_cost_category="material",
    )


TENANT_PROFILE_TEMPLATES = {
    "construction": {
        "assignment_label_singular": "Bauvorhaben",
        "assignment_label_plural": "Bauvorhaben",
        "assignment_code_label": "Bauvorhaben",
        "assignment_code_prefix": "BV",
        "default_assignment_kind": "construction_project",
        "allow_multiple_assignments": True,
        "accounting_framework": "SKR03",
        "default_credit_account": "70000",
        "default_tax_key": None,
        "default_tax_rate": Decimal("19.00"),
        "default_discount_account": "3736",
    },
    "fitness_studio": {
        "assignment_label_singular": "Standort",
        "assignment_label_plural": "Standorte",
        "assignment_code_label": "Standort",
        "assignment_code_prefix": None,
        "default_assignment_kind": "location",
        "allow_multiple_assignments": False,
        "accounting_framework": "SKR03",
        "default_credit_account": "70000",
        "default_tax_key": None,
        "default_tax_rate": Decimal("19.00"),
        "default_discount_account": "3736",
    },
    "container_transport": {
        "assignment_label_singular": "Bauvorhaben / Stellplatz",
        "assignment_label_plural": "Bauvorhaben / Stellplätze",
        "assignment_code_label": "Bauvorhaben / Stellplatz",
        "assignment_code_prefix": None,
        "default_assignment_kind": "construction_or_dropoff_site",
        "allow_multiple_assignments": True,
        "accounting_framework": "SKR03",
        "default_credit_account": "70000",
        "default_tax_key": None,
        "default_tax_rate": Decimal("19.00"),
        "default_discount_account": "3736",
    },
    "general": {
        "assignment_label_singular": "Kostenstelle",
        "assignment_label_plural": "Kostenstellen",
        "assignment_code_label": "Kostenstelle",
        "assignment_code_prefix": None,
        "default_assignment_kind": "cost_object",
        "allow_multiple_assignments": True,
        "accounting_framework": "SKR03",
        "default_credit_account": "70000",
        "default_tax_key": None,
        "default_tax_rate": Decimal("19.00"),
        "default_discount_account": "3736",
    },
}


def tenant_profile_template(industry: str) -> dict[str, Any]:
    return TENANT_PROFILE_TEMPLATES.get(industry, TENANT_PROFILE_TEMPLATES["general"])


def ensure_tenant_profile(tenant_id: str) -> dict[str, Any]:
    existing = get_tenant_profile(tenant_id)
    if existing:
        return existing
    template = tenant_profile_template("construction" if tenant_id == "demo-mandant" else "general")
    return upsert_tenant_profile(
        tenant_id=tenant_id,
        display_name=tenant_id,
        industry="construction" if tenant_id == "demo-mandant" else "general",
        assignment_label_singular=template["assignment_label_singular"],
        assignment_label_plural=template["assignment_label_plural"],
        assignment_code_label=template["assignment_code_label"],
        assignment_code_prefix=template["assignment_code_prefix"],
        default_assignment_kind=template["default_assignment_kind"],
        allow_multiple_assignments=template["allow_multiple_assignments"],
        accounting_framework=template["accounting_framework"],
        default_credit_account=template["default_credit_account"],
        default_tax_key=template["default_tax_key"],
        default_tax_rate=template["default_tax_rate"],
        default_discount_account=template["default_discount_account"],
    )


def get_tenant_profile(tenant_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_profiles
                where tenant_id = %s
                limit 1
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
            return _serialize_tenant_profile(row) if row else None


def upsert_tenant_profile(
    tenant_id: str,
    display_name: str,
    industry: str,
    assignment_label_singular: str,
    assignment_label_plural: str,
    assignment_code_label: str,
    assignment_code_prefix: str | None,
    default_assignment_kind: str,
    allow_multiple_assignments: bool,
    accounting_framework: str = "SKR03",
    default_credit_account: str | None = None,
    default_tax_key: str | None = None,
    default_tax_rate: Decimal | None = None,
    default_discount_account: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_profiles (
                    tenant_id, display_name, industry, assignment_label_singular,
                    assignment_label_plural, assignment_code_label, assignment_code_prefix,
                    default_assignment_kind, allow_multiple_assignments, accounting_framework,
                    default_credit_account, default_tax_key, default_tax_rate, default_discount_account,
                    created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id) do update set
                    display_name = excluded.display_name,
                    industry = excluded.industry,
                    assignment_label_singular = excluded.assignment_label_singular,
                    assignment_label_plural = excluded.assignment_label_plural,
                    assignment_code_label = excluded.assignment_code_label,
                    assignment_code_prefix = excluded.assignment_code_prefix,
                    default_assignment_kind = excluded.default_assignment_kind,
                    allow_multiple_assignments = excluded.allow_multiple_assignments,
                    accounting_framework = excluded.accounting_framework,
                    default_credit_account = excluded.default_credit_account,
                    default_tax_key = excluded.default_tax_key,
                    default_tax_rate = excluded.default_tax_rate,
                    default_discount_account = excluded.default_discount_account,
                    updated_at = excluded.updated_at
                returning *
                """,
                (
                    tenant_id.strip(),
                    display_name.strip() or tenant_id.strip(),
                    industry,
                    assignment_label_singular.strip(),
                    assignment_label_plural.strip(),
                    assignment_code_label.strip(),
                    assignment_code_prefix.strip() if assignment_code_prefix else None,
                    default_assignment_kind,
                    allow_multiple_assignments,
                    _normalize_accounting_framework(accounting_framework),
                    _blank_to_none(default_credit_account),
                    _blank_to_none(default_tax_key),
                    default_tax_rate,
                    _blank_to_none(default_discount_account),
                    now,
                    now,
                ),
            )
            return _serialize_tenant_profile(cursor.fetchone())


def list_assignment_units(tenant_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_assignment_units
                where tenant_id = %s
                order by is_active desc, label asc
                """,
                (tenant_id,),
            )
            return [_serialize_assignment_unit(row) for row in cursor.fetchall()]


def list_bwa_imports(tenant_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_bwa_imports
                where tenant_id = %s
                order by created_at desc
                """,
                (tenant_id,),
            )
            return [_serialize_bwa_import(row) for row in cursor.fetchall()]


def create_bwa_import(
    tenant_id: str,
    stored: StoredDocument,
    period: str | None,
    account_hints: list[dict[str, Any]],
    warnings: list[str],
    text_excerpt: str,
) -> tuple[dict[str, Any], bool]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_bwa_imports (
                    id, tenant_id, original_filename, content_type, sha256, size_bytes,
                    storage_path, period, account_hints, warnings, text_excerpt,
                    created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id, sha256) do update set
                    original_filename = excluded.original_filename,
                    content_type = excluded.content_type,
                    size_bytes = excluded.size_bytes,
                    storage_path = excluded.storage_path,
                    period = excluded.period,
                    account_hints = excluded.account_hints,
                    warnings = excluded.warnings,
                    text_excerpt = excluded.text_excerpt,
                    updated_at = excluded.updated_at
                returning *, (xmax = 0) as inserted
                """,
                (
                    uuid4(),
                    tenant_id,
                    stored.original_filename,
                    stored.content_type,
                    stored.sha256,
                    stored.size_bytes,
                    str(stored.storage_path),
                    period,
                    Jsonb(account_hints),
                    Jsonb(warnings),
                    text_excerpt,
                    now,
                    now,
                ),
            )
            row = cursor.fetchone()
            inserted = bool(row.pop("inserted", False))
            return _serialize_bwa_import(row), inserted


def create_assignment_unit(
    tenant_id: str,
    code: str,
    label: str,
    kind: str,
    project_number: str | None,
    address_line: str | None,
    postal_code: str | None,
    city: str | None,
    external_id: str | None,
    revenue_relevant: bool,
    aliases: list[str],
    is_active: bool = True,
    order_number: str | None = None,
    customer_number: str | None = None,
    description: str | None = None,
    client_name: str | None = None,
    source_status: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    normalized_external_id = external_id.strip() if external_id else None
    normalized_project_number = project_number.strip() if project_number else None
    with _connect() as connection:
        with connection.cursor() as cursor:
            if normalized_external_id:
                cursor.execute(
                    """
                    update tenant_assignment_units
                    set
                        code = %s,
                        label = %s,
                        kind = %s,
                        project_number = %s,
                        order_number = %s,
                        customer_number = %s,
                        description = %s,
                        client_name = %s,
                        source_status = %s,
                        address_line = %s,
                        postal_code = %s,
                        city = %s,
                        revenue_relevant = %s,
                        aliases = %s,
                        is_active = %s,
                        updated_at = %s
                    where tenant_id = %s and external_id = %s
                    returning *
                    """,
                    (
                        code.strip(),
                        label.strip(),
                        kind,
                        project_number.strip() if project_number else None,
                        order_number.strip() if order_number else None,
                        customer_number.strip() if customer_number else None,
                        description.strip() if description else None,
                        client_name.strip() if client_name else None,
                        source_status.strip() if source_status else None,
                        address_line.strip() if address_line else None,
                        postal_code.strip() if postal_code else None,
                        city.strip() if city else None,
                        revenue_relevant,
                        Jsonb([alias.strip() for alias in aliases if alias.strip()]),
                        is_active,
                        now,
                        tenant_id,
                        normalized_external_id,
                    ),
                )
                existing = cursor.fetchone()
                if existing:
                    _delete_assignment_unit_project_duplicates(cursor, tenant_id, normalized_project_number, existing["id"])
                    return _serialize_assignment_unit(existing)

            if normalized_project_number:
                cursor.execute(
                    """
                    select id
                    from tenant_assignment_units
                    where tenant_id = %s and lower(coalesce(project_number, '')) = lower(%s)
                    order by (code = %s) desc, (external_id is not null) desc, updated_at desc
                    limit 1
                    """,
                    (tenant_id, normalized_project_number, code.strip()),
                )
                project_match = cursor.fetchone()
                if project_match:
                    cursor.execute(
                        """
                        update tenant_assignment_units
                        set
                            code = %s,
                            label = %s,
                            kind = %s,
                            project_number = %s,
                            order_number = %s,
                            customer_number = %s,
                            description = %s,
                            client_name = %s,
                            source_status = %s,
                            address_line = %s,
                            postal_code = %s,
                            city = %s,
                            external_id = %s,
                            revenue_relevant = %s,
                            aliases = %s,
                            is_active = %s,
                            updated_at = %s
                        where id = %s
                        returning *
                        """,
                        (
                            code.strip(),
                            label.strip(),
                            kind,
                            normalized_project_number,
                            order_number.strip() if order_number else None,
                            customer_number.strip() if customer_number else None,
                            description.strip() if description else None,
                            client_name.strip() if client_name else None,
                            source_status.strip() if source_status else None,
                            address_line.strip() if address_line else None,
                            postal_code.strip() if postal_code else None,
                            city.strip() if city else None,
                            normalized_external_id,
                            revenue_relevant,
                            Jsonb([alias.strip() for alias in aliases if alias.strip()]),
                            is_active,
                            now,
                            project_match["id"],
                        ),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        _delete_assignment_unit_project_duplicates(cursor, tenant_id, normalized_project_number, existing["id"])
                        return _serialize_assignment_unit(existing)

            cursor.execute(
                """
                insert into tenant_assignment_units (
                    id, tenant_id, code, label, kind, project_number, order_number, customer_number,
                    description, client_name, source_status, address_line, postal_code, city, external_id,
                    revenue_relevant, aliases, is_active, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id, code) do update set
                    label = excluded.label,
                    kind = excluded.kind,
                    project_number = excluded.project_number,
                    order_number = excluded.order_number,
                    customer_number = excluded.customer_number,
                    description = excluded.description,
                    client_name = excluded.client_name,
                    source_status = excluded.source_status,
                    address_line = excluded.address_line,
                    postal_code = excluded.postal_code,
                    city = excluded.city,
                    external_id = excluded.external_id,
                    revenue_relevant = excluded.revenue_relevant,
                    aliases = excluded.aliases,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                returning *
                """,
                (
                    uuid4(),
                    tenant_id,
                    code.strip(),
                    label.strip(),
                    kind,
                    normalized_project_number,
                    order_number.strip() if order_number else None,
                    customer_number.strip() if customer_number else None,
                    description.strip() if description else None,
                    client_name.strip() if client_name else None,
                    source_status.strip() if source_status else None,
                    address_line.strip() if address_line else None,
                    postal_code.strip() if postal_code else None,
                    city.strip() if city else None,
                    normalized_external_id,
                    revenue_relevant,
                    Jsonb([alias.strip() for alias in aliases if alias.strip()]),
                    is_active,
                    now,
                    now,
                ),
            )
            created = cursor.fetchone()
            if created:
                _delete_assignment_unit_project_duplicates(cursor, tenant_id, normalized_project_number, created["id"])
            return _serialize_assignment_unit(created)


def _delete_assignment_unit_project_duplicates(cursor, tenant_id: str, project_number: str | None, keep_id) -> None:
    if not project_number:
        return
    cursor.execute(
        """
        delete from tenant_assignment_units
        where tenant_id = %s
          and lower(coalesce(project_number, '')) = lower(%s)
          and id <> %s
        """,
        (tenant_id, project_number, keep_id),
    )


def update_assignment_unit(
    assignment_id: UUID,
    code: str,
    label: str,
    kind: str,
    project_number: str | None,
    address_line: str | None,
    postal_code: str | None,
    city: str | None,
    external_id: str | None,
    revenue_relevant: bool,
    aliases: list[str],
    is_active: bool,
    order_number: str | None = None,
    customer_number: str | None = None,
    description: str | None = None,
    client_name: str | None = None,
    source_status: str | None = None,
) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_assignment_units
                set
                    code = %s,
                    label = %s,
                    kind = %s,
                    project_number = %s,
                    order_number = %s,
                    customer_number = %s,
                    description = %s,
                    client_name = %s,
                    source_status = %s,
                    address_line = %s,
                    postal_code = %s,
                    city = %s,
                    external_id = %s,
                    revenue_relevant = %s,
                    aliases = %s,
                    is_active = %s,
                    updated_at = %s
                where id = %s
                returning *
                """,
                (
                    code.strip(),
                    label.strip(),
                    kind,
                    project_number.strip() if project_number else None,
                    order_number.strip() if order_number else None,
                    customer_number.strip() if customer_number else None,
                    description.strip() if description else None,
                    client_name.strip() if client_name else None,
                    source_status.strip() if source_status else None,
                    address_line.strip() if address_line else None,
                    postal_code.strip() if postal_code else None,
                    city.strip() if city else None,
                    external_id.strip() if external_id else None,
                    revenue_relevant,
                    Jsonb([alias.strip() for alias in aliases if alias.strip()]),
                    is_active,
                    datetime.now(UTC),
                    assignment_id,
                ),
            )
            row = cursor.fetchone()
            return _serialize_assignment_unit(row) if row else None


def find_assignment_unit_by_text(tenant_id: str, text: str | None) -> dict[str, Any] | None:
    match = find_assignment_unit_match_by_text(tenant_id, text)
    return match["assignment"] if match else None


def find_assignment_unit_match_by_text(tenant_id: str, text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    normalized_text = _normalize_match_text(text)
    best_match: tuple[int, dict[str, Any], list[str]] | None = None
    for assignment in list_assignment_units(tenant_id):
        if not assignment["is_active"]:
            continue
        score, reasons = _assignment_match_score(assignment, normalized_text)
        if score and (not best_match or score > best_match[0]):
            best_match = (score, assignment, reasons)
    if best_match and best_match[0] >= 80:
        return {
            "assignment": best_match[1],
            "score": best_match[0],
            "reasons": best_match[2],
        }
    return None


def _assignment_match_score(assignment: dict[str, Any], normalized_text: str) -> tuple[int, list[str]]:
    weighted_candidates = [
        ("Projektnummer", assignment.get("project_number"), 220),
        ("Auftragsnummer", assignment.get("order_number"), 180),
        ("Projektcode", assignment.get("code"), 170),
        ("Projektname", assignment.get("label"), 150),
        ("Projektadresse", _assignment_address_text(assignment), 150),
        ("Adresse", assignment.get("address_line"), 130),
        ("Kundennummer", assignment.get("customer_number"), 95),
        ("Externe ID", assignment.get("external_id"), 80),
        ("Bauherr", assignment.get("client_name"), 55),
        ("Beschreibung", assignment.get("description"), 45),
    ]
    weighted_candidates.extend(("Alias", alias, 120) for alias in assignment.get("aliases") or [])

    score = 0
    reasons: list[str] = []
    for label, candidate, weight in weighted_candidates:
        normalized_candidate = _normalize_assignment_candidate(candidate)
        if normalized_candidate and normalized_candidate in normalized_text:
            score += weight
            if label not in reasons:
                reasons.append(label)
    return score, reasons


def _normalize_assignment_candidate(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _normalize_match_text(value)
    if not normalized:
        return None
    # Avoid broad matches such as "Hamburg", "22175" or tiny fragments.
    if len(normalized) < 4:
        return None
    if re_search(r"^\d{5}$", normalized):
        return None
    if normalized in {"hamburg", "aktiv", "abgeschlossen", "bauvorhaben"}:
        return None
    return normalized


def get_assignment_unit_by_code(tenant_id: str, code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_assignment_units
                where tenant_id = %s and lower(code) = lower(%s)
                limit 1
                """,
                (tenant_id, code.strip()),
            )
            row = cursor.fetchone()
            if row:
                return _serialize_assignment_unit(row)
            try:
                cursor.execute(
                    """
                    select *
                    from tenant_assignment_units
                    where tenant_id = %s and lower(coalesce(project_number, '')) = lower(%s)
                    limit 1
                    """,
                    (tenant_id, code.strip()),
                )
            except psycopg.errors.UndefinedColumn:
                return None
            row = cursor.fetchone()
            if row:
                return _serialize_assignment_unit(row)
            cursor.execute(
                """
                select *
                from tenant_assignment_units
                where tenant_id = %s and lower(label) = lower(%s)
                limit 1
                """,
                (tenant_id, code.strip()),
            )
            row = cursor.fetchone()
            return _serialize_assignment_unit(row) if row else None


def list_supplier_rules(tenant_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_supplier_rules
                where tenant_id = %s
                order by is_active desc, supplier_name asc
                """,
                (tenant_id,),
            )
            return [_serialize_supplier_rule(row) for row in cursor.fetchall()]


def create_supplier_rule(
    tenant_id: str,
    match_text: str,
    supplier_name: str,
    customer_number: str | None = None,
    default_cost_category: str | list[str] | None = None,
    default_assignment_code: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_supplier_rules (
                    id, tenant_id, match_text, supplier_name, customer_number,
                    default_cost_category, default_assignment_code, is_active,
                    created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    uuid4(),
                    tenant_id,
                    match_text.strip(),
                    supplier_name.strip(),
                    customer_number.strip() if customer_number else None,
                    _normalize_cost_categories(default_cost_category),
                    default_assignment_code.strip() if default_assignment_code else None,
                    is_active,
                    now,
                    now,
                ),
            )
            return _serialize_supplier_rule(cursor.fetchone())


def update_supplier_rule(
    rule_id: UUID,
    match_text: str,
    supplier_name: str,
    customer_number: str | None,
    default_cost_category: str | list[str] | None,
    default_assignment_code: str | None,
    is_active: bool,
) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_supplier_rules
                set
                    match_text = %s,
                    supplier_name = %s,
                    customer_number = %s,
                    default_cost_category = %s,
                    default_assignment_code = %s,
                    is_active = %s,
                    updated_at = %s
                where id = %s
                returning *
                """,
                (
                    match_text.strip(),
                    supplier_name.strip(),
                    customer_number.strip() if customer_number else None,
                    _normalize_cost_categories(default_cost_category),
                    default_assignment_code.strip() if default_assignment_code else None,
                    is_active,
                    datetime.now(UTC),
                    rule_id,
                ),
            )
            row = cursor.fetchone()
            return _serialize_supplier_rule(row) if row else None


def list_accounting_rules(tenant_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select *
                from tenant_accounting_rules
                where tenant_id = %s
                order by is_active desc, supplier_match_text nulls last, cost_category nulls last, name asc
                """,
                (tenant_id,),
            )
            return [_serialize_accounting_rule(row) for row in cursor.fetchall()]


def create_accounting_rule(
    tenant_id: str,
    name: str,
    supplier_match_text: str | None,
    cost_category: str | None,
    debit_account: str,
    credit_account: str,
    tax_key: str | None,
    tax_rate: Decimal | None,
    discount_account: str | None,
    is_active: bool = True,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_accounting_rules (
                    id, tenant_id, name, supplier_match_text, cost_category,
                    debit_account, credit_account, tax_key, tax_rate, discount_account,
                    is_active, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    uuid4(),
                    tenant_id,
                    name.strip(),
                    supplier_match_text.strip() if supplier_match_text else None,
                    cost_category or None,
                    debit_account.strip(),
                    credit_account.strip(),
                    tax_key.strip() if tax_key else None,
                    tax_rate,
                    discount_account.strip() if discount_account else None,
                    is_active,
                    now,
                    now,
                ),
            )
            return _serialize_accounting_rule(cursor.fetchone())


def update_accounting_rule(
    rule_id: UUID,
    name: str,
    supplier_match_text: str | None,
    cost_category: str | None,
    debit_account: str,
    credit_account: str,
    tax_key: str | None,
    tax_rate: Decimal | None,
    discount_account: str | None,
    is_active: bool,
) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_accounting_rules
                set
                    name = %s,
                    supplier_match_text = %s,
                    cost_category = %s,
                    debit_account = %s,
                    credit_account = %s,
                    tax_key = %s,
                    tax_rate = %s,
                    discount_account = %s,
                    is_active = %s,
                    updated_at = %s
                where id = %s
                returning *
                """,
                (
                    name.strip(),
                    supplier_match_text.strip() if supplier_match_text else None,
                    cost_category or None,
                    debit_account.strip(),
                    credit_account.strip(),
                    tax_key.strip() if tax_key else None,
                    tax_rate,
                    discount_account.strip() if discount_account else None,
                    is_active,
                    datetime.now(UTC),
                    rule_id,
                ),
            )
            row = cursor.fetchone()
            return _serialize_accounting_rule(row) if row else None


def find_bwa_account_hints(
    tenant_id: str | None,
    supplier_name: str | None,
    cost_category: str | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if not tenant_id:
        return []

    supplier_text = _normalize_match_text(supplier_name or "")
    cost_terms = _bwa_cost_category_terms(cost_category)
    ranked_hints: list[tuple[int, int, dict[str, Any]]] = []
    for import_index, bwa_import in enumerate(list_bwa_imports(tenant_id)):
        for hint in bwa_import.get("account_hints") or []:
            score, reasons = _bwa_hint_score(hint, supplier_text, cost_terms)
            if score <= 0:
                continue
            ranked_hints.append(
                (
                    score,
                    -import_index,
                    {
                        "account": hint.get("account"),
                        "label": hint.get("label"),
                        "kind": hint.get("kind"),
                        "is_expense_account_candidate": _is_bwa_expense_account_candidate(hint.get("account")),
                        "source": hint.get("source") or "BWA",
                        "effect": hint.get("effect"),
                        "amounts": hint.get("amounts") or [],
                        "period": bwa_import.get("period"),
                        "filename": bwa_import.get("original_filename"),
                        "reasons": reasons,
                    },
                )
            )

    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for _, _, hint in sorted(ranked_hints, key=lambda item: (item[0], item[1]), reverse=True):
        key = (str(hint.get("account") or ""), str(hint.get("label") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(hint)
        if len(result) >= limit:
            break
    return result


def _best_bwa_expense_account_hint(hints: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((hint for hint in hints if hint.get("account") and hint.get("is_expense_account_candidate")), None)


def _bwa_cost_category_terms(cost_category: str | None) -> list[str]:
    terms_by_category = {
        "material": ["material", "waren", "wareneinkauf", "wareneingang", "baustoff"],
        "subcontractor": ["fremdleistung", "fremdarbeiten", "subunternehmer"],
        "fuel_vehicle": ["fahrzeug", "kfz", "tanken", "kraftstoff"],
        "software_subscription": ["software", "wartung", "lizenz", "abo"],
        "security_subscription": ["ueberwachung", "überwachung", "kamera", "abo"],
        "general_overhead": ["sonstige", "gemeinkosten", "raumkosten", "versicherung", "beitrag"],
    }
    return [_normalize_match_text(term) for term in terms_by_category.get(cost_category or "", [])]


def _is_bwa_expense_account_candidate(account: Any) -> bool:
    digits = sub(r"\D", "", str(account or ""))
    if not digits or len(digits) > 4:
        return False
    return digits[0] in {"3", "4", "5", "6"}


def _bwa_hint_score(hint: dict[str, Any], supplier_text: str, cost_terms: list[str]) -> tuple[int, list[str]]:
    hint_text = _normalize_match_text(" ".join(str(hint.get(key) or "") for key in ("label", "source", "effect")))
    is_expense_candidate = _is_bwa_expense_account_candidate(hint.get("account"))
    score = 0
    reasons: list[str] = []

    supplier_tokens = [token for token in supplier_text.split() if len(token) >= 4]
    supplier_hits = [token for token in supplier_tokens if token in hint_text]
    if supplier_hits:
        score += 3 + min(len(supplier_hits), 2)
        reasons.append("Lieferant in BWA-Kontozeile gefunden")

    if cost_terms and any(term in hint_text for term in cost_terms):
        score += 6 if is_expense_candidate else 2
        reasons.append("Kostenart passt zur BWA-Zeile")

    if hint.get("kind") == "account" and is_expense_candidate:
        score += 1
    return score, reasons


def find_accounting_rule(
    tenant_id: str | None,
    supplier_name: str | None,
    cost_category: str | None,
) -> dict[str, Any] | None:
    matches = find_accounting_rule_matches(tenant_id, supplier_name, cost_category)
    return matches[0] if len(matches) == 1 else None


def find_accounting_rule_matches(
    tenant_id: str | None,
    supplier_name: str | None,
    cost_category: str | None,
) -> list[dict[str, Any]]:
    if not tenant_id:
        return []
    supplier_text = _normalize_match_text(supplier_name or "")
    best_rank: tuple[int, int] | None = None
    best_rules: list[dict[str, Any]] = []
    for rule in list_accounting_rules(tenant_id):
        rank = _accounting_rule_rank(rule, supplier_text, cost_category)
        if rank is None:
            continue
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_rules = [rule]
        elif rank == best_rank:
            best_rules.append(rule)
    return best_rules


def _accounting_rule_rank(
    rule: dict[str, Any],
    supplier_text: str,
    cost_category: str | None,
) -> tuple[int, int] | None:
    if not rule["is_active"]:
        return None
    score = 0
    supplier_specificity = 0
    if rule["cost_category"]:
        if rule["cost_category"] != cost_category:
            return None
        score += 2
    if rule["supplier_match_text"]:
        normalized_match = _normalize_match_text(rule["supplier_match_text"])
        if normalized_match not in supplier_text:
            return None
        score += 4
        supplier_specificity = len(normalized_match)
    return score, supplier_specificity


def find_supplier_rule(tenant_id: str, *texts: str | None) -> dict[str, Any] | None:
    haystack = _normalize_match_text(" ".join(text or "" for text in texts))
    if not haystack:
        return None
    for rule in list_supplier_rules(tenant_id):
        if not rule["is_active"]:
            continue
        if _normalize_match_text(rule["match_text"]) in haystack:
            return rule
    return None


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
        "processing_job_id": str(row["processing_job_id"]) if row.get("processing_job_id") else None,
        "processing_started_at": _serialize_date(row.get("processing_started_at")),
        "duplicate_of": str(row["duplicate_of"]) if row["duplicate_of"] else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "extraction": _serialize_extraction(row["extraction"]) if row.get("extraction") else None,
        "booking_suggestions": [
            _serialize_booking_suggestion(suggestion)
            for suggestion in row.get("booking_suggestions", [])
        ],
        "payment_decision": _serialize_payment_decision(row["payment_decision"])
        if row.get("payment_decision")
        else None,
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
        "allowed_tenant_ids": row.get("allowed_tenant_ids") or [],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "last_login_at": _serialize_date(row["last_login_at"]),
    }
    if include_password_hash:
        user["password_hash"] = row["password_hash"]
    return user


def _normalize_allowed_tenant_ids(tenant_ids: list[str] | None, role: str) -> list[str]:
    if role == "admin":
        return ["*"]
    normalized: list[str] = []
    for tenant_id in tenant_ids or ["demo-mandant"]:
        clean = tenant_id.strip()
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized or ["demo-mandant"]


def _split_cost_categories(value: str | list[str] | None) -> list[str]:
    return list(
        dict.fromkeys(
            item
            for item in split_cost_category_values(value)
            if item in VALID_COST_CATEGORIES
        )
    )


def _normalize_cost_categories(value: str | list[str] | None) -> str | None:
    categories = _split_cost_categories(value)
    return ",".join(categories) if categories else None


def _normalize_accounting_framework(value: str | None) -> str:
    normalized = (value or "SKR03").strip().upper()
    return normalized if normalized in VALID_ACCOUNTING_FRAMEWORKS else "SKR03"


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _serialize_tenant_profile(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "display_name": row["display_name"],
        "industry": row["industry"],
        "assignment_label_singular": row["assignment_label_singular"],
        "assignment_label_plural": row["assignment_label_plural"],
        "assignment_code_label": row["assignment_code_label"],
        "assignment_code_prefix": row["assignment_code_prefix"],
        "default_assignment_kind": row["default_assignment_kind"],
        "allow_multiple_assignments": row["allow_multiple_assignments"],
        "accounting_framework": _normalize_accounting_framework(row.get("accounting_framework")),
        "default_credit_account": row.get("default_credit_account"),
        "default_tax_key": row.get("default_tax_key"),
        "default_tax_rate": str(row["default_tax_rate"]) if row.get("default_tax_rate") is not None else None,
        "default_discount_account": row.get("default_discount_account"),
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_assignment_unit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "code": row["code"],
        "label": row["label"],
        "kind": row["kind"],
        "project_number": row.get("project_number"),
        "order_number": row.get("order_number"),
        "customer_number": row.get("customer_number"),
        "description": row.get("description"),
        "client_name": row.get("client_name"),
        "source_status": row.get("source_status"),
        "address_line": row.get("address_line"),
        "postal_code": row.get("postal_code"),
        "city": row.get("city"),
        "external_id": row.get("external_id"),
        "address": _assignment_address_text(row),
        "revenue_relevant": row["revenue_relevant"],
        "aliases": row["aliases"] or [],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _assignment_address_text(row: dict[str, Any]) -> str | None:
    line = row.get("address_line")
    postal_code = row.get("postal_code")
    city = row.get("city")
    city_line = " ".join(part for part in [postal_code, city] if part)
    parts = [part for part in [line, city_line] if part]
    return ", ".join(parts) if parts else None


def _serialize_supplier_rule(row: dict[str, Any]) -> dict[str, Any]:
    cost_categories = _split_cost_categories(row["default_cost_category"])
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "match_text": row["match_text"],
        "supplier_name": row["supplier_name"],
        "customer_number": row["customer_number"],
        "default_cost_category": row["default_cost_category"],
        "default_cost_categories": cost_categories,
        "default_assignment_code": row["default_assignment_code"],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_accounting_rule(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "supplier_match_text": row["supplier_match_text"],
        "cost_category": row["cost_category"],
        "debit_account": row["debit_account"],
        "credit_account": row["credit_account"],
        "tax_key": row["tax_key"],
        "tax_rate": str(row["tax_rate"]) if row["tax_rate"] is not None else None,
        "discount_account": row["discount_account"],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_bwa_import(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "original_filename": row["original_filename"],
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "storage_path": row["storage_path"],
        "period": row["period"],
        "account_hints": row.get("account_hints") or [],
        "warnings": row.get("warnings") or [],
        "text_excerpt": row.get("text_excerpt") or "",
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _list_document_bulk_job_items(job_id: UUID) -> list[dict[str, Any]]:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    i.*,
                    d.original_filename,
                    d.normalized_filename,
                    d.status as document_status
                from document_bulk_job_items i
                left join documents d on d.id = i.document_id
                where i.job_id = %s
                order by i.created_at, i.id
                """,
                (job_id,),
            )
            return [_serialize_bulk_job_item(row) for row in cursor.fetchall()]


def _serialize_bulk_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "action": row["action"],
        "status": row["status"],
        "requested_total": row["requested_total"],
        "processed_count": row["processed_count"],
        "succeeded_count": row["succeeded_count"],
        "failed_count": row["failed_count"],
        "error": row["error"],
        "created_by": row["created_by"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
        "started_at": _serialize_date(row["started_at"]),
        "finished_at": _serialize_date(row["finished_at"]),
    }


def _serialize_bulk_job_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "job_id": str(row["job_id"]),
        "document_id": str(row["document_id"]),
        "status": row["status"],
        "error": row["error"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
        "document": {
            "id": str(row["document_id"]),
            "original_filename": row.get("original_filename"),
            "normalized_filename": row.get("normalized_filename"),
            "status": row.get("document_status"),
        }
        if row.get("original_filename")
        else None,
    }


def _serialize_booking_suggestion(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "tenant_id": row["tenant_id"],
        "line_no": row["line_no"],
        "booking_type": row["booking_type"],
        "cost_category": row["cost_category"],
        "assignment_code": row["assignment_code"],
        "assignment_project_number": row.get("assignment_project_number"),
        "assignment_kind": row["assignment_kind"],
        "description": row["description"],
        "net_amount": str(row["net_amount"]) if row["net_amount"] is not None else None,
        "tax_amount": str(row["tax_amount"]) if row["tax_amount"] is not None else None,
        "gross_amount": str(row["gross_amount"]) if row["gross_amount"] is not None else None,
        "currency": row["currency"],
        "status": row["status"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_payment_decision(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "tenant_id": row["tenant_id"],
        "payment_type": row["payment_type"],
        "label": row["label"],
        "due_date": _serialize_date(row["due_date"]),
        "amount": str(row["amount"]) if row["amount"] is not None else None,
        "discount_base": str(row["discount_base"]) if row["discount_base"] is not None else None,
        "discount_percent": str(row["discount_percent"]) if row["discount_percent"] is not None else None,
        "discount_amount": str(row["discount_amount"]) if row["discount_amount"] is not None else None,
        "currency": row["currency"],
        "status": row["status"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _normalize_match_text(value: str) -> str:
    normalized = value.casefold()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, replacement in replacements.items():
        normalized = normalized.replace(source, replacement)
    return " ".join(normalized.split())


def _serialize_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe_value(value) for key, value in extraction.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    return value


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _money_string(value: Any) -> str | None:
    amount = _decimal_or_none(value)
    if amount is None:
        return None
    return str(_round_money(amount))
