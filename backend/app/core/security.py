import datetime
import hashlib
import hmac
import time
from typing import Optional, Dict, Any, Tuple
import bcrypt
import jwt
from backend.app.config import settings

ALGORITHM = "HS256"

# Precomputed bcrypt hash used for constant-time comparison when user does not exist (Timing Attack defense)
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"dummy_constant_time_defense_password", bcrypt.gensalt(rounds=12)).decode("utf-8")

# Brute-force protection store: key -> (failed_count, first_attempt_ts, locked_until_ts)
_LOGIN_ATTEMPTS: Dict[str, Tuple[int, float, float]] = {}

# Revoked tokens store: token_hash -> exp_timestamp
_REVOKED_TOKENS: Dict[str, float] = {}


def _cleanup_login_attempts(now: float) -> None:
    if len(_LOGIN_ATTEMPTS) > 1000:
        expired_keys = [
            k for k, (_, first_ts, locked_until) in _LOGIN_ATTEMPTS.items()
            if (locked_until > 0 and locked_until <= now) or (locked_until == 0 and now - first_ts > settings.LOGIN_LOCKOUT_SECONDS)
        ]
        for k in expired_keys:
            _LOGIN_ATTEMPTS.pop(k, None)


def _cleanup_revoked_tokens(now_ts: float) -> None:
    if len(_REVOKED_TOKENS) > 1000:
        expired = [k for k, exp in _REVOKED_TOKENS.items() if exp <= now_ts]
        for k in expired:
            _REVOKED_TOKENS.pop(k, None)


def get_password_hash(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


def verify_dummy_password(plain_password: str) -> None:
    """Constant-time dummy password verification to prevent username enumeration via timing attacks."""
    verify_password(plain_password, DUMMY_PASSWORD_HASH)


def compute_password_signature(password_hash: str) -> str:
    """Computes a short HMAC signature of the user's password hash for JWT session invalidation on password change."""
    return hmac.new(
        settings.APP_SECRET_KEY.encode("utf-8"),
        (password_hash or "").encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:16]


def check_login_rate_limit(ip: Optional[str], login: str) -> Optional[int]:
    """
    Returns remaining lockout seconds if blocked (by IP+login or global login), or None if allowed.
    """
    now = time.monotonic()
    _cleanup_login_attempts(now)
    login_norm = login.lower().strip()
    keys_to_check = [
        f"ip:{ip or 'unknown'}:{login_norm}",
        f"acct:{login_norm}",
    ]
    max_remaining = 0
    for key in keys_to_check:
        entry = _LOGIN_ATTEMPTS.get(key)
        if not entry:
            continue
        count, first_ts, locked_until = entry
        if locked_until > now:
            rem = max(1, int(locked_until - now))
            if rem > max_remaining:
                max_remaining = rem
        elif now - first_ts > settings.LOGIN_LOCKOUT_SECONDS:
            _LOGIN_ATTEMPTS.pop(key, None)

    return max_remaining if max_remaining > 0 else None


def _increment_attempt_key(key: str, now: float, threshold: int) -> Optional[int]:
    entry = _LOGIN_ATTEMPTS.get(key)
    if not entry or (now - entry[1] > settings.LOGIN_LOCKOUT_SECONDS) or (entry[2] > 0 and entry[2] <= now):
        count = 1
        first_ts = now
    else:
        count = entry[0] + 1
        first_ts = entry[1]

    locked_until = 0.0
    if count >= threshold:
        locked_until = now + settings.LOGIN_LOCKOUT_SECONDS

    _LOGIN_ATTEMPTS[key] = (count, first_ts, locked_until)
    if locked_until > now:
        return int(settings.LOGIN_LOCKOUT_SECONDS)
    return None


def record_failed_login(ip: Optional[str], login: str) -> Optional[int]:
    """
    Records a failed login attempt for both IP+login and global account login.
    Prevents brute-force via X-Forwarded-For IP rotation.
    """
    now = time.monotonic()
    login_norm = login.lower().strip()
    ip_key = f"ip:{ip or 'unknown'}:{login_norm}"
    acct_key = f"acct:{login_norm}"

    lock_ip = _increment_attempt_key(ip_key, now, settings.LOGIN_MAX_ATTEMPTS)
    lock_acct = _increment_attempt_key(acct_key, now, settings.LOGIN_MAX_ATTEMPTS)
    return lock_ip or lock_acct


def reset_login_attempts(ip: Optional[str], login: str) -> None:
    login_norm = login.lower().strip()
    _LOGIN_ATTEMPTS.pop(f"ip:{ip or 'unknown'}:{login_norm}", None)
    _LOGIN_ATTEMPTS.pop(f"acct:{login_norm}", None)


def clear_all_login_attempts() -> None:
    _LOGIN_ATTEMPTS.clear()
    _REVOKED_TOKENS.clear()


def revoke_access_token(token: str) -> None:
    """Revokes a JWT token until its natural expiration."""
    if not token:
        return
    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    _cleanup_revoked_tokens(now_ts)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        payload = jwt.decode(
            token,
            settings.APP_SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False}
        )
        exp_ts = float(payload.get("exp") or (now_ts + 86400))
    except Exception:
        exp_ts = now_ts + 86400
    _REVOKED_TOKENS[token_hash] = exp_ts


def is_token_revoked(token: str) -> bool:
    if not token:
        return False
    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    exp_ts = _REVOKED_TOKENS.get(token_hash)
    if exp_ts is None:
        return False
    if exp_ts <= now_ts:
        _REVOKED_TOKENS.pop(token_hash, None)
        return False
    return True


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
    password_hash: Optional[str] = None
) -> str:
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"iat": now, "exp": expire, "type": "access"})
    if password_hash:
        to_encode["pwd_sig"] = compute_password_signature(password_hash)
    return jwt.encode(to_encode, settings.APP_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        if is_token_revoked(token):
            return None
        payload = jwt.decode(
            token,
            settings.APP_SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub"]}
        )
        if payload.get("type") not in (None, "access"):
            return None
        return payload
    except (jwt.PyJWTError, Exception):
        return None
