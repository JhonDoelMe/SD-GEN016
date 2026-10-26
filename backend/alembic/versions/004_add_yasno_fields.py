"""Add YASNO blackout schedules integration fields to facilities

Revision ID: 004_add_yasno_fields
Revises: 003_multisite
Create Date: 2026-10-26 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '004_add_yasno_fields'
down_revision = '003_multisite'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'facilities' in tables:
        cols = [c['name'] for c in insp.get_columns('facilities')]
        with op.batch_alter_table('facilities') as batch_op:
            if 'yasno_enabled' not in cols:
                batch_op.add_column(
                    sa.Column('yasno_enabled', sa.Boolean(), server_default=sa.false(), nullable=False)
                )
            if 'yasno_region_id' not in cols:
                batch_op.add_column(
                    sa.Column('yasno_region_id', sa.Integer(), server_default='3', nullable=True)
                )
            if 'yasno_dso_id' not in cols:
                batch_op.add_column(
                    sa.Column('yasno_dso_id', sa.Integer(), server_default='301', nullable=True)
                )
            if 'yasno_group' not in cols:
                batch_op.add_column(
                    sa.Column('yasno_group', sa.String(length=10), nullable=True)
                )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'facilities' in tables:
        cols = [c['name'] for c in insp.get_columns('facilities')]
        with op.batch_alter_table('facilities') as batch_op:
            for col in ['yasno_group', 'yasno_dso_id', 'yasno_region_id', 'yasno_enabled']:
                if col in cols:
                    batch_op.drop_column(col)
