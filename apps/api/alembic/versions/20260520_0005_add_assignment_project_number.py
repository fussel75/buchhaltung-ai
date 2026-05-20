"""add assignment project number

Revision ID: 20260520_0005
Revises: 20260520_0004
Create Date: 2026-05-20
"""

from alembic import op

revision = "20260520_0005"
down_revision = "20260520_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table tenant_assignment_units add column if not exists project_number text")
    op.execute(
        """
        update tenant_assignment_units
        set project_number = '25-00008'
        where tenant_id = 'demo-mandant'
          and code = 'Wewe20'
          and project_number is null
        """
    )


def downgrade() -> None:
    op.execute("alter table tenant_assignment_units drop column if exists project_number")
