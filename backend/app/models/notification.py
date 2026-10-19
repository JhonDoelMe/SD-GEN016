import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True)
    endpoint = Column(Text, nullable=False, unique=True, index=True)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    user_agent = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", lazy="selectin")
    facility = relationship("Facility", lazy="selectin")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # GENERATOR_START, GENERATOR_STOP, LOW_FUEL, MAINTENANCE_DUE, CRITICAL_FAULT, TEST
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="SET NULL"), nullable=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    recipients_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    generator = relationship("Generator", lazy="selectin")
    facility = relationship("Facility", lazy="selectin")
