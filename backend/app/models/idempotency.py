from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from backend.app.database import Base, utc_now


class IdempotencyRecord(Base):
    """Stores serialized responses for idempotent offline-queued mutations."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", "idempotency_key", name="uq_idempotency_user_ep_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(120), nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status_code = Column(Integer, nullable=False, default=200)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
