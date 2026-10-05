import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"

    id = Column(Integer, primary_key=True, index=True)
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="CASCADE"), nullable=False)
    interval_hours = Column(Float, nullable=False, default=300.0)
    last_performed_hours = Column(Float, nullable=False, default=0.0)
    next_due_hours = Column(Float, nullable=False, default=300.0)
    is_active = Column(Boolean, nullable=False, default=True)

    generator = relationship("Generator", back_populates="maintenance_schedules")


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id = Column(Integer, primary_key=True, index=True)
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    maintenance_type = Column(String(50), nullable=False)
    operating_hours = Column(Float, nullable=False)
    work_description = Column(Text, nullable=False)
    consumables_used = Column(Text, nullable=True)
    cost = Column(Float, nullable=False, default=0.0)
    comment = Column(Text, nullable=True)
    photo_urls = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    generator = relationship("Generator", back_populates="maintenance_records")
    user = relationship("User", back_populates="maintenance_records", lazy="selectin")
