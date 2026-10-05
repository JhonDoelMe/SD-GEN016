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
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('generator_runs')]
    if 'duration_seconds' not in cols:
        with op.batch_alter_table('generator_runs') as batch_op:
            batch_op.add_column(sa.Column('duration_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('generator_runs')]
    if 'duration_seconds' in cols:
        with op.batch_alter_table('generator_runs') as batch_op:
            batch_op.drop_column('duration_seconds')
