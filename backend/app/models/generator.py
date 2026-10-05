import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class Generator(Base):
    __tablename__ = "generators"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    manufacturer = Column(String(100), nullable=False)
    serial_number = Column(String(100), nullable=False)
    rated_power_kw = Column(Float, nullable=False, default=5.0)
    tank_capacity_l = Column(Float, nullable=False, default=25.0)
    fuel_type = Column(String(50), nullable=False, default="А-95")
    nominal_consumption_l_per_h = Column(Float, nullable=False, default=2.2)

    # Operational metrics
    current_operating_hours = Column(Float, nullable=False, default=0.0)
    fuel_tank_level_l = Column(Float, nullable=False, default=0.0)

    # Status: STOPPED, RUNNING, MAINTENANCE_REQUIRED, FAULTY, BLOCKED
    status = Column(String(50), nullable=False, default="STOPPED")
    is_configured = Column(Boolean, nullable=False, default=False)

    timezone = Column(String(50), nullable=False, default="Europe/Kyiv")
    extra_params_json = Column(Text, nullable=True)

    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    facility = relationship("Facility", back_populates="generators")
    schedules = relationship("GeneratorSchedule", back_populates="generator", cascade="all, delete-orphan", lazy="selectin")
    runs = relationship("GeneratorRun", back_populates="generator", cascade="all, delete-orphan")
    maintenance_schedules = relationship("MaintenanceSchedule", back_populates="generator", cascade="all, delete-orphan", lazy="selectin")
    maintenance_records = relationship("MaintenanceRecord", back_populates="generator", cascade="all, delete-orphan")
    faults = relationship("Fault", back_populates="generator", cascade="all, delete-orphan")
    transfers = relationship("FuelTransfer", back_populates="generator", cascade="all, delete-orphan")


class GeneratorSchedule(Base):
    __tablename__ = "generator_schedules"

    id = Column(Integer, primary_key=True, index=True)
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="CASCADE"), nullable=False)
    weekday = Column(Integer, nullable=False, default=-1)
    start_time = Column(String(10), nullable=False, default="08:00")
    end_time = Column(String(10), nullable=False, default="20:00")
    timezone = Column(String(50), nullable=False, default="Europe/Kyiv")
    is_active = Column(Boolean, nullable=False, default=True)

    generator = relationship("Generator", back_populates="schedules")


class GeneratorRun(Base):
    __tablename__ = "generator_runs"

    id = Column(Integer, primary_key=True, index=True)
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    start_time = Column(DateTime, default=utc_now, nullable=False)
    end_time = Column(DateTime, nullable=True)

    start_hours = Column(Float, nullable=False)
    end_hours = Column(Float, nullable=True)
    duration_hours = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    start_fuel_level_l = Column(Float, nullable=True)
    end_fuel_level_l = Column(Float, nullable=True)

    calculated_consumption_l = Column(Float, nullable=True)
    status = Column(String(50), nullable=False, default="RUNNING")
    note = Column(Text, nullable=True)

    generator = relationship("Generator", back_populates="runs")
    user = relationship("User", back_populates="runs", lazy="selectin")
