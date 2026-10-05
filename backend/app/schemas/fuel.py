import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FuelStockOut(BaseModel):
    id: int
    name: str
    fuel_type: str
    current_balance_l: float
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class FuelReceiptCreate(BaseModel):
    stock_id: Optional[int] = None
    fuel_type: str = Field(default="А-95")
    liters: float = Field(..., gt=0, description="Кількість літрів за чеком")
    cost_total: float = Field(..., gt=0, description="Загальна сума за чеком (грн)")
    driver_name: str = Field(..., min_length=2, description="ПІБ водія бензовоза")
    receipt_number: str = Field(..., min_length=1, description="Номер чека або накладної")
    comment: Optional[str] = None


class FuelReceiptOut(BaseModel):
    id: int
    stock_id: int
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
    stock_id: Optional[int] = None
    generator_id: Optional[int] = None
    liters: float = Field(..., gt=0, description="Кількість літрів для заправки бака")
    comment: Optional[str] = None


class FuelTransferOut(BaseModel):
    id: int
    stock_id: int
    generator_id: int
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
