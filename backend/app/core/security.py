import datetime
import hashlib
import hmac
import time
from typing import Optional, Dict, Any, Tuple
import bcrypt
import jwt
from backend.app.config import settings

ALGORITHM = "HS256"

import os as _os


def _get_bcrypt_rounds() -> int:
    """Use cost=4 under automated tests for fast suites, and cost=12 in runtime/production."""
    if getattr(settings, "APP_ENV", "").strip().lower() == "testing" or _os.getenv("PYTEST_CURRENT_TEST"):
        return 4
    return 12


# Precomputed bcrypt hash used for constant-time comparison when user does not exist (Timing Attack defense)
DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"dummy_constant_time_defense_password",
    bcrypt.gensalt(rounds=_get_bcrypt_rounds()),
).decode("utf-8")

# Brute-force protection store: key -> (failed_count, first_attempt_ts, locked_until_ts)
_LOGIN_ATTEMPTS: Dict[str, Tuple[int, float, float]] = {}

# Revoked tokens store: token_hash -> exp_timestamp
_REVOKED_TOKENS: Dict[str, float] = {}


def _get_login_max_attempts() -> int:
    from backend.app.services.settings_service import get_effective_int_setting
    return get_effective_int_setting(
        "login_max_attempts",
        "LOGIN_MAX_ATTEMPTS",
        int(settings.LOGIN_MAX_ATTEMPTS or 5),
        min_value=1,
    )


def _get_login_lockout_seconds() -> int:
    from backend.app.services.settings_service import get_effective_int_setting
    return get_effective_int_setting(
        "login_lockout_seconds",
        "LOGIN_LOCKOUT_SECONDS",
        int(settings.LOGIN_LOCKOUT_SECONDS or 300),
        min_value=1,
    )


def _get_access_token_expire_minutes() -> int:
    from backend.app.services.settings_service import get_effective_int_setting
    return get_effective_int_setting(
        "access_token_expire_minutes",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        int(settings.ACCESS_TOKEN_EXPIRE_MINUTES or 1440),
        min_value=5,
    )


def get_password_hash(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=_get_bcrypt_rounds())
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


def reset_login_attempts(ip: Optional[str], login: str) -> None:
    login_norm = login.lower().strip()
    _LOGIN_ATTEMPTS.pop(f"ip:{ip or 'unknown'}:{login_norm}", None)
    _LOGIN_ATTEMPTS.pop(f"acct:{login_norm}", None)


_RESET_ATTEMPTS: Dict[str, Tuple[int, float, float]] = {}


def clear_all_login_attempts() -> None:
    _LOGIN_ATTEMPTS.clear()
    _RESET_ATTEMPTS.clear()
    _REVOKED_TOKENS.clear()


def extract_token_revocation_info(token: str) -> Optional[Tuple[str, float]]:
    """Return (sha256_token_hash, exp_unix_ts) for a JWT string."""
    if not token:
        return None
    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
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
    return token_hash, exp_ts


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
        expire = now + datetime.timedelta(minutes=_get_access_token_expire_minutes())
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
