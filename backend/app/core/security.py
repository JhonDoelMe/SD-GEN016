import datetime
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


def check_login_rate_limit(ip: Optional[str], login: str) -> Optional[int]:
    """
    Returns remaining lockout seconds if blocked, or None if allowed.
    """
    now = time.monotonic()
    key = f"{ip or 'unknown'}:{login.lower()}"
    entry = _LOGIN_ATTEMPTS.get(key)
    if not entry:
        return None
    count, first_ts, locked_until = entry
    if locked_until > now:
        return max(1, int(locked_until - now))
    if now - first_ts > settings.LOGIN_LOCKOUT_SECONDS:
        _LOGIN_ATTEMPTS.pop(key, None)
    return None


def record_failed_login(ip: Optional[str], login: str) -> Optional[int]:
    """
    Records a failed login attempt and returns lockout seconds if threshold reached.
    """
    now = time.monotonic()
    key = f"{ip or 'unknown'}:{login.lower()}"
    entry = _LOGIN_ATTEMPTS.get(key)
    if not entry or (now - entry[1] > settings.LOGIN_LOCKOUT_SECONDS) or (entry[2] > 0 and entry[2] <= now):
        count = 1
        first_ts = now
    else:
        count = entry[0] + 1
        first_ts = entry[1]

    locked_until = 0.0
    if count >= settings.LOGIN_MAX_ATTEMPTS:
        locked_until = now + settings.LOGIN_LOCKOUT_SECONDS

    _LOGIN_ATTEMPTS[key] = (count, first_ts, locked_until)
    if locked_until > now:
        return int(settings.LOGIN_LOCKOUT_SECONDS)
    return None


def reset_login_attempts(ip: Optional[str], login: str) -> None:
    key = f"{ip or 'unknown'}:{login.lower()}"
    _LOGIN_ATTEMPTS.pop(key, None)


def clear_all_login_attempts() -> None:
    _LOGIN_ATTEMPTS.clear()


def create_access_token(data: Dict[str, Any], expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"iat": now, "exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.APP_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
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
