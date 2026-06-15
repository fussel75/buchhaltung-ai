"""add assignment source status

Revision ID: 20260615_0011
Revises: 20260615_0010
Create Date: 2026-06-15
"""

from alembic import op


revision = "20260615_0011"
down_revision = "20260615_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table tenant_assignment_units add column if not exists source_status text")


def downgrade() -> None:
    op.execute("alter table tenant_assignment_units drop column if exists source_status")
