"""Add default_fuel_provider to facilities and fuel_provider to fuel_receipts

Revision ID: 006_fuel_provider
Revises: 005_adjustments_fix
Create Date: 2026-11-02 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '006_fuel_provider'
down_revision = '005_adjustments_fix'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    # 1. Add default_fuel_provider to facilities
    if 'facilities' in tables:
        cols = [c['name'] for c in insp.get_columns('facilities')]
        if 'default_fuel_provider' not in cols:
            with op.batch_alter_table('facilities') as batch_op:
                batch_op.add_column(
                    sa.Column('default_fuel_provider', sa.String(length=30), nullable=False, server_default='wog')
                )

    # 2. Add fuel_provider to fuel_receipts
    if 'fuel_receipts' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_receipts')]
        if 'fuel_provider' not in cols:
            with op.batch_alter_table('fuel_receipts') as batch_op:
                batch_op.add_column(
                    sa.Column('fuel_provider', sa.String(length=50), nullable=True, server_default='wog')
                )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'fuel_receipts' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_receipts')]
        if 'fuel_provider' in cols:
            with op.batch_alter_table('fuel_receipts') as batch_op:
                batch_op.drop_column('fuel_provider')

    if 'facilities' in tables:
        cols = [c['name'] for c in insp.get_columns('facilities')]
        if 'default_fuel_provider' in cols:
            with op.batch_alter_table('facilities') as batch_op:
                batch_op.drop_column('default_fuel_provider')
