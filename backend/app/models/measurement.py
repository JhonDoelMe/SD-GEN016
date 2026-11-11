from sqlalchemy import Column, Integer, String, Float, Numeric, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base, utc_now


class FuelMeasurement(Base):
    """
    Controlled fuel consumption measurement ('full tank to empty tank', >= 100 L)
    followed by mandatory 3-member commission inventory & PDF A4 statement approval.
    """

    __tablename__ = "fuel_measurements"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True)
    generator_id = Column(Integer, ForeignKey("generators.id", ondelete="CASCADE"), nullable=False, index=True)

    # MEASURING -> PENDING_INVENTORY -> PENDING_APPROVAL -> APPROVED | CANCELLED
    status = Column(String(32), nullable=False, default="MEASURING", index=True)

    started_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    start_operating_hours = Column(Float, nullable=False)
    start_tank_level_l = Column(Numeric(10, 3), nullable=False)
    old_nominal_consumption_l_per_h = Column(Float, nullable=False)
    min_liters_threshold = Column(Numeric(10, 3), nullable=False, default=100.0)
    added_during_measurement_l = Column(Numeric(10, 3), nullable=False, default=0.0)
    start_snapshot_json = Column(Text, nullable=True)

    tank_emptied_at = Column(DateTime, nullable=True)
    tank_emptied_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    end_operating_hours = Column(Float, nullable=True)
    total_fuel_consumed_l = Column(Numeric(10, 3), nullable=True)
    total_hours_elapsed = Column(Float, nullable=True)
    calculated_consumption_l_per_h = Column(Float, nullable=True)

    inventory_entered_at = Column(DateTime, nullable=True)
    commission_members_json = Column(Text, nullable=True)
    inventory_fact_json = Column(Text, nullable=True)
    statement_number = Column(String(40), nullable=True, index=True)
    document_generated_at = Column(DateTime, nullable=True)
    document_downloaded_at = Column(DateTime, nullable=True)

    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    cancelled_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    facility = relationship("Facility")
    generator = relationship("Generator")
    started_by = relationship("User", foreign_keys=[started_by_id])
    tank_emptied_by = relationship("User", foreign_keys=[tank_emptied_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
