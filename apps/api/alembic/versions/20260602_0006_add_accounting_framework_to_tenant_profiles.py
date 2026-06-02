"""add accounting framework to tenant profiles

Revision ID: 20260602_0006
Revises: 20260520_0005
Create Date: 2026-06-02
"""

from alembic import op

revision = "20260602_0006"
down_revision = "20260520_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table tenant_profiles add column if not exists accounting_framework text not null default 'SKR03'")


def downgrade() -> None:
    op.execute("alter table tenant_profiles drop column if exists accounting_framework")
