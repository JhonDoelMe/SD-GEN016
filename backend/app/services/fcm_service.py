"""Lightweight async Firebase Cloud Messaging (HTTP v1 API) client for Android Push."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
import jwt

from backend.app.config import settings

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
HIGH_PRIORITY_EVENTS = {
    "AIR_ALERT_START",
    "CRITICAL_FAULT",
    "GENERATOR_SAFETY_STOP",
    "GENERATOR_AUTO_STOP",
    "LOW_FUEL",
    "TEST",
}

_token_lock = asyncio.Lock()
_cached_access_token: Optional[str] = None
_cached_expires_at: float = 0.0
_cached_project_id: Optional[str] = None


def _load_service_account() -> Optional[Dict[str, Any]]:
    """Load Firebase service account credentials from env JSON or filesystem."""
    raw_json = (settings.FIREBASE_SERVICE_ACCOUNT_JSON or "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict) and data.get("project_id") and data.get("private_key") and data.get("client_email"):
                return data
        except Exception as exc:
            logger.warning("FCM: Invalid FIREBASE_SERVICE_ACCOUNT_JSON: %s", exc)
            return None

    candidates = []
    if settings.FIREBASE_SERVICE_ACCOUNT_PATH:
        candidates.append(Path(settings.FIREBASE_SERVICE_ACCOUNT_PATH))
    candidates.extend([
        Path("/app/firebase/firebase-service-account.json"),
        Path("./docker/firebase/firebase-service-account.json"),
        Path("./firebase-service-account.json"),
    ])

    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("project_id") and data.get("private_key") and data.get("client_email"):
                    return data
        except Exception as exc:
            logger.warning("FCM: Failed reading %s: %s", path, exc)
    return None


def is_fcm_configured() -> bool:
    """Return True when valid Firebase service account credentials are available."""
    return _load_service_account() is not None


def reset_fcm_token_cache() -> None:
    """Clear cached OAuth2 access token (useful for tests or key rotation)."""
    global _cached_access_token, _cached_expires_at, _cached_project_id
    _cached_access_token = None
    _cached_expires_at = 0.0
    _cached_project_id = None


async def _get_access_token(creds: Dict[str, Any]) -> Tuple[str, str]:
    global _cached_access_token, _cached_expires_at, _cached_project_id

    now = time.time()
    project_id = str(creds["project_id"])
    if _cached_access_token and _cached_project_id == project_id and now < (_cached_expires_at - 120):
        return _cached_access_token, project_id

    async with _token_lock:
        now = time.time()
        if _cached_access_token and _cached_project_id == project_id and now < (_cached_expires_at - 120):
            return _cached_access_token, project_id

        token_uri = str(creds.get("token_uri") or DEFAULT_TOKEN_URI)
        assertion = jwt.encode(
            {
                "iss": creds["client_email"],
                "scope": FCM_SCOPE,
                "aud": token_uri,
                "iat": int(now),
                "exp": int(now) + 3600,
            },
            creds["private_key"],
            algorithm="RS256",
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            resp.raise_for_status()
            token_data = resp.json()

        access_token = str(token_data["access_token"])
        expires_in = int(token_data.get("expires_in", 3600))
        _cached_access_token = access_token
        _cached_expires_at = now + expires_in
        _cached_project_id = project_id
        return access_token, project_id


def _is_token_unregistered(status_code: int, body_text: str) -> bool:
    if status_code == 404:
        return True
    if status_code == 400 and ("UNREGISTERED" in body_text or "registration token is not a valid FCM registration token" in body_text):
        return True
    return "UNREGISTERED" in body_text


async def send_fcm_message(
    device_token: str,
    title: str,
    body: str,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, bool]:
    """
    Send a single FCM HTTP v1 notification to an Android device token.
    Returns (success, is_expired_token).
    """
    creds = _load_service_account()
    if creds is None:
        logger.debug("FCM: Credentials not configured; skipping native Android push.")
        return False, False

    is_high = event_type in HIGH_PRIORITY_EVENTS
    channel_id = "sdgen_alerts" if is_high else "sdgen_events"
    str_data = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
    str_data["title"] = title
    str_data["body"] = body
    str_data["event_type"] = event_type

    payload = {
        "message": {
            "token": device_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": str_data,
            "android": {
                "priority": "HIGH" if is_high else "NORMAL",
                "notification": {
                    "channel_id": channel_id,
                    "sound": "default",
                },
            },
        }
    }

    try:
        access_token, project_id = await _get_access_token(creds)
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
            if resp.status_code == 401:
                reset_fcm_token_cache()
                access_token, project_id = await _get_access_token(creds)
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=payload,
                )

        if 200 <= resp.status_code < 300:
            return True, False

        is_expired = _is_token_unregistered(resp.status_code, resp.text)
        logger.warning(
            "FCM: Push failed for token ...%s (HTTP %s, expired=%s): %s",
            device_token[-8:] if len(device_token) >= 8 else device_token,
            resp.status_code,
            is_expired,
            resp.text[:300],
        )
        return False, is_expired
    except Exception as exc:
        logger.warning("FCM: Exception sending push: %s", exc)
        return False, False
