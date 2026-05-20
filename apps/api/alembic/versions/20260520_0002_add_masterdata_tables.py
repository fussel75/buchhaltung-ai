"""add tenant masterdata tables

Revision ID: 20260520_0002
Revises: 20260507_0001
Create Date: 2026-05-20
"""

from alembic import op

revision = "20260520_0002"
down_revision = "20260507_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists tenant_assignment_units (
            id uuid primary key,
            tenant_id text not null,
            code text not null,
            label text not null,
            kind text not null,
            revenue_relevant boolean not null default false,
            aliases jsonb not null default '[]'::jsonb,
            is_active boolean not null default true,
            created_at timestamptz not null,
            updated_at timestamptz not null,
            unique (tenant_id, code)
        )
        """
    )
    op.execute(
        """
        create index if not exists tenant_assignment_units_tenant_idx
        on tenant_assignment_units (tenant_id, is_active, kind)
        """
    )
    op.execute(
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
    op.execute(
        """
        create index if not exists tenant_supplier_rules_tenant_idx
        on tenant_supplier_rules (tenant_id, is_active)
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists tenant_supplier_rules")
    op.execute("drop table if exists tenant_assignment_units")
