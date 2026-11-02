"""Harden generator subsystem: archiving, idempotency_key, partial unique index for active runs

Revision ID: 009_generator_hardening
Revises: 008_ensure_schema_integrity
Create Date: 2026-11-02 22:55:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '009_generator_hardening'
down_revision = '008_ensure_schema_integrity'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    if conn.dialect.name == "postgresql":
        pg_statements = [
            "ALTER TABLE generators ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE generators ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
            "ALTER TABLE generator_runs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_idempotency_key ON generator_runs(idempotency_key)",
            # Normalize any duplicate RUNNING sessions before creating the partial unique index
            """
            UPDATE generator_runs
            SET status = 'COMPLETED',
                end_time = COALESCE(end_time, start_time),
                end_hours = COALESCE(end_hours, start_hours),
                duration_seconds = COALESCE(duration_seconds, 0),
                duration_hours = COALESCE(duration_hours, 0.0),
                calculated_consumption_l = COALESCE(calculated_consumption_l, 0.0)
            WHERE status = 'RUNNING'
              AND id NOT IN (
                  SELECT MAX(id) FROM generator_runs WHERE status = 'RUNNING' GROUP BY generator_id
              )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_one_active ON generator_runs(generator_id) WHERE status = 'RUNNING'",
        ]
        for stmt in pg_statements:
            conn.execute(sa.text(stmt))
    else:
        insp = sa.inspect(conn)
        tables = insp.get_table_names()

        if 'generators' in tables:
            cols = [c['name'] for c in insp.get_columns('generators')]
            with op.batch_alter_table('generators') as batch_op:
                if 'is_active' not in cols:
                    batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
                if 'archived_at' not in cols:
                    batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))

        if 'generator_runs' in tables:
            cols = [c['name'] for c in insp.get_columns('generator_runs')]
            with op.batch_alter_table('generator_runs') as batch_op:
                if 'idempotency_key' not in cols:
                    batch_op.add_column(sa.Column('idempotency_key', sa.String(64), nullable=True))
                    batch_op.create_index('ix_generator_runs_idempotency_key', ['idempotency_key'], unique=True)

            conn.execute(sa.text(
                "UPDATE generator_runs SET status = 'COMPLETED', end_time = COALESCE(end_time, start_time) "
                "WHERE status = 'RUNNING' AND id NOT IN "
                "(SELECT MAX(id) FROM generator_runs WHERE status = 'RUNNING' GROUP BY generator_id)"
            ))
            conn.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_generator_runs_one_active ON generator_runs(generator_id) WHERE status = 'RUNNING'"
            ))


def downgrade() -> None:
    pass
