import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MeasurementStartRequest(BaseModel):
    facility_id: Optional[int] = None
    generator_id: int


class MeasurementFinishEmptyRequest(BaseModel):
    end_operating_hours: Optional[float] = Field(default=None, ge=0)


class CommissionMemberIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    role: str = Field(..., min_length=2, max_length=120)


class InventoryPoolFactIn(BaseModel):
    pool_id: int
    full_count: int = Field(..., ge=0)
    empty_count: int = Field(..., ge=0)
    away_refill_count: int = Field(..., ge=0)
    reserve_liters: float = Field(default=0.0, ge=0)


class InventoryStockFactIn(BaseModel):
    stock_id: int
    fact_balance_l: float = Field(..., ge=0)


class MeasurementInventoryRequest(BaseModel):
    generator_tank_fact_l: float = Field(default=0.0, ge=0)
    pools: List[InventoryPoolFactIn] = Field(default_factory=list)
    stocks: List[InventoryStockFactIn] = Field(default_factory=list)
    commission_members: List[CommissionMemberIn] = Field(..., min_length=3)
    notes: Optional[str] = Field(default=None, max_length=500)


class MeasurementCancelRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class MeasurementTransferItemOut(BaseModel):
    id: int
    created_at: datetime.datetime
    liters: float
    stock_name: str
    operator_name: Optional[str] = None
    comment: Optional[str] = None


class MeasurementSummaryOut(BaseModel):
    id: int
    facility_id: int
    facility_name: Optional[str] = None
    generator_id: int
    generator_name: Optional[str] = None
    generator_model: Optional[str] = None
    fuel_type: Optional[str] = None
    tank_capacity_l: float = 0.0
    status: str

    started_at: datetime.datetime
    started_by_name: Optional[str] = None
    start_operating_hours: float
    current_operating_hours: float
    start_tank_level_l: float
    added_during_measurement_l: float
    measured_liters_total: float
    min_liters_threshold: float
    liters_remaining_to_min: float
    progress_pct: float
    can_finish_empty: bool
    is_generator_running: bool = False

    elapsed_hours: float = 0.0
    old_nominal_consumption_l_per_h: float
    est_consumption_l_per_h: Optional[float] = None

    tank_emptied_at: Optional[datetime.datetime] = None
    end_operating_hours: Optional[float] = None
    total_fuel_consumed_l: Optional[float] = None
    total_hours_elapsed: Optional[float] = None
    calculated_consumption_l_per_h: Optional[float] = None

    statement_number: Optional[str] = None
    inventory_entered_at: Optional[datetime.datetime] = None
    document_generated_at: Optional[datetime.datetime] = None
    document_downloaded_at: Optional[datetime.datetime] = None
    can_approve: bool = False

    approved_at: Optional[datetime.datetime] = None
    approved_by_name: Optional[str] = None
    cancelled_at: Optional[datetime.datetime] = None
    cancel_reason: Optional[str] = None

    commission_members: List[Dict[str, Any]] = Field(default_factory=list)
    inventory_fact: Optional[Dict[str, Any]] = None
    transfers: List[MeasurementTransferItemOut] = Field(default_factory=list)
    current_stocks: List[Dict[str, Any]] = Field(default_factory=list)
    current_pools: List[Dict[str, Any]] = Field(default_factory=list)


class MeasurementStatusEnvelope(BaseModel):
    has_active: bool
    is_locked: bool
    is_measuring: bool
    lock_reason: Optional[str] = None
    active: Optional[MeasurementSummaryOut] = None
    latest_completed: Optional[MeasurementSummaryOut] = None
