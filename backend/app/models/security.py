import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime
from backend.app.database import Base, utc_now


class RevokedToken(Base):
    """JWT tokens explicitly revoked on logout before natural expiration."""

    __tablename__ = "revoked_tokens"

    token_hash = Column(String(64), primary_key=True, index=True)
    expires_at = Column(Float, nullable=False, index=True)
    revoked_at = Column(DateTime, default=utc_now, nullable=False)


class AuthAttempt(Base):
    """Persistent brute-force lockout counters for login and password reset."""

    __tablename__ = "auth_attempts"

    attempt_key = Column(String(255), primary_key=True, index=True)
    failed_count = Column(Integer, default=0, nullable=False)
    first_attempt_at = Column(Float, nullable=False)
    locked_until = Column(Float, default=0.0, nullable=False, index=True)
    expires_at = Column(Float, nullable=False, index=True)
