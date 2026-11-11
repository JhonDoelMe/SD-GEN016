import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class FuelStockCreate(BaseModel):
    facility_id: int = Field(..., description="ID об'єкта, до якого належить склад")
    name: str = Field(..., min_length=2, max_length=100, description="Назва складу ГСМ")
    fuel_type: str = Field(default="А-95", max_length=50)
    initial_balance_l: float = Field(default=0.0, ge=0, description="Початковий залишок (л)")


class FuelStockUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100, description="Нова назва складу ГСМ")
    fuel_type: Optional[str] = Field(None, min_length=2, max_length=50, description="Новий тип палива")
    facility_id: Optional[int] = Field(None, description="Перенесення на інший об'єкт")
    is_active: Optional[bool] = Field(None, description="Статус активності складу")


class FuelStockOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
    facility_name: Optional[str] = None
    name: str
    fuel_type: str
    current_balance_l: float
    is_active: bool = True
    updated_at: datetime.datetime
    has_canister_pools: bool = False
    canisters_total: int = 0
    canisters_full: int = 0
    canisters_empty: int = 0
    canisters_away: int = 0
    canister_reserve_l: float = 0.0

    model_config = {"from_attributes": True}


class FuelReceiptCreate(BaseModel):
    facility_id: Optional[int] = None
    stock_id: Optional[int] = None
    canister_pool_id: Optional[int] = None
    fuel_provider: Optional[str] = Field(default=None, description="Мережа АЗС / Постачальник (wog, okko, other)")
    fuel_type: Optional[str] = Field(default=None, description="Тип палива (за замовчуванням зі складу)")
    liters: float = Field(..., gt=0, description="Кількість літрів за чеком")
    cost_total: Optional[float] = Field(
        default=None,
        ge=0,
        description="Загальна сума за чеком (грн). Якщо не вказано або 0 — розраховується автоматично з налаштувань або інтернету"
    )
    price_per_liter: Optional[float] = Field(
        default=None,
        ge=0,
        description="Ціна за літр (грн, необов'язково)"
    )
    driver_name: str = Field(..., min_length=2, description="ПІБ водія бензовоза")
    receipt_number: str = Field(..., min_length=1, description="Номер чека або накладної")
    comment: Optional[str] = None
    force_confirm: bool = Field(False, description="Підтвердження операції при значному об'ємі або нетиповій ціні")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Унікальний ключ ідемпотентності")


class FuelReceiptOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
    facility_name: Optional[str] = None
    stock_id: int
    stock_name: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    fuel_provider: Optional[str] = "wog"
    fuel_type: str
    liters: float
    cost_total: float
    price_per_liter: float
    price_source: Optional[str] = None
    driver_name: str
    receipt_number: str
    comment: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class FuelTransferCreate(BaseModel):
    facility_id: Optional[int] = None
    stock_id: Optional[int] = None
    canister_pool_id: Optional[int] = None
    generator_id: Optional[int] = None
    liters: float = Field(..., gt=0, description="Кількість літрів для заправки бака")
    comment: Optional[str] = None
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Унікальний ключ ідемпотентності")


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
    used_from_reserve_l: Optional[float] = None
    opened_canisters_count: Optional[int] = None
    canister_reserve_after_l: Optional[float] = None
    comment: Optional[str] = None
    idempotency_key: Optional[str] = None
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
    canisters_total: int = 0
    canisters_full: int = 0
    canisters_empty: int = 0
    canisters_away: int = 0
    canister_reserve_l: float = 0.0


class CanisterPoolCreate(BaseModel):
    facility_id: int
    stock_id: int
    name: str = Field(..., min_length=2, max_length=120)
    canister_volume_l: float = Field(default=20.0, gt=0, le=200)
    full_count: int = Field(default=0, ge=0)
    empty_count: int = Field(default=0, ge=0)
    away_refill_count: int = Field(default=0, ge=0)
    reserve_liters: float = Field(default=0.0, ge=0)


class CanisterPoolUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    canister_volume_l: Optional[float] = Field(None, gt=0, le=200)
    full_count: Optional[int] = Field(None, ge=0)
    empty_count: Optional[int] = Field(None, ge=0)
    away_refill_count: Optional[int] = Field(None, ge=0)
    reserve_liters: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class CanisterPoolOut(BaseModel):
    id: int
    facility_id: int
    facility_name: Optional[str] = None
    stock_id: int
    stock_name: Optional[str] = None
    name: str
    fuel_type: str
    canister_volume_l: float
    total_count: int
    full_count: int
    empty_count: int
    away_refill_count: int
    reserve_liters: float
    available_liters: float
    is_active: bool = True
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class CanisterDispatchRequest(BaseModel):
    count: int = Field(..., ge=1, description="Кількість порожніх каністр для відправки на заправку")
    comment: Optional[str] = None
    idempotency_key: Optional[str] = Field(None, max_length=64)


class CanisterReturnEmptyRequest(BaseModel):
    count: int = Field(..., ge=1, description="Кількість каністр, повернених порожніми без заправки")
    comment: Optional[str] = None
    idempotency_key: Optional[str] = Field(None, max_length=64)


class CanisterReceiveRequest(BaseModel):
    count: int = Field(..., ge=1, description="Кількість заправлених каністр, що привезли")
    source: Literal["auto", "away", "empty"] = Field(
        default="auto",
        description="'auto' — спершу закриває каністри на АЗС, далі порожні; 'away' — тільки з АЗС; 'empty' — тільки з порожніх"
    )
    create_receipt: bool = Field(default=True, description="Створити прибутковий чек у журналі надходжень")
    fuel_provider: Optional[str] = None
    cost_total: Optional[float] = Field(default=None, ge=0)
    price_per_liter: Optional[float] = Field(default=None, ge=0)
    driver_name: str = Field(default="Доставка каністр", min_length=2)
    receipt_number: Optional[str] = None
    comment: Optional[str] = None
    force_confirm: bool = False
    idempotency_key: Optional[str] = Field(None, max_length=64)


class CanisterTransactionOut(BaseModel):
    id: int
    facility_id: int
    pool_id: int
    pool_name: Optional[str] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    operation: str
    count: int
    liters_delta: float
    used_from_reserve_l: float
    full_before: int
    full_after: int
    empty_before: int
    empty_after: int
    away_before: int
    away_after: int
    reserve_before: float
    reserve_after: float
    related_transfer_id: Optional[int] = None
    related_receipt_id: Optional[int] = None
    comment: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
