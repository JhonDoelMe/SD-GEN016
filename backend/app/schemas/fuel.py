import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FuelStockCreate(BaseModel):
    facility_id: int = Field(..., description="ID об'єкта, до якого належить склад")
    name: str = Field(..., min_length=2, max_length=100, description="Назва складу ГСМ")
    fuel_type: str = Field(default="А-95", max_length=50)
    initial_balance_l: float = Field(default=0.0, ge=0, description="Початковий залишок (л)")


class FuelStockOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
    facility_name: Optional[str] = None
    name: str
    fuel_type: str
    current_balance_l: float
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class FuelReceiptCreate(BaseModel):
    facility_id: Optional[int] = None
    stock_id: Optional[int] = None
    fuel_type: str = Field(default="А-95")
    liters: float = Field(..., gt=0, description="Кількість літрів за чеком")
    cost_total: float = Field(..., gt=0, description="Загальна сума за чеком (грн)")
    driver_name: str = Field(..., min_length=2, description="ПІБ водія бензовоза")
    receipt_number: str = Field(..., min_length=1, description="Номер чека або накладної")
    comment: Optional[str] = None


class FuelReceiptOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
    facility_name: Optional[str] = None
    stock_id: int
    stock_name: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    fuel_type: str
    liters: float
    cost_total: float
    price_per_liter: float
    driver_name: str
    receipt_number: str
    comment: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class FuelTransferCreate(BaseModel):
    facility_id: Optional[int] = None
    stock_id: Optional[int] = None
    generator_id: Optional[int] = None
    liters: float = Field(..., gt=0, description="Кількість літрів для заправки бака")
    comment: Optional[str] = None


class FuelTransferOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
    facility_name: Optional[str] = None
    stock_id: int
    stock_name: Optional[str] = None
    generator_id: int
    generator_name: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    liters: float
    source_balance_before: float
    source_balance_after: float
    tank_balance_before: float
    tank_balance_after: float
    comment: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class FuelBalancesSummary(BaseModel):
    warehouse_balance_l: float
    tank_balance_l: float
    tank_capacity_l: float
    total_received_l: float
    total_spent_uah: float
    avg_price_per_liter: float
    total_transferred_l: float
    total_calculated_consumed_l: float
