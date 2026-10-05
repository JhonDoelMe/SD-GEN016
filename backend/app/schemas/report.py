import datetime
from typing import Optional, List
from pydantic import BaseModel


class OperationalReportFilter(BaseModel):
    generator_id: Optional[int] = None
    start_date: Optional[datetime.datetime] = None
    end_date: Optional[datetime.datetime] = None


class OperationalReportOut(BaseModel):
    start_date: str
    end_date: str
    generator_name: str

    # Operating Metrics
    total_runs_count: int
    total_operating_hours: float
    total_calculated_consumption_l: float

    # Fuel Metrics
    total_fuel_received_l: float
    total_fuel_receipts_cost_uah: float
    avg_fuel_price_per_liter: float
    total_fuel_transferred_to_tank_l: float
    current_stock_balance_l: float
    current_tank_level_l: float

    # Maintenance Metrics
    total_maintenance_count: int
    scheduled_maintenance_count: int
    intermediate_maintenance_count: int
    total_maintenance_cost_uah: float

    # Faults Metrics
    total_faults_count: int
    resolved_faults_count: int
    open_faults_count: int
