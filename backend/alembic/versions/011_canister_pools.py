"""Add facility canister pools and canister transaction log tables.

Revision ID: 011_canister_pools
Revises: 010_security_persistence
Create Date: 2026-11-11 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '011_canister_pools'
down_revision = '010_security_persistence'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'canister_pools' not in tables:
        op.create_table(
            'canister_pools',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id', ondelete='CASCADE'), nullable=False),
            sa.Column('stock_id', sa.Integer(), sa.ForeignKey('fuel_stocks.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('fuel_type', sa.String(length=50), nullable=False),
            sa.Column('canister_volume_l', sa.Numeric(8, 2), nullable=False, server_default='20.0'),
            sa.Column('total_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('full_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('empty_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('away_refill_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('reserve_liters', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('TRUE') if conn.dialect.name == 'postgresql' else '1'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_canister_pools_facility_id', 'canister_pools', ['facility_id'], unique=False)
        op.create_index('ix_canister_pools_stock_id', 'canister_pools', ['stock_id'], unique=False)

    if 'canister_transactions' not in tables:
        op.create_table(
            'canister_transactions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id', ondelete='CASCADE'), nullable=False),
            sa.Column('pool_id', sa.Integer(), sa.ForeignKey('canister_pools.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('operation', sa.String(length=40), nullable=False),
            sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('liters_delta', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('used_from_reserve_l', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('full_before', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('full_after', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('empty_before', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('empty_after', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('away_before', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('away_after', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('reserve_before', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('reserve_after', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('related_transfer_id', sa.Integer(), sa.ForeignKey('fuel_transfers.id', ondelete='SET NULL'), nullable=True),
            sa.Column('related_receipt_id', sa.Integer(), sa.ForeignKey('fuel_receipts.id', ondelete='SET NULL'), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_canister_transactions_facility_id', 'canister_transactions', ['facility_id'], unique=False)
        op.create_index('ix_canister_transactions_pool_id', 'canister_transactions', ['pool_id'], unique=False)
        op.create_index('ix_canister_transactions_operation', 'canister_transactions', ['operation'], unique=False)
        op.create_index('ix_canister_transactions_created_at', 'canister_transactions', ['created_at'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'canister_transactions' in tables:
        for idx in ('ix_canister_transactions_created_at', 'ix_canister_transactions_operation', 'ix_canister_transactions_pool_id', 'ix_canister_transactions_facility_id'):
            op.drop_index(idx, table_name='canister_transactions')
        op.drop_table('canister_transactions')

    if 'canister_pools' in tables:
        for idx in ('ix_canister_pools_stock_id', 'ix_canister_pools_facility_id'):
            op.drop_index(idx, table_name='canister_pools')
        op.drop_table('canister_pools')
