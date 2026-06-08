"""add bwa imports

Revision ID: 20260608_0007
Revises: 20260602_0006
Create Date: 2026-06-08 00:00:00.000000
"""

from alembic import op


revision = "20260608_0007"
down_revision = "20260602_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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
    op.execute(
        """
        create index if not exists tenant_bwa_imports_tenant_created_idx
            on tenant_bwa_imports (tenant_id, created_at desc)
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists tenant_bwa_imports")
