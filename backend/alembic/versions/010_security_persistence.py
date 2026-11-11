"""Persist revoked JWT tokens and auth brute-force lockouts in PostgreSQL/SQLite.

Revision ID: 010_security_persistence
Revises: 009_generator_hardening
Create Date: 2026-11-11 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '010_security_persistence'
down_revision = '009_generator_hardening'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if hasattr(conn, "info_cache"):
        conn.info_cache.clear()

    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'revoked_tokens' not in tables:
        op.create_table(
            'revoked_tokens',
            sa.Column('token_hash', sa.String(length=64), primary_key=True, nullable=False),
            sa.Column('expires_at', sa.Float(), nullable=False),
            sa.Column('revoked_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at'], unique=False)

    if 'auth_attempts' not in tables:
        op.create_table(
            'auth_attempts',
            sa.Column('attempt_key', sa.String(length=255), primary_key=True, nullable=False),
            sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('first_attempt_at', sa.Float(), nullable=False),
            sa.Column('locked_until', sa.Float(), nullable=False, server_default='0'),
            sa.Column('expires_at', sa.Float(), nullable=False),
        )
        op.create_index('ix_auth_attempts_locked_until', 'auth_attempts', ['locked_until'], unique=False)
        op.create_index('ix_auth_attempts_expires_at', 'auth_attempts', ['expires_at'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'auth_attempts' in tables:
        op.drop_index('ix_auth_attempts_expires_at', table_name='auth_attempts')
        op.drop_index('ix_auth_attempts_locked_until', table_name='auth_attempts')
        op.drop_table('auth_attempts')

    if 'revoked_tokens' in tables:
        op.drop_index('ix_revoked_tokens_expires_at', table_name='revoked_tokens')
        op.drop_table('revoked_tokens')
