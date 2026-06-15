"""add assignment project metadata

Revision ID: 20260615_0010
Revises: 20260612_0009
Create Date: 2026-06-15
"""

from alembic import op


revision = "20260615_0010"
down_revision = "20260612_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table tenant_assignment_units add column if not exists order_number text")
    op.execute("alter table tenant_assignment_units add column if not exists customer_number text")
    op.execute("alter table tenant_assignment_units add column if not exists description text")
    op.execute("alter table tenant_assignment_units add column if not exists client_name text")


def downgrade() -> None:
    op.execute("alter table tenant_assignment_units drop column if exists client_name")
    op.execute("alter table tenant_assignment_units drop column if exists description")
    op.execute("alter table tenant_assignment_units drop column if exists customer_number")
    op.execute("alter table tenant_assignment_units drop column if exists order_number")
