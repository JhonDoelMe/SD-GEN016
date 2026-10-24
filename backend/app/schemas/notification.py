import datetime
import ipaddress
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, field_validator

ALLOWED_PUSH_DOMAIN_SUFFIXES = (
    ".googleapis.com",
    ".google.com",
    ".push.services.mozilla.com",
    ".mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
    ".wns.windows.com",
)


def validate_safe_webpush_endpoint(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > 2048:
        raise ValueError("Некоректний URL Web Push ендпоінта")

    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Web Push ендпоінт повинен використовувати захищений протокол HTTPS")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise ValueError("Відсутній хост у Web Push ендпоінті")

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "app", "db", "nginx", "metadata.google.internal"):
        raise ValueError("Локальні та внутрішні адреси заборонені для Web Push")

    # Block raw IP addresses (private, loopback, link-local, or public IPs)
    try:
        ipaddress.ip_address(hostname)
        raise ValueError("Використання IP-адрес у Web Push ендпоінтах заборонено")
    except ValueError as e:
        if "заборонено" in str(e):
            raise

    # Enforce whitelist of official browser Web Push services (prevents SSRF)
    if not any(hostname == s.lstrip(".") or hostname.endswith(s) for s in ALLOWED_PUSH_DOMAIN_SUFFIXES):
        raise ValueError(
            "Домен Web Push сервісу не входить до переліку дозволених офіційних провайдерів (FCM, Mozilla, Apple, WNS)"
        )

    return url


class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=512)
    auth: str = Field(..., min_length=1, max_length=256)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(..., description="W3C Push endpoint URL")
    keys: PushKeys
    user_agent: Optional[str] = Field(default=None, max_length=512)
    facility_id: Optional[int] = None

    @field_validator("endpoint")
    @classmethod
    def check_endpoint_ssrf(cls, v: str) -> str:
        return validate_safe_webpush_endpoint(v)


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
    title: Optional[str] = Field(default="Тестове сповіщення Service Desk", max_length=150)
    body: Optional[str] = Field(default="Система сповіщень працює належним чином на вашому пристрої!", max_length=500)
