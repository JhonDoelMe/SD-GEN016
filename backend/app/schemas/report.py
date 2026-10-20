import datetime
from typing import Optional, List
from pydantic import BaseModel


class OperationalReportFilter(BaseModel):
    generator_id: Optional[int] = None
    start_date: Optional[datetime.datetime] = None
    end_date: Optional[datetime.datetime] = None


class ReportRunItem(BaseModel):
    id: int
    start_time: str
    end_time: Optional[str] = None
    duration_hours: float
    calculated_consumption_l: float
    start_hours: float
    end_hours: Optional[float] = None
    operator_name: str
    status: str


class ReportFuelReceiptItem(BaseModel):
    id: int
    created_at: str
    liters: float
    price_per_liter: float
    cost_total: float
    receipt_number: Optional[str] = "-"
    driver_name: Optional[str] = "-"
    supplier: Optional[str] = "-"
    stock_name: str
    operator_name: str


class ReportFuelTransferItem(BaseModel):
    id: int
    created_at: str
    liters: float
    stock_name: str
    generator_name: str
    operator_name: str


class ReportMaintenanceItem(BaseModel):
    id: int
    created_at: str
    maintenance_type: str
    operating_hours: float
    work_description: str
    cost: float
    technician: Optional[str] = None
    operator_name: str


class OperationalReportOut(BaseModel):
    start_date: str
    end_date: str
    generator_name: str
    facility_name: Optional[str] = None

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

    # Calculated Analytics
    total_costs_uah: float = 0.0
    avg_consumption_l_per_hour: float = 0.0
    avg_run_duration_hours: float = 0.0

    # Detailed records for the selected period
    runs: List[ReportRunItem] = []
    fuel_receipts: List[ReportFuelReceiptItem] = []
    fuel_transfers: List[ReportFuelTransferItem] = []
    maintenance_records: List[ReportMaintenanceItem] = []
