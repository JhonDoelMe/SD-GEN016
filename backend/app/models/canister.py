from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base, utc_now


class CanisterPool(Base):
    """Facility-assigned pool of uniform fuel canisters plus on-site reserve buffer."""

    __tablename__ = "canister_pools"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True)
    stock_id = Column(Integer, ForeignKey("fuel_stocks.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(120), nullable=False, default="Основні каністри")
    fuel_type = Column(String(50), nullable=False, default="А-95")
    canister_volume_l = Column(Numeric(8, 2), nullable=False, default=20.0)

    total_count = Column(Integer, nullable=False, default=0)
    full_count = Column(Integer, nullable=False, default=0)
    empty_count = Column(Integer, nullable=False, default=0)
    away_refill_count = Column(Integer, nullable=False, default=0)

    # On-site reserve vessel storing leftover fuel (< canister_volume_l) so opened canisters become empty immediately
    reserve_liters = Column(Numeric(10, 3), nullable=False, default=0.0)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    facility = relationship("Facility")
    stock = relationship("FuelStock")
    transactions = relationship("CanisterTransaction", back_populates="pool", cascade="all, delete-orphan")


class CanisterTransaction(Base):
    """Audit journal of canister dispatches, returns, refills, and reserve-first transfers."""

    __tablename__ = "canister_transactions"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True)
    pool_id = Column(Integer, ForeignKey("canister_pools.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    operation = Column(String(40), nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
    liters_delta = Column(Numeric(10, 3), nullable=False, default=0.0)
    used_from_reserve_l = Column(Numeric(10, 3), nullable=False, default=0.0)

    full_before = Column(Integer, nullable=False, default=0)
    full_after = Column(Integer, nullable=False, default=0)
    empty_before = Column(Integer, nullable=False, default=0)
    empty_after = Column(Integer, nullable=False, default=0)
    away_before = Column(Integer, nullable=False, default=0)
    away_after = Column(Integer, nullable=False, default=0)
    reserve_before = Column(Numeric(10, 3), nullable=False, default=0.0)
    reserve_after = Column(Numeric(10, 3), nullable=False, default=0.0)

    related_transfer_id = Column(Integer, ForeignKey("fuel_transfers.id", ondelete="SET NULL"), nullable=True)
    related_receipt_id = Column(Integer, ForeignKey("fuel_receipts.id", ondelete="SET NULL"), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    pool = relationship("CanisterPool", back_populates="transactions")
    user = relationship("User")
    facility = relationship("Facility")
