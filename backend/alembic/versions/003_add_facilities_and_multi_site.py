"""Add facilities table and multi-site support

Revision ID: 003_add_facilities_and_multi_site
Revises: 002_add_duration_seconds
Create Date: 2026-10-05 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '003_add_facilities_and_multi_site'
down_revision = '002_add_duration_seconds'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create facilities table
    try:
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
    except Exception:
        pass

    # 2. Add facility_id to related tables
    for table_name in ['generators', 'fuel_stocks', 'fuel_receipts', 'fuel_transfers', 'users']:
        try:
            op.add_column(
                table_name,
                sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id', ondelete='SET NULL'), nullable=True)
            )
        except Exception:
            pass


def downgrade() -> None:
    for table_name in ['users', 'fuel_transfers', 'fuel_receipts', 'fuel_stocks', 'generators']:
        try:
            op.drop_column(table_name, 'facility_id')
        except Exception:
            pass
    try:
        op.drop_table('facilities')
    except Exception:
        pass
