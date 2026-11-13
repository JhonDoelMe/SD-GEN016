"""Add avatar_path column to users table.

Revision ID: 014_user_avatar
Revises: 013_fuel_measurements
Create Date: 2026-11-13 21:12:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '014_user_avatar'
down_revision = '013_fuel_measurements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_path VARCHAR(255)"))
        return

    insp = sa.inspect(conn)
    columns = {col["name"] for col in insp.get_columns("users")}
    if "avatar_path" not in columns:
        op.add_column("users", sa.Column("avatar_path", sa.String(length=255), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS avatar_path"))
        return

    insp = sa.inspect(conn)
    columns = {col["name"] for col in insp.get_columns("users")}
    if "avatar_path" in columns:
        op.drop_column("users", "avatar_path")
