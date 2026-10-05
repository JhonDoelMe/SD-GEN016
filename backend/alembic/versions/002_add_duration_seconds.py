"""Add duration_seconds to generator_runs

Revision ID: 002_add_duration_seconds
Revises: 001_initial_schema
Create Date: 2026-10-05 14:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '002_add_duration_seconds'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.add_column('generator_runs', sa.Column('duration_seconds', sa.Integer(), nullable=True))
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_column('generator_runs', 'duration_seconds')
    except Exception:
        pass
