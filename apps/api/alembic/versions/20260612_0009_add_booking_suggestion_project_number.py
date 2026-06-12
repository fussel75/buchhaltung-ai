"""add project number to booking suggestions

Revision ID: 20260612_0009
Revises: 20260610_0008
Create Date: 2026-06-12
"""

from alembic import op


revision = "20260612_0009"
down_revision = "20260610_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table document_booking_suggestions add column if not exists assignment_project_number text")
    op.execute(
        """
        update document_booking_suggestions suggestion
        set assignment_project_number = assignment.project_number
        from tenant_assignment_units assignment
        where suggestion.tenant_id = assignment.tenant_id
          and lower(trim(suggestion.assignment_code)) = lower(trim(assignment.code))
          and suggestion.assignment_project_number is null
          and assignment.project_number is not null
        """
    )


def downgrade() -> None:
    op.execute("alter table document_booking_suggestions drop column if exists assignment_project_number")
