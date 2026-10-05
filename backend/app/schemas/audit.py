import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details_json: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class SystemAdjustmentCreate(BaseModel):
    entity_type: str = Field(..., description="Generator / FuelStock / MaintenanceSchedule")
    entity_id: int = Field(..., description="ID сутності")
    field_name: str = Field(..., min_length=2, description="Поле для коригування")
    new_value: str = Field(..., description="Нове значення")
    reason: str = Field(..., min_length=5, description="Обов'язкова причина системного коригування")


class SystemAdjustmentOut(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    entity_type: str
    entity_id: int
    field_name: str
    old_value: str
    new_value: str
    reason: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
