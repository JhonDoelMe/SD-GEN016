import hashlib
import json
from typing import Any, Awaitable, Callable, Optional, TypeVar
from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.user import User

T = TypeVar("T")


def resolve_idempotency_key(request: Optional[Request], body_key: Optional[str] = None) -> Optional[str]:
    """Extract and sanitize idempotency key from request body or HTTP headers."""
    raw = body_key
    if (not raw or not str(raw).strip()) and request is not None:
        raw = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")
    if not raw:
        return None
    clean = str(raw).strip()
    if not clean:
        return None
    return clean[:64]


def compute_request_hash(payload: Any) -> str:
    """Compute canonical SHA-256 hash of a mutation payload to detect key reuse with altered arguments."""
    encoded = jsonable_encoder(payload)
    canonical = json.dumps(encoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def run_idempotent_endpoint(
    db: AsyncSession,
    request: Optional[Request],
    current_user: User,
    endpoint: str,
    body_data: Any,
    success_status: int,
    action_fn: Callable[[], Awaitable[T]],
) -> Any:
    """
    Execute an endpoint handler idempotently when an idempotency key is provided.
    Returns cached JSONResponse on exact replay or raises HTTP 409 if the same key
    was previously committed with a different payload.
    """
    key = resolve_idempotency_key(request, getattr(body_data, "idempotency_key", None))
    if not key:
        return await action_fn()

    raw_dump = body_data.model_dump(mode="json") if hasattr(body_data, "model_dump") else dict(body_data or {})
    raw_dump.pop("idempotency_key", None)
    req_hash = compute_request_hash(raw_dump)

    existing = (
        await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == current_user.id,
                IdempotencyRecord.endpoint == endpoint,
                IdempotencyRecord.idempotency_key == key,
            )
        )
    ).scalars().first()

    if existing:
        if existing.request_hash != req_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ключ ідемпотентності вже використано з іншими параметрами операції.",
            )
        return JSONResponse(
            status_code=existing.status_code,
            content=json.loads(existing.response_json),
            headers={"X-Idempotency-Replayed": "true"},
        )

    result = await action_fn()

    serialized = json.dumps(jsonable_encoder(result), ensure_ascii=False)
    rec = IdempotencyRecord(
        user_id=current_user.id,
        endpoint=endpoint,
        idempotency_key=key,
        request_hash=req_hash,
        status_code=success_status,
        response_json=serialized,
    )
    db.add(rec)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing_race = (
            await db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == current_user.id,
                    IdempotencyRecord.endpoint == endpoint,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
        ).scalars().first()
        if existing_race:
            if existing_race.request_hash != req_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ключ ідемпотентності вже використано з іншими параметрами операції.",
                )
            return JSONResponse(
                status_code=existing_race.status_code,
                content=json.loads(existing_race.response_json),
                headers={"X-Idempotency-Replayed": "true"},
            )
    return result
