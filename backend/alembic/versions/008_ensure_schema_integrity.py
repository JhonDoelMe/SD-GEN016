"""Ensure full schema integrity and missing columns on PostgreSQL and SQLite

Revision ID: 008_ensure_schema_integrity
Revises: 007_fuel_system_hardening
Create Date: 2026-11-02 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '008_ensure_schema_integrity'
down_revision = '007_fuel_system_hardening'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    if conn.dialect.name == "postgresql":
        # Direct PostgreSQL DDL ensuring all required columns and indexes exist (one command per prepared statement for asyncpg)
        pg_statements = [
            "ALTER TABLE fuel_stocks ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE fuel_stocks ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE CASCADE",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS fuel_provider VARCHAR(50) DEFAULT 'wog'",
            "ALTER TABLE fuel_receipts ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
            "ALTER TABLE fuel_transfers ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL",
            "ALTER TABLE fuel_transfers ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
            "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS default_fuel_provider VARCHAR(30) NOT NULL DEFAULT 'wog'",
            "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS yasno_enabled BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS yasno_region_id INTEGER DEFAULT 3",
            "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS yasno_dso_id INTEGER DEFAULT 301",
            "ALTER TABLE facilities ADD COLUMN IF NOT EXISTS yasno_group VARCHAR(10)",
            "ALTER TABLE system_adjustments ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL",
            "ALTER TABLE system_adjustments ADD COLUMN IF NOT EXISTS target_name VARCHAR(200)",
            "ALTER TABLE generators ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS facility_id INTEGER REFERENCES facilities(id) ON DELETE SET NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_fuel_receipts_idempotency_key ON fuel_receipts(idempotency_key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_fuel_transfers_idempotency_key ON fuel_transfers(idempotency_key)",
            "ALTER TABLE fuel_stocks ALTER COLUMN current_balance_l TYPE NUMERIC(10, 3) USING current_balance_l::numeric(10, 3)",
            "ALTER TABLE fuel_receipts ALTER COLUMN liters TYPE NUMERIC(10, 3) USING liters::numeric(10, 3)",
            "ALTER TABLE fuel_receipts ALTER COLUMN cost_total TYPE NUMERIC(12, 2) USING cost_total::numeric(12, 2)",
            "ALTER TABLE fuel_receipts ALTER COLUMN price_per_liter TYPE NUMERIC(12, 2) USING price_per_liter::numeric(12, 2)",
            "ALTER TABLE fuel_transfers ALTER COLUMN liters TYPE NUMERIC(10, 3) USING liters::numeric(10, 3)",
            "ALTER TABLE fuel_transfers ALTER COLUMN source_balance_before TYPE NUMERIC(10, 3) USING source_balance_before::numeric(10, 3)",
            "ALTER TABLE fuel_transfers ALTER COLUMN source_balance_after TYPE NUMERIC(10, 3) USING source_balance_after::numeric(10, 3)",
            "ALTER TABLE fuel_transfers ALTER COLUMN tank_balance_before TYPE NUMERIC(10, 3) USING tank_balance_before::numeric(10, 3)",
            "ALTER TABLE fuel_transfers ALTER COLUMN tank_balance_after TYPE NUMERIC(10, 3) USING tank_balance_after::numeric(10, 3)",
        ]
        for stmt in pg_statements:
            conn.execute(sa.text(stmt))
    else:
        # SQLite dialect handling
        insp = sa.inspect(conn)
        tables = insp.get_table_names()

        if 'fuel_stocks' in tables:
            cols = [c['name'] for c in insp.get_columns('fuel_stocks')]
            with op.batch_alter_table('fuel_stocks') as batch_op:
                if 'is_active' not in cols:
                    batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
                if 'facility_id' not in cols:
                    batch_op.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))

        if 'fuel_receipts' in tables:
            cols = [c['name'] for c in insp.get_columns('fuel_receipts')]
            with op.batch_alter_table('fuel_receipts') as batch_op:
                if 'idempotency_key' not in cols:
                    batch_op.add_column(sa.Column('idempotency_key', sa.String(64), nullable=True))
                    batch_op.create_index('ix_fuel_receipts_idempotency_key', ['idempotency_key'], unique=True)
                if 'fuel_provider' not in cols:
                    batch_op.add_column(sa.Column('fuel_provider', sa.String(50), nullable=True, server_default='wog'))
                if 'facility_id' not in cols:
                    batch_op.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))

        if 'fuel_transfers' in tables:
            cols = [c['name'] for c in insp.get_columns('fuel_transfers')]
            with op.batch_alter_table('fuel_transfers') as batch_op:
                if 'idempotency_key' not in cols:
                    batch_op.add_column(sa.Column('idempotency_key', sa.String(64), nullable=True))
                    batch_op.create_index('ix_fuel_transfers_idempotency_key', ['idempotency_key'], unique=True)
                if 'facility_id' not in cols:
                    batch_op.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))

        if 'facilities' in tables:
            cols = [c['name'] for c in insp.get_columns('facilities')]
            with op.batch_alter_table('facilities') as batch_op:
                if 'default_fuel_provider' not in cols:
                    batch_op.add_column(sa.Column('default_fuel_provider', sa.String(30), nullable=False, server_default='wog'))


def downgrade() -> None:
    pass
