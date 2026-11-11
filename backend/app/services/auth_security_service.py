"""Database-backed persistence for revoked JWTs and auth brute-force rate limits."""

import hashlib
import time
from typing import Dict, List, Optional, Tuple
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.core.security import (
    _LOGIN_ATTEMPTS,
    _RESET_ATTEMPTS,
    _REVOKED_TOKENS,
    extract_token_revocation_info,
    is_token_revoked as _is_token_revoked_mem,
    record_failed_login as _record_failed_login_mem,
    record_password_reset_attempt as _record_reset_mem,
    reset_login_attempts as _reset_login_mem,
)
from backend.app.models.security import AuthAttempt, RevokedToken


def _make_safe_key(prefix: str, raw_value: str) -> str:
    """Build a bounded-length DB key (<= 255 chars), hashing oversized inputs."""
    full = f"{prefix}:{raw_value}"
    if len(full) <= 255:
        return full
    digest = hashlib.sha256(raw_value.encode("utf-8", errors="ignore")).hexdigest()[:32]
    head = raw_value[: 255 - len(prefix) - len(digest) - 2]
    return f"{prefix}:{head}:{digest}"


def _build_login_keys(ip: Optional[str], login: str) -> List[Tuple[str, str]]:
    """Return list of (mem_key, db_key) pairs for login brute-force tracking."""
    login_norm = login.lower().strip()
    mem_ip = f"ip:{ip or 'unknown'}:{login_norm}"
    mem_acct = f"acct:{login_norm}"
    return [
        (mem_ip, _make_safe_key("login", mem_ip)),
        (mem_acct, _make_safe_key("login", mem_acct)),
    ]


def _build_reset_keys(ip: Optional[str], identifier: str) -> List[Tuple[str, str]]:
    """Return list of (mem_key, db_key) pairs for password-reset rate limiting."""
    ident_norm = identifier.lower().strip()
    mem_ip = f"reset:ip:{ip or 'unknown'}"
    mem_id = f"reset:id:{ident_norm}"
    return [
        (mem_ip, _make_safe_key("reset", mem_ip)),
        (mem_id, _make_safe_key("reset", mem_id)),
    ]


async def _check_rate_limit_db(
    db: AsyncSession,
    mem_store: Dict[str, Tuple[int, float, float]],
    key_pairs: List[Tuple[str, str]],
    window_sec: float,
) -> Optional[int]:
    """Check whether any key is currently locked out in DB or memory cache."""
    now = time.time()
    db_keys = [db_key for _, db_key in key_pairs]
    mem_by_db = {db_key: mem_key for mem_key, db_key in key_pairs}

    res = await db.execute(select(AuthAttempt).where(AuthAttempt.attempt_key.in_(db_keys)))
    rows = res.scalars().all()

    max_remaining = 0
    stale_keys: List[str] = []

    for row in rows:
        mem_key = mem_by_db.get(row.attempt_key)
        if row.locked_until > now:
            rem = max(1, int(row.locked_until - now))
            if rem > max_remaining:
                max_remaining = rem
            if mem_key:
                mem_store[mem_key] = (row.failed_count, row.first_attempt_at, row.locked_until)
        elif row.expires_at <= now or (now - row.first_attempt_at > window_sec and row.locked_until <= now):
            stale_keys.append(row.attempt_key)
            if mem_key:
                mem_store.pop(mem_key, None)

    if stale_keys:
        await db.execute(delete(AuthAttempt).where(AuthAttempt.attempt_key.in_(stale_keys)))

    return max_remaining if max_remaining > 0 else None


async def _record_attempt_db(
    db: AsyncSession,
    mem_store: Dict[str, Tuple[int, float, float]],
    key_pairs: List[Tuple[str, str]],
    max_attempts: int,
    window_sec: float,
    lockout_sec: float,
) -> Optional[int]:
    """Increment brute-force counters atomically in memory and DB (flushed to session)."""
    now = time.time()
    db_keys = [db_key for _, db_key in key_pairs]
    res = await db.execute(select(AuthAttempt).where(AuthAttempt.attempt_key.in_(db_keys)))
    existing: Dict[str, AuthAttempt] = {r.attempt_key: r for r in res.scalars().all()}

    blocked_sec: Optional[int] = None

    for mem_key, db_key in key_pairs:
        row = existing.get(db_key)
        is_expired = (
            row is None
            or (now - row.first_attempt_at > window_sec and row.locked_until <= now)
            or (row.locked_until > 0 and row.locked_until <= now)
        )
        if is_expired:
            count = 1
            first_ts = now
            locked_until = 0.0
        else:
            count = int(row.failed_count) + 1
            first_ts = float(row.first_attempt_at)
            locked_until = float(row.locked_until)

        if count >= max_attempts:
            locked_until = max(locked_until, now + lockout_sec)
            rem = max(1, int(locked_until - now))
            blocked_sec = max(blocked_sec or 0, rem)

        expires_at = max(first_ts + window_sec, locked_until)
        if row is None:
            try:
                async with db.begin_nested():
                    db.add(AuthAttempt(
                        attempt_key=db_key,
                        failed_count=count,
                        first_attempt_at=first_ts,
                        locked_until=locked_until,
                        expires_at=expires_at,
                    ))
                    await db.flush()
            except IntegrityError:
                raced = await db.get(AuthAttempt, db_key)
                if raced is not None:
                    raced.failed_count = max(int(raced.failed_count) + 1, count)
                    raced.locked_until = max(float(raced.locked_until), locked_until)
                    raced.expires_at = max(float(raced.expires_at), expires_at)
        else:
            row.failed_count = count
            row.first_attempt_at = first_ts
            row.locked_until = locked_until
            row.expires_at = expires_at

        mem_store[mem_key] = (count, first_ts, locked_until)

    await db.flush()
    return blocked_sec


async def check_login_rate_limit_db(db: AsyncSession, ip: Optional[str], login: str) -> Optional[int]:
    """Persistent login lockout check (survives worker/container restarts)."""
    return await _check_rate_limit_db(
        db=db,
        mem_store=_LOGIN_ATTEMPTS,
        key_pairs=_build_login_keys(ip, login),
        window_sec=float(settings.LOGIN_LOCKOUT_SECONDS),
    )


async def record_failed_login_db(db: AsyncSession, ip: Optional[str], login: str) -> Optional[int]:
    """Record a failed login attempt in both DB and in-memory cache."""
    lockout = float(settings.LOGIN_LOCKOUT_SECONDS)
    res = await _record_attempt_db(
        db=db,
        mem_store=_LOGIN_ATTEMPTS,
        key_pairs=_build_login_keys(ip, login),
        max_attempts=int(settings.LOGIN_MAX_ATTEMPTS),
        window_sec=lockout,
        lockout_sec=lockout,
    )
    return res


async def reset_login_attempts_db(db: AsyncSession, ip: Optional[str], login: str) -> None:
    """Clear login failure counters on successful login from DB and memory."""
    _reset_login_mem(ip, login)
    db_keys = [db_key for _, db_key in _build_login_keys(ip, login)]
    await db.execute(delete(AuthAttempt).where(AuthAttempt.attempt_key.in_(db_keys)))
    await db.flush()


async def check_password_reset_rate_limit_db(
    db: AsyncSession, ip: Optional[str], identifier: str
) -> Optional[int]:
    """Persistent password reset lockout check (max 3 requests per 15 min)."""
    return await _check_rate_limit_db(
        db=db,
        mem_store=_RESET_ATTEMPTS,
        key_pairs=_build_reset_keys(ip, identifier),
        window_sec=900.0,
    )


async def record_password_reset_attempt_db(
    db: AsyncSession,
    ip: Optional[str],
    identifier: str,
    max_attempts: int = 3,
    window_sec: float = 900.0,
) -> Optional[int]:
    """Record a password reset request attempt in both DB and in-memory cache."""
    return await _record_attempt_db(
        db=db,
        mem_store=_RESET_ATTEMPTS,
        key_pairs=_build_reset_keys(ip, identifier),
        max_attempts=max_attempts,
        window_sec=window_sec,
        lockout_sec=window_sec,
    )


async def revoke_access_token_db(db: AsyncSession, token: str) -> None:
    """Persist JWT token revocation to DB and memory cache."""
    info = extract_token_revocation_info(token)
    if not info:
        return
    token_hash, exp_ts = info
    _REVOKED_TOKENS[token_hash] = exp_ts

    existing = await db.get(RevokedToken, token_hash)
    if existing is None:
        try:
            async with db.begin_nested():
                db.add(RevokedToken(token_hash=token_hash, expires_at=exp_ts))
                await db.flush()
        except IntegrityError:
            raced = await db.get(RevokedToken, token_hash)
            if raced is not None:
                raced.expires_at = max(float(raced.expires_at), exp_ts)
    else:
        existing.expires_at = max(float(existing.expires_at), exp_ts)
    await db.flush()


async def is_token_revoked_db(db: AsyncSession, token: str) -> bool:
    """Check token revocation via in-memory fast path first, falling back to DB."""
    if not token:
        return False
    if _is_token_revoked_mem(token):
        return True

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = await db.get(RevokedToken, token_hash)
    if row is None:
        return False

    now_ts = time.time()
    if float(row.expires_at) <= now_ts:
        await db.delete(row)
        await db.flush()
        return False

    _REVOKED_TOKENS[token_hash] = float(row.expires_at)
    return True


async def cleanup_expired_security_state_db(db: AsyncSession) -> None:
    """Prune expired revoked tokens / lockouts on startup and warm memory cache."""
    now_ts = time.time()
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now_ts))
    await db.execute(delete(AuthAttempt).where(AuthAttempt.expires_at <= now_ts))

    active_tokens = (
        await db.execute(select(RevokedToken).where(RevokedToken.expires_at > now_ts))
    ).scalars().all()
    for tok in active_tokens:
        _REVOKED_TOKENS[tok.token_hash] = float(tok.expires_at)

    await db.commit()
