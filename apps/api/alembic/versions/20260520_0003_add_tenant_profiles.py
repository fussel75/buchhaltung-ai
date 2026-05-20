"""add tenant profiles

Revision ID: 20260520_0003
Revises: 20260520_0002
Create Date: 2026-05-20
"""

from alembic import op

revision = "20260520_0003"
down_revision = "20260520_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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


def downgrade() -> None:
    op.execute("drop table if exists tenant_profiles")
