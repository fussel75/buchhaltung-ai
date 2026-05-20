from datetime import UTC, date, datetime
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
                create table if not exists document_booking_suggestions (
                    id uuid primary key,
                    document_id uuid not null references documents(id) on delete cascade,
                    tenant_id text not null,
                    line_no integer not null,
                    booking_type text not null,
                    cost_category text,
                    assignment_code text,
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
                    created_at timestamptz not null,
                    updated_at timestamptz not null
                )
                """
            )
            cursor.execute(
                """
                create table if not exists tenant_assignment_units (
                    id uuid primary key,
                    tenant_id text not null,
                    code text not null,
                    label text not null,
                    kind text not null,
                    project_number text,
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


def list_documents(tenant_id: str) -> list[dict[str, Any]]:
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
                    ) as booking_suggestions
                from documents d
                left join document_extractions e on e.document_id = d.id
                where d.tenant_id = %s
                order by d.created_at desc
                limit 100
                """,
                (tenant_id,),
            )
            return [_serialize_document(row) for row in cursor.fetchall()]


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
                    ) as booking_suggestions
                from documents d
                left join document_extractions e on e.document_id = d.id
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
                    ) as booking_suggestions
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
            cursor.execute("delete from document_booking_suggestions where document_id = %s", (document_id,))
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


def approve_document_review(document_id: UUID, actor: str = "system") -> dict[str, Any] | None:
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
                cursor.execute(
                    """
                    insert into document_booking_suggestions (
                        id, document_id, tenant_id, line_no, booking_type, cost_category,
                        assignment_code, assignment_kind, description, net_amount, tax_amount,
                        gross_amount, currency, status, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'suggested', %s, %s)
                    """,
                    (
                        uuid4(),
                        document_id,
                        document["tenant_id"],
                        line_no,
                        suggestion["booking_type"],
                        suggestion.get("cost_category"),
                        suggestion.get("assignment_code"),
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
        details={"suggestion_count": len(suggestions)},
    )
    return get_document(document_id)


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
    if existing:
        return
    create_assignment_unit(
        tenant_id="demo-mandant",
        code="Wewe20",
        label="Weseler Weg 20",
        kind="construction_project",
        project_number="25-00008",
        revenue_relevant=True,
        aliases=["Weseler Weg 20", "Weseler Weg 20, 22045 Hamburg"],
    )
    create_supplier_rule(
        tenant_id="demo-mandant",
        match_text="Holz Junge",
        supplier_name="Holz Junge GmbH",
        customer_number="109324",
        default_cost_category="material",
        default_assignment_code="Wewe20",
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
    },
    "fitness_studio": {
        "assignment_label_singular": "Standort",
        "assignment_label_plural": "Standorte",
        "assignment_code_label": "Standort",
        "assignment_code_prefix": None,
        "default_assignment_kind": "location",
        "allow_multiple_assignments": False,
    },
    "container_transport": {
        "assignment_label_singular": "Bauvorhaben / Stellplatz",
        "assignment_label_plural": "Bauvorhaben / Stellplaetze",
        "assignment_code_label": "Bauvorhaben / Stellplatz",
        "assignment_code_prefix": None,
        "default_assignment_kind": "construction_or_dropoff_site",
        "allow_multiple_assignments": True,
    },
    "general": {
        "assignment_label_singular": "Kostenstelle",
        "assignment_label_plural": "Kostenstellen",
        "assignment_code_label": "Kostenstelle",
        "assignment_code_prefix": None,
        "default_assignment_kind": "cost_object",
        "allow_multiple_assignments": True,
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
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_profiles (
                    tenant_id, display_name, industry, assignment_label_singular,
                    assignment_label_plural, assignment_code_label, assignment_code_prefix,
                    default_assignment_kind, allow_multiple_assignments, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id) do update set
                    display_name = excluded.display_name,
                    industry = excluded.industry,
                    assignment_label_singular = excluded.assignment_label_singular,
                    assignment_label_plural = excluded.assignment_label_plural,
                    assignment_code_label = excluded.assignment_code_label,
                    assignment_code_prefix = excluded.assignment_code_prefix,
                    default_assignment_kind = excluded.default_assignment_kind,
                    allow_multiple_assignments = excluded.allow_multiple_assignments,
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


def create_assignment_unit(
    tenant_id: str,
    code: str,
    label: str,
    kind: str,
    project_number: str | None,
    revenue_relevant: bool,
    aliases: list[str],
    is_active: bool = True,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenant_assignment_units (
                    id, tenant_id, code, label, kind, project_number, revenue_relevant,
                    aliases, is_active, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (tenant_id, code) do update set
                    label = excluded.label,
                    kind = excluded.kind,
                    project_number = excluded.project_number,
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
                    project_number.strip() if project_number else None,
                    revenue_relevant,
                    Jsonb([alias.strip() for alias in aliases if alias.strip()]),
                    is_active,
                    now,
                    now,
                ),
            )
            return _serialize_assignment_unit(cursor.fetchone())


def update_assignment_unit(
    assignment_id: UUID,
    label: str,
    kind: str,
    project_number: str | None,
    revenue_relevant: bool,
    aliases: list[str],
    is_active: bool,
) -> dict[str, Any] | None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update tenant_assignment_units
                set
                    label = %s,
                    kind = %s,
                    project_number = %s,
                    revenue_relevant = %s,
                    aliases = %s,
                    is_active = %s,
                    updated_at = %s
                where id = %s
                returning *
                """,
                (
                    label.strip(),
                    kind,
                    project_number.strip() if project_number else None,
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
    if not text:
        return None
    normalized_text = _normalize_match_text(text)
    for assignment in list_assignment_units(tenant_id):
        if not assignment["is_active"]:
            continue
        candidates = [assignment["code"], assignment["label"], assignment.get("project_number"), *assignment["aliases"]]
        if any(_normalize_match_text(candidate) in normalized_text for candidate in candidates if candidate):
            return assignment
    return None


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
    default_cost_category: str | None = None,
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
                    default_cost_category or None,
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
    default_cost_category: str | None,
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
                    default_cost_category or None,
                    default_assignment_code.strip() if default_assignment_code else None,
                    is_active,
                    datetime.now(UTC),
                    rule_id,
                ),
            )
            row = cursor.fetchone()
            return _serialize_supplier_rule(row) if row else None


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
        "duplicate_of": str(row["duplicate_of"]) if row["duplicate_of"] else None,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "extraction": _serialize_extraction(row["extraction"]) if row.get("extraction") else None,
        "booking_suggestions": [
            _serialize_booking_suggestion(suggestion)
            for suggestion in row.get("booking_suggestions", [])
        ],
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
        "revenue_relevant": row["revenue_relevant"],
        "aliases": row["aliases"] or [],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
    }


def _serialize_supplier_rule(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "match_text": row["match_text"],
        "supplier_name": row["supplier_name"],
        "customer_number": row["customer_number"],
        "default_cost_category": row["default_cost_category"],
        "default_assignment_code": row["default_assignment_code"],
        "is_active": row["is_active"],
        "created_at": _serialize_date(row["created_at"]),
        "updated_at": _serialize_date(row["updated_at"]),
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


def _normalize_match_text(value: str) -> str:
    return " ".join(value.casefold().split())


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


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))
