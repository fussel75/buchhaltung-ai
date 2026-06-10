"""add accounting defaults to tenant profiles

Revision ID: 20260610_0008
Revises: 20260608_0007
Create Date: 2026-06-10
"""

from alembic import op


revision = "20260610_0008"
down_revision = "20260608_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table tenant_profiles add column if not exists default_credit_account text")
    op.execute("alter table tenant_profiles add column if not exists default_tax_key text")
    op.execute("alter table tenant_profiles add column if not exists default_tax_rate numeric(5, 2)")
    op.execute("alter table tenant_profiles add column if not exists default_discount_account text")


def downgrade() -> None:
    op.execute("alter table tenant_profiles drop column if exists default_discount_account")
    op.execute("alter table tenant_profiles drop column if exists default_tax_rate")
    op.execute("alter table tenant_profiles drop column if exists default_tax_key")
    op.execute("alter table tenant_profiles drop column if exists default_credit_account")
