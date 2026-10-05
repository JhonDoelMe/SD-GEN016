"""Initial schema for SD-GEN016 Service Desk

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()
    if 'users' in existing_tables:
        # Schema already initialized, skip creating tables
        return

    # 1. Users, Roles, Permissions
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('login', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_superadmin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_login', 'users', ['login'], unique=True)
    op.create_index('ix_users_id', 'users', ['id'], unique=False)

    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_roles_name', 'roles', ['name'], unique=True)
    op.create_index('ix_roles_id', 'roles', ['id'], unique=False)

    op.create_table(
        'permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_permissions_code', 'permissions', ['code'], unique=True)
    op.create_index('ix_permissions_id', 'permissions', ['id'], unique=False)

    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
    )

    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )

    # 2. Generator, Schedules, Runs
    op.create_table(
        'generators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('manufacturer', sa.String(length=100), nullable=False),
        sa.Column('serial_number', sa.String(length=100), nullable=False),
        sa.Column('rated_power_kw', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('tank_capacity_l', sa.Float(), nullable=False, server_default='25.0'),
        sa.Column('fuel_type', sa.String(length=50), nullable=False, server_default='А-95'),
        sa.Column('nominal_consumption_l_per_h', sa.Float(), nullable=False, server_default='2.2'),
        sa.Column('current_operating_hours', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('fuel_tank_level_l', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='STOPPED'),
        sa.Column('is_configured', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='Europe/Kyiv'),
        sa.Column('extra_params_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generators_id', 'generators', ['id'], unique=False)

    op.create_table(
        'generator_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False, server_default='-1'),
        sa.Column('start_time', sa.String(length=10), nullable=False, server_default='08:00'),
        sa.Column('end_time', sa.String(length=10), nullable=False, server_default='20:00'),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='Europe/Kyiv'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generator_schedules_id', 'generator_schedules', ['id'], unique=False)

    op.create_table(
        'generator_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('start_hours', sa.Float(), nullable=False),
        sa.Column('end_hours', sa.Float(), nullable=True),
        sa.Column('duration_hours', sa.Float(), nullable=True),
        sa.Column('start_fuel_level_l', sa.Float(), nullable=True),
        sa.Column('end_fuel_level_l', sa.Float(), nullable=True),
        sa.Column('calculated_consumption_l', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='RUNNING'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generator_runs_id', 'generator_runs', ['id'], unique=False)

    # 3. Fuel
    op.create_table(
        'fuel_stocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('fuel_type', sa.String(length=50), nullable=False, server_default='А-95'),
        sa.Column('current_balance_l', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fuel_stocks_id', 'fuel_stocks', ['id'], unique=False)

    op.create_table(
        'fuel_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stock_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fuel_type', sa.String(length=50), nullable=False),
        sa.Column('liters', sa.Float(), nullable=False),
        sa.Column('cost_total', sa.Float(), nullable=False),
        sa.Column('price_per_liter', sa.Float(), nullable=False),
        sa.Column('driver_name', sa.String(length=255), nullable=False),
        sa.Column('receipt_number', sa.String(length=100), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['stock_id'], ['fuel_stocks.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fuel_receipts_id', 'fuel_receipts', ['id'], unique=False)

    op.create_table(
        'fuel_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stock_id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('liters', sa.Float(), nullable=False),
        sa.Column('source_balance_before', sa.Float(), nullable=False),
        sa.Column('source_balance_after', sa.Float(), nullable=False),
        sa.Column('tank_balance_before', sa.Float(), nullable=False),
        sa.Column('tank_balance_after', sa.Float(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id']),
        sa.ForeignKeyConstraint(['stock_id'], ['fuel_stocks.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fuel_transfers_id', 'fuel_transfers', ['id'], unique=False)

    # 4. Maintenance
    op.create_table(
        'maintenance_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('interval_hours', sa.Float(), nullable=False, server_default='300.0'),
        sa.Column('last_performed_hours', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('next_due_hours', sa.Float(), nullable=False, server_default='300.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_maintenance_schedules_id', 'maintenance_schedules', ['id'], unique=False)

    op.create_table(
        'maintenance_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('maintenance_type', sa.String(length=50), nullable=False),
        sa.Column('operating_hours', sa.Float(), nullable=False),
        sa.Column('work_description', sa.Text(), nullable=False),
        sa.Column('consumables_used', sa.Text(), nullable=True),
        sa.Column('cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('photo_urls', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_maintenance_records_id', 'maintenance_records', ['id'], unique=False)

    # 5. Faults
    op.create_table(
        'faults',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generator_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('operating_hours', sa.Float(), nullable=False),
        sa.Column('priority', sa.String(length=50), nullable=False, server_default='MEDIUM'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='NEW'),
        sa.Column('photo_urls', sa.Text(), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['generator_id'], ['generators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_faults_id', 'faults', ['id'], unique=False)

    # 6. Audit & System Adjustments
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_entity_type', 'audit_logs', ['entity_type'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_id', 'audit_logs', ['id'], unique=False)

    op.create_table(
        'system_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=False),
        sa.Column('new_value', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_system_adjustments_created_at', 'system_adjustments', ['created_at'], unique=False)
    op.create_index('ix_system_adjustments_id', 'system_adjustments', ['id'], unique=False)

    # 7. System Settings
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value_json', sa.Text(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )
    op.create_index('ix_system_settings_key', 'system_settings', ['key'], unique=False)


def downgrade() -> None:
    op.drop_table('system_settings')
    op.drop_table('system_adjustments')
    op.drop_table('audit_logs')
    op.drop_table('faults')
    op.drop_table('maintenance_records')
    op.drop_table('maintenance_schedules')
    op.drop_table('fuel_transfers')
    op.drop_table('fuel_receipts')
    op.drop_table('fuel_stocks')
    op.drop_table('generator_runs')
    op.drop_table('generator_schedules')
    op.drop_table('generators')
    op.drop_table('role_permissions')
    op.drop_table('user_roles')
    op.drop_table('permissions')
    op.drop_table('roles')
    op.drop_table('users')
