from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base, utc_now


class FuelStock(Base):
    __tablename__ = "fuel_stocks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="Основний склад ГСМ")
    fuel_type = Column(String(50), nullable=False, default="А-95")
    current_balance_l = Column(Numeric(10, 3, asdecimal=True), nullable=False, default=0.0)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    facility = relationship("Facility", back_populates="fuel_stocks")
    receipts = relationship("FuelReceipt", back_populates="stock")
    transfers = relationship("FuelTransfer", back_populates="stock")


class FuelReceipt(Base):
    __tablename__ = "fuel_receipts"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True)
    stock_id = Column(Integer, ForeignKey("fuel_stocks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    fuel_type = Column(String(50), nullable=False)
    fuel_provider = Column(String(50), nullable=True, default="wog", server_default="wog")
    liters = Column(Numeric(10, 3, asdecimal=True), nullable=False)
    cost_total = Column(Numeric(12, 2, asdecimal=True), nullable=False)
    price_per_liter = Column(Numeric(12, 2, asdecimal=True), nullable=False)

    driver_name = Column(String(255), nullable=False)
    receipt_number = Column(String(100), nullable=False)
    comment = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=True, unique=True, index=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    stock = relationship("FuelStock", back_populates="receipts")
    user = relationship("User", back_populates="fuel_receipts", lazy="selectin")


class FuelTransfer(Base):
    __tablename__ = "fuel_transfers"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True)
    stock_id = Column(Integer, ForeignKey("fuel_stocks.id"), nullable=False)
    generator_id = Column(Integer, ForeignKey("generators.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    liters = Column(Numeric(10, 3, asdecimal=True), nullable=False)
    source_balance_before = Column(Numeric(10, 3, asdecimal=True), nullable=False)
    source_balance_after = Column(Numeric(10, 3, asdecimal=True), nullable=False)
    tank_balance_before = Column(Numeric(10, 3, asdecimal=True), nullable=False)
    tank_balance_after = Column(Numeric(10, 3, asdecimal=True), nullable=False)

    comment = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    stock = relationship("FuelStock", back_populates="transfers")
    generator = relationship("Generator", back_populates="transfers")
    user = relationship("User", back_populates="fuel_transfers", lazy="selectin")
