"""Add fuel_measurements table for controlled fuel consumption measurement & inventory mode.

Revision ID: 013_fuel_measurements
Revises: 012_offline_idempotency
Create Date: 2026-11-12 01:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '013_fuel_measurements'
down_revision = '012_offline_idempotency'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'fuel_measurements' not in tables:
        op.create_table(
            'fuel_measurements',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('facility_id', sa.Integer(), sa.ForeignKey('facilities.id', ondelete='CASCADE'), nullable=False),
            sa.Column('generator_id', sa.Integer(), sa.ForeignKey('generators.id', ondelete='CASCADE'), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='MEASURING'),
            sa.Column('started_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('start_operating_hours', sa.Float(), nullable=False),
            sa.Column('start_tank_level_l', sa.Numeric(10, 3), nullable=False),
            sa.Column('old_nominal_consumption_l_per_h', sa.Float(), nullable=False),
            sa.Column('min_liters_threshold', sa.Numeric(10, 3), nullable=False, server_default='100.0'),
            sa.Column('added_during_measurement_l', sa.Numeric(10, 3), nullable=False, server_default='0.0'),
            sa.Column('start_snapshot_json', sa.Text(), nullable=True),
            sa.Column('tank_emptied_at', sa.DateTime(), nullable=True),
            sa.Column('tank_emptied_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('end_operating_hours', sa.Float(), nullable=True),
            sa.Column('total_fuel_consumed_l', sa.Numeric(10, 3), nullable=True),
            sa.Column('total_hours_elapsed', sa.Float(), nullable=True),
            sa.Column('calculated_consumption_l_per_h', sa.Float(), nullable=True),
            sa.Column('inventory_entered_at', sa.DateTime(), nullable=True),
            sa.Column('commission_members_json', sa.Text(), nullable=True),
            sa.Column('inventory_fact_json', sa.Text(), nullable=True),
            sa.Column('statement_number', sa.String(length=40), nullable=True),
            sa.Column('document_generated_at', sa.DateTime(), nullable=True),
            sa.Column('document_downloaded_at', sa.DateTime(), nullable=True),
            sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('approved_at', sa.DateTime(), nullable=True),
            sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('cancelled_at', sa.DateTime(), nullable=True),
            sa.Column('cancel_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_fuel_measurements_facility_id', 'fuel_measurements', ['facility_id'], unique=False)
        op.create_index('ix_fuel_measurements_generator_id', 'fuel_measurements', ['generator_id'], unique=False)
        op.create_index('ix_fuel_measurements_status', 'fuel_measurements', ['status'], unique=False)
        op.create_index('ix_fuel_measurements_started_at', 'fuel_measurements', ['started_at'], unique=False)
        op.create_index('ix_fuel_measurements_statement_number', 'fuel_measurements', ['statement_number'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'fuel_measurements' in tables:
        for idx in (
            'ix_fuel_measurements_statement_number',
            'ix_fuel_measurements_started_at',
            'ix_fuel_measurements_status',
            'ix_fuel_measurements_generator_id',
            'ix_fuel_measurements_facility_id',
        ):
            op.drop_index(idx, table_name='fuel_measurements')
        op.drop_table('fuel_measurements')
