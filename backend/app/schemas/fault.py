import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FaultCreate(BaseModel):
    generator_id: Optional[int] = None
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5)
    priority: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    photo_urls: Optional[str] = None


class FaultStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(NEW|ACCEPTED|IN_PROGRESS|PENDING|RESOLVED|CLOSED)$")
    resolution_notes: Optional[str] = None


class FaultOut(BaseModel):
    id: int
    generator_id: int
    user_id: int
    user_name: Optional[str] = None
    title: str
    description: str
    operating_hours: float
    priority: str
    status: str
    photo_urls: Optional[str] = None
    resolved_by_id: Optional[int] = None
    resolved_by_name: Optional[str] = None
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
