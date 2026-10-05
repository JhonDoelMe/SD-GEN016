import datetime
from typing import Optional
from pydantic import BaseModel, Field


class MaintenanceScheduleOut(BaseModel):
    id: int
    generator_id: int
    interval_hours: float
    last_performed_hours: float
    next_due_hours: float
    current_operating_hours: float
    hours_remaining: float
    is_due: bool
    is_overdue: bool
    is_active: bool

    model_config = {"from_attributes": True}


class MaintenanceScheduleUpdate(BaseModel):
    interval_hours: float = Field(..., gt=0)


class MaintenanceRecordCreate(BaseModel):
    generator_id: Optional[int] = None
    maintenance_type: str = Field(..., pattern="^(SCHEDULED|INTERMEDIATE)$")
    work_description: str = Field(..., min_length=3)
    consumables_used: Optional[str] = None
    cost: float = Field(default=0.0, ge=0)
    comment: Optional[str] = None
    photo_urls: Optional[str] = None


class MaintenanceRecordOut(BaseModel):
    id: int
    generator_id: int
    user_id: int
    user_name: Optional[str] = None
    maintenance_type: str
    operating_hours: float
    work_description: str
    consumables_used: Optional[str] = None
    cost: float
    comment: Optional[str] = None
    photo_urls: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
