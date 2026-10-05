import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(100), nullable=True)

    details_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    user = relationship("User", back_populates="audit_logs", lazy="selectin")


class SystemAdjustment(Base):
    __tablename__ = "system_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    entity_type = Column(String(100), nullable=False)
    entity_id = Column(Integer, nullable=False)
    field_name = Column(String(100), nullable=False)

    old_value = Column(Text, nullable=False)
    new_value = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    user = relationship("User", back_populates="adjustments", lazy="selectin")
