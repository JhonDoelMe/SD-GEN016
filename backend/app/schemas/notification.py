import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(..., description="W3C Push endpoint URL")
    keys: PushKeys
    user_agent: Optional[str] = None
    facility_id: Optional[int] = None


class PushSubscriptionOut(BaseModel):
    id: int
    endpoint: str
    user_id: int
    facility_id: Optional[int] = None
    is_active: bool
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationSettingsIn(BaseModel):
    notifications_enabled: bool = True
    notify_generator_start: bool = True
    notify_generator_stop: bool = True
    notify_low_fuel: bool = True
    low_fuel_threshold_l: float = Field(default=5.0, ge=0.5, le=500.0)
    notify_maintenance: bool = True
    max_maintenance_notifications_per_day: int = Field(default=2, ge=1, le=10)
    notify_critical_faults: bool = True


class NotificationSettingsOut(BaseModel):
    notifications_enabled: bool
    notify_generator_start: bool
    notify_generator_stop: bool
    notify_low_fuel: bool
    low_fuel_threshold_l: float
    notify_maintenance: bool
    max_maintenance_notifications_per_day: int
    notify_critical_faults: bool
    vapid_public_key: str
    active_subscriptions_count: int


class NotificationLogOut(BaseModel):
    id: int
    event_type: str
    generator_id: Optional[int] = None
    facility_id: Optional[int] = None
    title: str
    body: str
    recipients_count: int
    success_count: int
    failure_count: int
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class TestNotificationIn(BaseModel):
    title: Optional[str] = "Тестове сповіщення Service Desk"
    body: Optional[str] = "Система сповіщень працює належним чином на вашому пристрої!"
