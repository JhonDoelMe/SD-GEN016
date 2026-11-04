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
    generator_id: Optional[int] = None
    facility_id: Optional[int] = None
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
    last_maintenance_performed_hours: Optional[float] = None
    timezone: str = Field(default="Europe/Kyiv")


class GeneratorCreate(GeneratorWizardSetup):
    pass


class GeneratorUpdate(BaseModel):
    facility_id: Optional[int] = None
    name: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    rated_power_kw: Optional[float] = None
    tank_capacity_l: Optional[float] = None
    fuel_type: Optional[str] = None
    nominal_consumption_l_per_h: Optional[float] = None
    timezone: Optional[str] = None


class GeneratorFacilityTransferRequest(BaseModel):
    target_facility_id: int = Field(..., description="ID цільового об'єкта")
    reason: str = Field(..., min_length=3, max_length=500, description="Причина перенесення генератора")


class GeneratorOut(BaseModel):
    id: int
    facility_id: Optional[int] = None
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
    is_active: bool = True
    archived_at: Optional[datetime.datetime] = None
    timezone: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    schedules: List[GeneratorScheduleOut] = []
    cooldown_remaining_seconds: int = 0

    model_config = {"from_attributes": True}


class GeneratorStartRequest(BaseModel):
    generator_id: Optional[int] = None
    fuel_level_l: Optional[float] = None
    force_start_with_maintenance: bool = Field(False, description="Дозвіл запуску генератора при простроченому ТО")
    force_start_reason: Optional[str] = Field(None, max_length=500, description="Обов'язкова причина примусового запуску при простроченому ТО")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Ключ ідемпотентності для захисту від дублювання")
    skip_cooldown: bool = Field(False, description="Пропуск 60-секундного кулдауну (для адміністраторів або тестів)")


class GeneratorStopRequest(BaseModel):
    generator_id: Optional[int] = None
    end_hours: Optional[float] = Field(None, description="Показання лічильника мотогодин при зупинці (якщо не вказано, розраховується автоматично)")
    end_fuel_level_l: Optional[float] = None
    note: Optional[str] = None
    fuel_discrepancy_reason: Optional[str] = Field(None, max_length=500, description="Пояснення причини розбіжності палива у баку")
    force_confirm: bool = Field(False, description="Підтвердження операції при підозрілій різниці мотогодин")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Ключ ідемпотентності")


class GeneratorManualRunCreate(BaseModel):
    generator_id: Optional[int] = None
    start_time: datetime.datetime = Field(..., description="Час запуску генератора (з паперового журналу)")
    end_time: datetime.datetime = Field(..., description="Час зупинки генератора (з паперового журналу)")
    start_hours: Optional[float] = Field(None, ge=0, description="Початкові мотогодини (якщо відомі)")
    end_hours: Optional[float] = Field(None, ge=0, description="Кінцеві мотогодини (якщо відомі)")
    fuel_consumed_l: Optional[float] = Field(None, ge=0, description="Фактично витрачене паливо (якщо відомо)")
    note: Optional[str] = Field(None, max_length=500, description="Примітки (напр. Внесено з паперового журналу)")
    force_confirm: bool = Field(False, description="Підтвердження при розходженні мотогодин із часом")
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Ключ ідемпотентності для захисту від дублювання")
    skip_cooldown: bool = Field(False, description="Пропуск 60-секундного кулдауну (для адміністраторів або тестів)")


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
    duration_seconds: Optional[int] = None
    duration_formatted: Optional[str] = None
    start_fuel_level_l: Optional[float] = None
    end_fuel_level_l: Optional[float] = None
    calculated_consumption_l: Optional[float] = None
    status: str
    note: Optional[str] = None


    model_config = {"from_attributes": True}
