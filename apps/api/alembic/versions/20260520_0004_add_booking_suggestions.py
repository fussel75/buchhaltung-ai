"""add document booking suggestions

Revision ID: 20260520_0004
Revises: 20260520_0003
Create Date: 2026-05-20
"""

from alembic import op

revision = "20260520_0004"
down_revision = "20260520_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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
    op.execute(
        """
        create index if not exists document_booking_suggestions_document_idx
        on document_booking_suggestions (document_id, line_no)
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists document_booking_suggestions")
