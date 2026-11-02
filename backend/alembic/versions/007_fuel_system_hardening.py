"""Harden fuel system: add is_active to FuelStock, idempotency_key to FuelReceipt and FuelTransfer, precision Numeric fields

Revision ID: 007_fuel_system_hardening
Revises: 006_fuel_provider
Create Date: 2026-11-02 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '007_fuel_system_hardening'
down_revision = '006_fuel_provider'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    # 1. fuel_stocks
    if 'fuel_stocks' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_stocks')]
        with op.batch_alter_table('fuel_stocks') as batch_op:
            if 'is_active' not in cols:
                batch_op.add_column(
                    sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1')
                )
            batch_op.alter_column(
                'current_balance_l',
                existing_type=sa.Float(),
                type_=sa.Numeric(10, 3),
                existing_nullable=False
            )

    # 2. fuel_receipts
    if 'fuel_receipts' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_receipts')]
        with op.batch_alter_table('fuel_receipts') as batch_op:
            if 'idempotency_key' not in cols:
                batch_op.add_column(
                    sa.Column('idempotency_key', sa.String(64), nullable=True)
                )
                batch_op.create_index('ix_fuel_receipts_idempotency_key', ['idempotency_key'], unique=True)
            batch_op.alter_column('liters', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('cost_total', existing_type=sa.Float(), type_=sa.Numeric(12, 2), existing_nullable=False)
            batch_op.alter_column('price_per_liter', existing_type=sa.Float(), type_=sa.Numeric(12, 2), existing_nullable=False)

    # 3. fuel_transfers
    if 'fuel_transfers' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_transfers')]
        with op.batch_alter_table('fuel_transfers') as batch_op:
            if 'idempotency_key' not in cols:
                batch_op.add_column(
                    sa.Column('idempotency_key', sa.String(64), nullable=True)
                )
                batch_op.create_index('ix_fuel_transfers_idempotency_key', ['idempotency_key'], unique=True)
            batch_op.alter_column('liters', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('source_balance_before', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('source_balance_after', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('tank_balance_before', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('tank_balance_after', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)

    # 4. generators
    if 'generators' in tables:
        with op.batch_alter_table('generators') as batch_op:
            batch_op.alter_column('tank_capacity_l', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)
            batch_op.alter_column('fuel_tank_level_l', existing_type=sa.Float(), type_=sa.Numeric(10, 3), existing_nullable=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'fuel_stocks' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_stocks')]
        if 'is_active' in cols:
            with op.batch_alter_table('fuel_stocks') as batch_op:
                batch_op.drop_column('is_active')

    if 'fuel_receipts' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_receipts')]
        if 'idempotency_key' in cols:
            with op.batch_alter_table('fuel_receipts') as batch_op:
                batch_op.drop_index('ix_fuel_receipts_idempotency_key')
                batch_op.drop_column('idempotency_key')

    if 'fuel_transfers' in tables:
        cols = [c['name'] for c in insp.get_columns('fuel_transfers')]
        if 'idempotency_key' in cols:
            with op.batch_alter_table('fuel_transfers') as batch_op:
                batch_op.drop_index('ix_fuel_transfers_idempotency_key')
                batch_op.drop_column('idempotency_key')
