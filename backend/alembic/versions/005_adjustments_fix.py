"""Add adjustments facility columns and fix maintenance schedule anomaly

Revision ID: 005_adjustments_fix
Revises: 004_add_yasno_fields
Create Date: 2026-11-02 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '005_adjustments_fix'
down_revision = '004_add_yasno_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    # 1. Ensure default facility record exists
    if 'facilities' in tables:
        res = conn.execute(sa.text("SELECT COUNT(*) FROM facilities")).scalar()
        if res == 0:
            bool_val = "FALSE" if conn.dialect.name == "postgresql" else "0"
            conn.execute(sa.text(
                f"INSERT INTO facilities (name, address, description, timezone, yasno_enabled, yasno_region_id, yasno_dso_id, created_at, updated_at) "
                f"VALUES ('Основний об''єкт', 'Головна локація', 'Базовий об''єкт генератора', 'Europe/Kyiv', {bool_val}, 3, 301, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))

    # 2. Add facility_id and target_name to system_adjustments
    if 'system_adjustments' in tables:
        cols = [c['name'] for c in insp.get_columns('system_adjustments')]
        with op.batch_alter_table('system_adjustments') as batch_op:
            if 'facility_id' not in cols:
                batch_op.add_column(sa.Column('facility_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    'fk_system_adjustments_facilities',
                    'facilities',
                    ['facility_id'],
                    ['id'],
                    ondelete='SET NULL'
                )
            if 'target_name' not in cols:
                batch_op.add_column(sa.Column('target_name', sa.String(length=200), nullable=True))

    # 3. Correct legacy maintenance schedule anomaly (MAIN-02)
    if 'maintenance_schedules' in tables:
        conn.execute(sa.text(
            "UPDATE maintenance_schedules SET last_performed_hours = 0.0, next_due_hours = interval_hours "
            "WHERE (last_performed_hours = 235.0 AND next_due_hours = 535.0) "
            "OR (last_performed_hours = 235.0 AND next_due_hours > 300.0)"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'system_adjustments' in tables:
        cols = [c['name'] for c in insp.get_columns('system_adjustments')]
        with op.batch_alter_table('system_adjustments') as batch_op:
            if 'facility_id' in cols:
                try:
                    batch_op.drop_constraint('fk_system_adjustments_facilities', type_='foreignkey')
                except Exception:
                    pass
                batch_op.drop_column('facility_id')
            if 'target_name' in cols:
                batch_op.drop_column('target_name')
