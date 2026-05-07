"""add auth tables

Revision ID: 20260507_0001
Revises:
Create Date: 2026-05-07
"""

from alembic import op

revision = "20260507_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists users (
            id uuid primary key,
            email text not null unique,
            password_hash text not null,
            display_name text not null,
            role text not null check (role in ('admin', 'user')),
            is_active boolean not null default true,
            created_at timestamptz not null,
            last_login_at timestamptz
        )
        """
    )
    op.execute("create unique index if not exists users_email_idx on users (lower(email))")
    op.execute(
        """
        create table if not exists sessions (
            id text primary key,
            user_id uuid not null references users(id) on delete cascade,
            expires_at timestamptz not null,
            created_at timestamptz not null
        )
        """
    )
    op.execute("create index if not exists sessions_expires_at_idx on sessions (expires_at)")


def downgrade() -> None:
    op.execute("drop table if exists sessions")
    op.execute("drop table if exists users")
