"""Add idempotency_records table for PWA offline mutation deduplication.

Revision ID: 012_offline_idempotency
Revises: 011_canister_pools
Create Date: 2026-11-12 00:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '012_offline_idempotency'
down_revision = '011_canister_pools'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'idempotency_records' not in tables:
        op.create_table(
            'idempotency_records',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('endpoint', sa.String(length=120), nullable=False),
            sa.Column('idempotency_key', sa.String(length=64), nullable=False),
            sa.Column('request_hash', sa.String(length=64), nullable=False),
            sa.Column('status_code', sa.Integer(), nullable=False, server_default='200'),
            sa.Column('response_json', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('user_id', 'endpoint', 'idempotency_key', name='uq_idempotency_user_ep_key'),
        )
        op.create_index('ix_idempotency_records_user_id', 'idempotency_records', ['user_id'], unique=False)
        op.create_index('ix_idempotency_records_created_at', 'idempotency_records', ['created_at'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'idempotency_records' in tables:
        op.drop_index('ix_idempotency_records_created_at', table_name='idempotency_records')
        op.drop_index('ix_idempotency_records_user_id', table_name='idempotency_records')
        op.drop_table('idempotency_records')
