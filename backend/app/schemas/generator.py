import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ScheduleItem(BaseModel):
    weekday: int = -1  # -1 = All days, 0 = Monday ... 6 = Sunday
    start_time: str = "08:00"
    end_time: str = "20:00"
    is_active: bool = True


class GeneratorScheduleOut(BaseModel):
    id: int
    weekday: int
    start_time: str
    end_time: str
    timezone: str
    is_active: bool

    model_config = {"from_attributes": True}


class GeneratorWizardSetup(BaseModel):
    name: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    manufacturer: str = Field(..., min_length=1)
    serial_number: str = Field(..., min_length=1)
    rated_power_kw: float = Field(..., gt=0)
    tank_capacity_l: float = Field(..., gt=0)
    fuel_type: str = Field(default="А-95")
    nominal_consumption_l_per_h: float = Field(..., gt=0)
    initial_operating_hours: float = Field(default=0.0, ge=0)
    initial_fuel_tank_level_l: float = Field(default=0.0, ge=0)
    work_schedule_start: str = Field(default="08:00")
    work_schedule_end: str = Field(default="20:00")
    maintenance_interval_hours: float = Field(default=300.0, gt=0)
    timezone: str = Field(default="Europe/Kyiv")


class GeneratorUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    rated_power_kw: Optional[float] = None
    tank_capacity_l: Optional[float] = None
    fuel_type: Optional[str] = None
    nominal_consumption_l_per_h: Optional[float] = None
    timezone: Optional[str] = None


class GeneratorOut(BaseModel):
    id: int
    name: str
    model: str
    manufacturer: str
    serial_number: str
    rated_power_kw: float
    tank_capacity_l: float
    fuel_type: str
    nominal_consumption_l_per_h: float
    current_operating_hours: float
    fuel_tank_level_l: float
    status: str
    is_configured: bool
    timezone: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    schedules: List[GeneratorScheduleOut] = []

    model_config = {"from_attributes": True}


class GeneratorStartRequest(BaseModel):
    fuel_level_l: Optional[float] = None


class GeneratorStopRequest(BaseModel):
    end_hours: float = Field(..., description="Показання лічильника мотогодин при зупинці")
    end_fuel_level_l: Optional[float] = None
    note: Optional[str] = None


class GeneratorRunOut(BaseModel):
    id: int
    generator_id: int
    user_id: int
    user_name: Optional[str] = None
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime] = None
    start_hours: float
    end_hours: Optional[float] = None
    duration_hours: Optional[float] = None
    start_fuel_level_l: Optional[float] = None
    end_fuel_level_l: Optional[float] = None
    calculated_consumption_l: Optional[float] = None
    status: str
    note: Optional[str] = None

    model_config = {"from_attributes": True}
