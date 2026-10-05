"""Add facilities table and multi-site support

Revision ID: 003_multisite
Revises: 002_add_duration_seconds
Create Date: 2026-10-05 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '003_multisite'
down_revision = '002_add_duration_seconds'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    # 1. Create facilities table
    if 'facilities' not in tables:
        op.create_table(
            'facilities',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(length=150), nullable=False, unique=True),
            sa.Column('address', sa.String(length=255), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('timezone', sa.String(length=50), nullable=False, server_default='Europe/Kyiv'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False)
        )

    # 2. Add facility_id to related tables
    for table_name in ['generators', 'fuel_stocks', 'fuel_receipts', 'fuel_transfers', 'users']:
        if table_name in tables:
            cols = [c['name'] for c in insp.get_columns(table_name)]
            if 'facility_id' not in cols:
                with op.batch_alter_table(table_name) as batch_op:
                    batch_op.add_column(
                        sa.Column('facility_id', sa.Integer(), nullable=True)
                    )
                    batch_op.create_foreign_key(
                        f'fk_{table_name}_facilities',
                        'facilities',
                        ['facility_id'],
                        ['id'],
                        ondelete='SET NULL'
                    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    for table_name in ['users', 'fuel_transfers', 'fuel_receipts', 'fuel_stocks', 'generators']:
        if table_name in tables:
            cols = [c['name'] for c in insp.get_columns(table_name)]
            if 'facility_id' in cols:
                with op.batch_alter_table(table_name) as batch_op:
                    try:
                        batch_op.drop_constraint(f'fk_{table_name}_facilities', type_='foreignkey')
                    except Exception:
                        pass
                    batch_op.drop_column('facility_id')

    if 'facilities' in tables:
        op.drop_table('facilities')
