import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.app.database import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class FuelStock(Base):
    __tablename__ = "fuel_stocks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="Основний склад ГСМ")
    fuel_type = Column(String(50), nullable=False, default="А-95")
    current_balance_l = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    receipts = relationship("FuelReceipt", back_populates="stock", cascade="all, delete-orphan")
    transfers = relationship("FuelTransfer", back_populates="stock", cascade="all, delete-orphan")


class FuelReceipt(Base):
    __tablename__ = "fuel_receipts"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("fuel_stocks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    fuel_type = Column(String(50), nullable=False)
    liters = Column(Float, nullable=False)
    cost_total = Column(Float, nullable=False)
    price_per_liter = Column(Float, nullable=False)

    driver_name = Column(String(255), nullable=False)
    receipt_number = Column(String(100), nullable=False)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    stock = relationship("FuelStock", back_populates="receipts")
    user = relationship("User", back_populates="fuel_receipts", lazy="selectin")


class FuelTransfer(Base):
    __tablename__ = "fuel_transfers"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("fuel_stocks.id"), nullable=False)
    generator_id = Column(Integer, ForeignKey("generators.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    liters = Column(Float, nullable=False)
    source_balance_before = Column(Float, nullable=False)
    source_balance_after = Column(Float, nullable=False)
    tank_balance_before = Column(Float, nullable=False)
    tank_balance_after = Column(Float, nullable=False)

    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    stock = relationship("FuelStock", back_populates="transfers")
    generator = relationship("Generator", back_populates="transfers")
    user = relationship("User", back_populates="fuel_transfers", lazy="selectin")
