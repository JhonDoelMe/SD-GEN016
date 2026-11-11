"""Facility canister pool accounting & reserve-first fuel deduction logic."""

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.canister import CanisterPool, CanisterTransaction
from backend.app.models.facility import Facility
from backend.app.models.fuel import FuelReceipt, FuelStock, utc_now
from backend.app.schemas.fuel import (
    CanisterDispatchRequest,
    CanisterPoolCreate,
    CanisterPoolOut,
    CanisterPoolUpdate,
    CanisterReceiveRequest,
    CanisterReturnEmptyRequest,
    FuelReceiptCreate,
)
from backend.app.services.audit_service import log_audit
from backend.app.services.fuel_service import (
    add_fuel_receipt,
    normalize_fuel_family,
    to_decimal,
    to_float,
    to_liters,
)


def _pool_available_dec(pool: CanisterPool) -> Decimal:
    return (Decimal(int(pool.full_count)) * to_liters(pool.canister_volume_l)) + to_liters(pool.reserve_liters)


def _validate_pool_invariants(
    full_count: int,
    empty_count: int,
    away_count: int,
    volume_dec: Decimal,
    reserve_dec: Decimal,
) -> int:
    total = int(full_count) + int(empty_count) + int(away_count)
    if total < 0 or full_count < 0 or empty_count < 0 or away_count < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Кількість каністр не може бути від'ємною."
        )
    if volume_dec <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Об'єм однієї каністри має бути більше 0 л."
        )
    if reserve_dec < Decimal("0.000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Залишок у резервній ємності не може бути від'ємним."
        )
    if reserve_dec >= volume_dec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Залишок у резервній ємності ({float(reserve_dec):.2f} л) має бути суворо меншим "
                f"за номінал однієї каністри ({float(volume_dec):.1f} л)."
            )
        )
    return total


def _snapshot_pool(pool: CanisterPool) -> Tuple[int, int, int, Decimal]:
    return (
        int(pool.full_count),
        int(pool.empty_count),
        int(pool.away_refill_count),
        to_liters(pool.reserve_liters),
    )


def _record_canister_tx(
    db: AsyncSession,
    pool: CanisterPool,
    user_id: Optional[int],
    operation: str,
    count: int,
    liters_delta: Decimal,
    used_from_reserve: Decimal,
    before_snap: Tuple[int, int, int, Decimal],
    comment: Optional[str] = None,
    related_transfer_id: Optional[int] = None,
    related_receipt_id: Optional[int] = None,
) -> CanisterTransaction:
    f_b, e_b, a_b, r_b = before_snap
    tx = CanisterTransaction(
        facility_id=pool.facility_id,
        pool_id=pool.id,
        user_id=user_id,
        operation=operation,
        count=int(count),
        liters_delta=liters_delta,
        used_from_reserve_l=used_from_reserve,
        full_before=f_b,
        full_after=int(pool.full_count),
        empty_before=e_b,
        empty_after=int(pool.empty_count),
        away_before=a_b,
        away_after=int(pool.away_refill_count),
        reserve_before=r_b,
        reserve_after=to_liters(pool.reserve_liters),
        related_transfer_id=related_transfer_id,
        related_receipt_id=related_receipt_id,
        comment=comment,
    )
    db.add(tx)
    return tx


async def sync_stock_balance_from_pools(db: AsyncSession, stock: FuelStock) -> Optional[Decimal]:
    """
    If stock has active canister pool(s), recompute FuelStock.current_balance_l
    directly from sum(full_count * canister_volume_l + reserve_liters).
    Returns None if the stock has no active pools.
    """
    res = await db.execute(
        select(CanisterPool).where(CanisterPool.stock_id == stock.id, CanisterPool.is_active == True)  # noqa: E712
    )
    pools = res.scalars().all()
    if not pools:
        return None
    total = sum((_pool_available_dec(p) for p in pools), Decimal("0.000"))
    stock.current_balance_l = to_liters(total)
    stock.updated_at = utc_now()
    return total


async def get_stock_canister_aggregates(
    db: AsyncSession, stock_ids: List[int]
) -> Dict[int, Dict[str, float]]:
    """Aggregate active canister counts & reserve per FuelStock ID in one query."""
    if not stock_ids:
        return {}
    res = await db.execute(
        select(CanisterPool).where(
            CanisterPool.stock_id.in_(stock_ids),
            CanisterPool.is_active == True,  # noqa: E712
        )
    )
    agg: Dict[int, Dict[str, float]] = {}
    for p in res.scalars().all():
        entry = agg.setdefault(
            int(p.stock_id),
            {
                "has_canister_pools": True,
                "canisters_total": 0,
                "canisters_full": 0,
                "canisters_empty": 0,
                "canisters_away": 0,
                "canister_reserve_l": 0.0,
            },
        )
        entry["canisters_total"] += int(p.total_count)
        entry["canisters_full"] += int(p.full_count)
        entry["canisters_empty"] += int(p.empty_count)
        entry["canisters_away"] += int(p.away_refill_count)
        entry["canister_reserve_l"] = round(entry["canister_reserve_l"] + float(p.reserve_liters), 3)
    return agg


def to_pool_out(pool: CanisterPool) -> CanisterPoolOut:
    avail = _pool_available_dec(pool)
    return CanisterPoolOut(
        id=pool.id,
        facility_id=pool.facility_id,
        facility_name=pool.facility.name if pool.facility else None,
        stock_id=pool.stock_id,
        stock_name=pool.stock.name if pool.stock else None,
        name=pool.name,
        fuel_type=pool.fuel_type,
        canister_volume_l=to_float(pool.canister_volume_l, 2),
        total_count=int(pool.total_count),
        full_count=int(pool.full_count),
        empty_count=int(pool.empty_count),
        away_refill_count=int(pool.away_refill_count),
        reserve_liters=to_float(pool.reserve_liters, 3),
        available_liters=to_float(avail, 3),
        is_active=bool(pool.is_active),
        updated_at=pool.updated_at,
    )


async def list_canister_pools(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    include_inactive: bool = False,
) -> List[CanisterPool]:
    q = select(CanisterPool).options(
        selectinload(CanisterPool.facility),
        selectinload(CanisterPool.stock),
    ).order_by(CanisterPool.id.asc())
    if facility_id is not None:
        q = q.where(CanisterPool.facility_id == facility_id)
    if not include_inactive:
        q = q.where(CanisterPool.is_active == True)  # noqa: E712
    return list((await db.execute(q)).scalars().all())


async def create_canister_pool(
    db: AsyncSession,
    data: CanisterPoolCreate,
    user_id: int,
    ip_address: Optional[str] = None,
) -> CanisterPool:
    fac = await db.get(Facility, data.facility_id)
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Об'єкт не знайдено")

    stock = (
        await db.execute(select(FuelStock).where(FuelStock.id == data.stock_id).with_for_update())
    ).scalars().first()
    if not stock or not stock.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активний склад ГСМ не знайдено")
    if int(stock.facility_id) != int(data.facility_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Склад ГСМ належить до іншого об'єкта."
        )

    vol_dec = to_decimal(data.canister_volume_l, 2)
    res_dec = to_liters(data.reserve_liters)
    total = _validate_pool_invariants(
        data.full_count, data.empty_count, data.away_refill_count, vol_dec, res_dec
    )

    pool = CanisterPool(
        facility_id=data.facility_id,
        stock_id=stock.id,
        name=data.name.strip(),
        fuel_type=stock.fuel_type,
        canister_volume_l=vol_dec,
        total_count=total,
        full_count=data.full_count,
        empty_count=data.empty_count,
        away_refill_count=data.away_refill_count,
        reserve_liters=res_dec,
        is_active=True,
    )
    db.add(pool)
    await db.flush()

    pool_avail = _pool_available_dec(pool)
    _record_canister_tx(
        db=db,
        pool=pool,
        user_id=user_id,
        operation="POOL_CREATED",
        count=total,
        liters_delta=pool_avail,
        used_from_reserve=Decimal("0.000"),
        before_snap=(0, 0, 0, Decimal("0.000")),
        comment=f"Створено пул каністр ({total} × {float(vol_dec):.0f} л)",
    )
    await sync_stock_balance_from_pools(db, stock)

    await log_audit(
        db=db,
        action="CANISTER_POOL_CREATED",
        entity_type="CanisterPool",
        entity_id=str(pool.id),
        user_id=user_id,
        details={
            "facility_id": pool.facility_id,
            "stock_id": pool.stock_id,
            "name": pool.name,
            "canister_volume_l": float(vol_dec),
            "total_count": total,
            "full_count": pool.full_count,
            "empty_count": pool.empty_count,
            "away_refill_count": pool.away_refill_count,
            "reserve_liters": float(res_dec),
        },
        ip_address=ip_address,
    )
    await db.commit()

    return (
        await db.execute(
            select(CanisterPool)
            .options(selectinload(CanisterPool.facility), selectinload(CanisterPool.stock))
            .where(CanisterPool.id == pool.id)
        )
    ).scalars().first()


async def update_canister_pool(
    db: AsyncSession,
    pool_id: int,
    data: CanisterPoolUpdate,
    user_id: int,
    ip_address: Optional[str] = None,
) -> CanisterPool:
    pool = (
        await db.execute(select(CanisterPool).where(CanisterPool.id == pool_id).with_for_update())
    ).scalars().first()
    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пул каністр не знайдено")

    stock = (
        await db.execute(select(FuelStock).where(FuelStock.id == pool.stock_id).with_for_update())
    ).scalars().first()

    before_snap = _snapshot_pool(pool)
    old_avail = _pool_available_dec(pool)

    if data.name is not None and data.name.strip():
        pool.name = data.name.strip()

    new_vol = to_decimal(data.canister_volume_l, 2) if data.canister_volume_l is not None else to_decimal(pool.canister_volume_l, 2)
    new_full = data.full_count if data.full_count is not None else int(pool.full_count)
    new_empty = data.empty_count if data.empty_count is not None else int(pool.empty_count)
    new_away = data.away_refill_count if data.away_refill_count is not None else int(pool.away_refill_count)
    new_res = to_liters(data.reserve_liters) if data.reserve_liters is not None else to_liters(pool.reserve_liters)

    new_total = _validate_pool_invariants(new_full, new_empty, new_away, new_vol, new_res)

    pool.canister_volume_l = new_vol
    pool.full_count = new_full
    pool.empty_count = new_empty
    pool.away_refill_count = new_away
    pool.total_count = new_total
    pool.reserve_liters = new_res
    if data.is_active is not None:
        pool.is_active = data.is_active
    pool.updated_at = utc_now()
    await db.flush()

    new_avail = _pool_available_dec(pool)
    _record_canister_tx(
        db=db,
        pool=pool,
        user_id=user_id,
        operation="POOL_CONFIGURED",
        count=new_total,
        liters_delta=new_avail - old_avail,
        used_from_reserve=Decimal("0.000"),
        before_snap=before_snap,
        comment="Оновлення складу / інвентаризація каністр",
    )

    if stock:
        await sync_stock_balance_from_pools(db, stock)

    await log_audit(
        db=db,
        action="CANISTER_POOL_UPDATED",
        entity_type="CanisterPool",
        entity_id=str(pool.id),
        user_id=user_id,
        details={
            "facility_id": pool.facility_id,
            "stock_id": pool.stock_id,
            "full_count": pool.full_count,
            "empty_count": pool.empty_count,
            "away_refill_count": pool.away_refill_count,
            "total_count": pool.total_count,
            "reserve_liters": float(pool.reserve_liters),
        },
        ip_address=ip_address,
    )
    await db.commit()

    return (
        await db.execute(
            select(CanisterPool)
            .options(selectinload(CanisterPool.facility), selectinload(CanisterPool.stock))
            .where(CanisterPool.id == pool.id)
        )
    ).scalars().first()


async def delete_canister_pool(
    db: AsyncSession,
    pool_id: int,
    user_id: int,
    ip_address: Optional[str] = None,
) -> dict:
    pool = (
        await db.execute(select(CanisterPool).where(CanisterPool.id == pool_id).with_for_update())
    ).scalars().first()
    if not pool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пул каністр не знайдено")

    avail = _pool_available_dec(pool)
    if avail > Decimal("0.000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неможливо видалити пул каністр із залишком палива ({float(avail):.1f} л). Спочатку спишіть або обнуліть залишок."
        )

    stock = await db.get(FuelStock, pool.stock_id)
    pool_name = pool.name
    facility_id = pool.facility_id
    await db.delete(pool)
    await db.flush()

    if stock:
        await sync_stock_balance_from_pools(db, stock)

    await log_audit(
        db=db,
        action="CANISTER_POOL_DELETED",
        entity_type="CanisterPool",
        entity_id=str(pool_id),
        user_id=user_id,
        details={"facility_id": facility_id, "name": pool_name},
        ip_address=ip_address,
    )
    await db.commit()
    return {"status": "ok", "detail": f"Пул каністр '{pool_name}' видалено"}


async def dispatch_canisters(
    db: AsyncSession,
    pool_id: int,
    data: CanisterDispatchRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> CanisterPool:
    """Send empty canisters out for refilling (`empty_count` -> `away_refill_count`)."""
    pool = (
        await db.execute(select(CanisterPool).where(CanisterPool.id == pool_id).with_for_update())
    ).scalars().first()
    if not pool or not pool.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активний пул каністр не знайдено")

    if data.count > int(pool.empty_count):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Доступно лише {pool.empty_count} порожніх каністр для відправки на заправку (запитано {data.count})."
        )

    before_snap = _snapshot_pool(pool)
    pool.empty_count -= data.count
    pool.away_refill_count += data.count
    pool.updated_at = utc_now()
    await db.flush()

    _record_canister_tx(
        db=db,
        pool=pool,
        user_id=user_id,
        operation="DISPATCH_REFILL",
        count=data.count,
        liters_delta=Decimal("0.000"),
        used_from_reserve=Decimal("0.000"),
        before_snap=before_snap,
        comment=data.comment or f"Віддано на заправку {data.count} шт.",
    )
    await log_audit(
        db=db,
        action="CANISTER_DISPATCHED",
        entity_type="CanisterPool",
        entity_id=str(pool.id),
        user_id=user_id,
        details={
            "facility_id": pool.facility_id,
            "count": data.count,
            "empty_after": pool.empty_count,
            "away_after": pool.away_refill_count,
            "comment": data.comment,
        },
        ip_address=ip_address,
    )
    await db.commit()
    return (
        await db.execute(
            select(CanisterPool)
            .options(selectinload(CanisterPool.facility), selectinload(CanisterPool.stock))
            .where(CanisterPool.id == pool.id)
        )
    ).scalars().first()


async def return_empty_canisters(
    db: AsyncSession,
    pool_id: int,
    data: CanisterReturnEmptyRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> CanisterPool:
    """Return dispatched canisters back unfilled (`away_refill_count` -> `empty_count`)."""
    pool = (
        await db.execute(select(CanisterPool).where(CanisterPool.id == pool_id).with_for_update())
    ).scalars().first()
    if not pool or not pool.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активний пул каністр не знайдено")

    if data.count > int(pool.away_refill_count):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"На заправці перебуває лише {pool.away_refill_count} каністр (вказано {data.count})."
        )

    before_snap = _snapshot_pool(pool)
    pool.away_refill_count -= data.count
    pool.empty_count += data.count
    pool.updated_at = utc_now()
    await db.flush()

    _record_canister_tx(
        db=db,
        pool=pool,
        user_id=user_id,
        operation="RETURN_EMPTY",
        count=data.count,
        liters_delta=Decimal("0.000"),
        used_from_reserve=Decimal("0.000"),
        before_snap=before_snap,
        comment=data.comment or f"Повернуто порожніми без заправки {data.count} шт.",
    )
    await log_audit(
        db=db,
        action="CANISTER_RETURNED_EMPTY",
        entity_type="CanisterPool",
        entity_id=str(pool.id),
        user_id=user_id,
        details={
            "facility_id": pool.facility_id,
            "count": data.count,
            "empty_after": pool.empty_count,
            "away_after": pool.away_refill_count,
            "comment": data.comment,
        },
        ip_address=ip_address,
    )
    await db.commit()
    return (
        await db.execute(
            select(CanisterPool)
            .options(selectinload(CanisterPool.facility), selectinload(CanisterPool.stock))
            .where(CanisterPool.id == pool.id)
        )
    ).scalars().first()


async def receive_canisters(
    db: AsyncSession,
    pool_id: int,
    data: CanisterReceiveRequest,
    user_id: int,
    ip_address: Optional[str] = None,
    user_permissions: Optional[List[str]] = None,
    is_admin: bool = False,
) -> CanisterPool:
    """
    Bring filled canisters back to the facility (`away_refill_count` or `empty_count` -> `full_count`),
    optionally create a matching FuelReceipt, and sync FuelStock balance.
    """
    pool = (
        await db.execute(select(CanisterPool).where(CanisterPool.id == pool_id).with_for_update())
    ).scalars().first()
    if not pool or not pool.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активний пул каністр не знайдено")

    stock = (
        await db.execute(select(FuelStock).where(FuelStock.id == pool.stock_id).with_for_update())
    ).scalars().first()
    if not stock or not stock.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пов'язаний склад ГСМ не знайдено або архівовано.")

    if data.source == "away":
        if data.count > int(pool.away_refill_count):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"На заправці очікується {pool.away_refill_count} каністр (неможливо прийняти {data.count})."
            )
    else:
        if data.count > int(pool.empty_count):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"На об'єкті лише {pool.empty_count} порожніх каністр (неможливо прийняти {data.count})."
            )

    added_liters = to_liters(Decimal(data.count) * to_decimal(pool.canister_volume_l, 2))
    receipt_id: Optional[int] = None

    if data.create_receipt:
        rec_no = (data.receipt_number or "").strip() or f"КАН-{int(utc_now().timestamp())}"
        rec_payload = FuelReceiptCreate(
            facility_id=pool.facility_id,
            stock_id=pool.stock_id,
            canister_pool_id=pool.id,
            fuel_provider=data.fuel_provider,
            fuel_type=pool.fuel_type,
            liters=float(added_liters),
            cost_total=data.cost_total,
            price_per_liter=data.price_per_liter,
            driver_name=data.driver_name,
            receipt_number=rec_no,
            comment=data.comment or f"Заправка {data.count} каністр × {float(pool.canister_volume_l):.0f} л",
            force_confirm=data.force_confirm,
            idempotency_key=data.idempotency_key,
        )
        # Skip direct receipt auto-conversion & commit since receive_canisters commits atomically
        receipt = await add_fuel_receipt(
            db=db,
            receipt_data=rec_payload,
            user_id=user_id,
            ip_address=ip_address,
            user_permissions=user_permissions,
            is_admin=is_admin,
            _skip_canister_sync=True,
            _auto_commit=False,
        )
        receipt_id = receipt.id

    before_snap = _snapshot_pool(pool)
    if data.source == "away":
        pool.away_refill_count -= data.count
    else:
        pool.empty_count -= data.count
    pool.full_count += data.count
    pool.updated_at = utc_now()
    await db.flush()

    _record_canister_tx(
        db=db,
        pool=pool,
        user_id=user_id,
        operation="RECEIVE_REFILL",
        count=data.count,
        liters_delta=added_liters,
        used_from_reserve=Decimal("0.000"),
        before_snap=before_snap,
        related_receipt_id=receipt_id,
        comment=data.comment or f"Привезено з заправки {data.count} каністр (+{float(added_liters):.1f} л)",
    )
    await sync_stock_balance_from_pools(db, stock)

    await log_audit(
        db=db,
        action="CANISTER_RECEIVED",
        entity_type="CanisterPool",
        entity_id=str(pool.id),
        user_id=user_id,
        details={
            "facility_id": pool.facility_id,
            "count": data.count,
            "source": data.source,
            "added_liters": float(added_liters),
            "full_after": pool.full_count,
            "away_after": pool.away_refill_count,
            "related_receipt_id": receipt_id,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return (
        await db.execute(
            select(CanisterPool)
            .options(selectinload(CanisterPool.facility), selectinload(CanisterPool.stock))
            .where(CanisterPool.id == pool.id)
        )
    ).scalars().first()


async def consume_from_canister_pool_for_transfer(
    db: AsyncSession,
    stock: FuelStock,
    liters: Decimal,
    user_id: int,
    transfer_id: int,
    canister_pool_id: Optional[int] = None,
) -> Optional[Tuple[Decimal, int, Decimal]]:
    """
    Consume fuel from an active canister pool attached to `stock`:
    1. Reserve vessel is drained FIRST (`used_from_reserve = min(reserve, liters)`).
    2. Remaining fuel opens `ceil(remaining / canister_volume_l)` full canisters.
    3. Opened canisters immediately become empty (`full -= opened, empty += opened`).
    4. Any leftover stays in `reserve_liters` (`< canister_volume_l`).
    Returns `(used_from_reserve_dec, opened_count, new_reserve_dec)`, or None if no active pool exists.
    """
    q = select(CanisterPool).where(
        CanisterPool.stock_id == stock.id,
        CanisterPool.is_active == True,  # noqa: E712
    ).order_by(CanisterPool.id.asc()).with_for_update()
    pools = list((await db.execute(q)).scalars().all())
    if not pools:
        return None

    target: Optional[CanisterPool] = None
    if canister_pool_id is not None:
        target = next((p for p in pools if int(p.id) == int(canister_pool_id)), None)
        if not target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Обраний пул каністр не належить до цього складу або неактивний."
            )
        if _pool_available_dec(target) < liters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"У пулі '{target.name}' недостатньо палива: доступно {float(_pool_available_dec(target)):.1f} л "
                    f"({target.full_count} каністр + {float(target.reserve_liters):.1f} л резерву), запитано {float(liters):.1f} л."
                )
            )
    else:
        for p in pools:
            if _pool_available_dec(p) >= liters:
                target = p
                break
        if target is None:
            max_single = max((_pool_available_dec(p) for p in pools), default=Decimal("0.000"))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"У жодному пулі каністр складу '{stock.name}' недостатньо палива для одного списання "
                    f"(макс. в одному пулі: {float(max_single):.1f} л, запитано: {float(liters):.1f} л)."
                )
            )

    before_snap = _snapshot_pool(target)
    vol_dec = to_decimal(target.canister_volume_l, 2)
    reserve_dec = to_liters(target.reserve_liters)

    used_from_reserve = min(reserve_dec, liters)
    need_from_canisters = liters - used_from_reserve

    if need_from_canisters > Decimal("0.000"):
        q_cnt, rem_mod = divmod(need_from_canisters, vol_dec)
        opened = int(q_cnt) + (1 if rem_mod > Decimal("0.000") else 0)
        if opened > int(target.full_count):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Недостатньо повних каністр у пулі '{target.name}' (потрібно {opened}, є {target.full_count})."
            )
        new_reserve = to_liters((Decimal(opened) * vol_dec) - need_from_canisters)
        target.full_count -= opened
        target.empty_count += opened
    else:
        opened = 0
        new_reserve = to_liters(reserve_dec - liters)

    target.reserve_liters = new_reserve
    target.updated_at = utc_now()
    await db.flush()

    breakdown_parts = []
    if used_from_reserve > Decimal("0.000"):
        breakdown_parts.append(f"{float(used_from_reserve):.1f} л з резерву")
    if opened > 0:
        breakdown_parts.append(f"{opened} кан. × {float(vol_dec):.0f} л")
    comment_note = " + ".join(breakdown_parts) if breakdown_parts else f"{float(liters):.1f} л"

    _record_canister_tx(
        db=db,
        pool=target,
        user_id=user_id,
        operation="CONSUME_TRANSFER",
        count=opened,
        liters_delta=-liters,
        used_from_reserve=used_from_reserve,
        before_snap=before_snap,
        related_transfer_id=transfer_id,
        comment=f"Заправка бака: {comment_note} (новий резерв: {float(new_reserve):.1f} л)",
    )
    await sync_stock_balance_from_pools(db, stock)
    return used_from_reserve, opened, new_reserve


async def apply_direct_receipt_to_canister_pool(
    db: AsyncSession,
    stock: FuelStock,
    liters: Decimal,
    user_id: int,
    receipt_id: int,
    canister_pool_id: Optional[int] = None,
) -> None:
    """
    Enforce canister storage constraints when POST /fuel/receipt is used directly on
    a canister-managed FuelStock: fuel must fit exact integer canisters across
    (away_refill_count + empty_count).
    """
    q = select(CanisterPool).where(
        CanisterPool.stock_id == stock.id,
        CanisterPool.is_active == True,  # noqa: E712
    ).order_by(CanisterPool.id.asc()).with_for_update()
    pools = list((await db.execute(q)).scalars().all())
    if not pools:
        return

    target = (
        next((p for p in pools if int(p.id) == int(canister_pool_id)), None)
        if canister_pool_id is not None
        else pools[0]
    )
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обраний пул каністр не належить до цього складу або неактивний."
        )

    if normalize_fuel_family(stock.fuel_type) != normalize_fuel_family(target.fuel_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Невідповідність типу палива для пулу '{target.name}': "
                f"каністри призначені для '{target.fuel_type}', а чек на '{stock.fuel_type}'."
            )
        )

    vol_dec = to_decimal(target.canister_volume_l, 2)
    q_cnt, rem_mod = divmod(liters, vol_dec)
    if rem_mod > Decimal("0.000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Склад '{stock.name}' зберігає пальне лише в каністрах по {float(vol_dec):.0f} л (резервуару немає). "
                f"Введіть кратний об'єм (напр., {float(vol_dec):.0f}, {float(vol_dec * 2):.0f} л) "
                f"або скористайтесь кнопкою прийому каністр."
            )
        )

    needed = int(q_cnt)
    fillable = int(target.away_refill_count) + int(target.empty_count)
    if needed > fillable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"У пулі '{target.name}' доступно лише {fillable} вільних каністр для заповнення "
                f"(на АЗС: {target.away_refill_count}, порожніх: {target.empty_count}; запитано {needed} шт.)."
            )
        )

    before_snap = _snapshot_pool(target)
    from_away = min(needed, int(target.away_refill_count))
    from_empty = needed - from_away
    target.away_refill_count -= from_away
    target.empty_count -= from_empty
    target.full_count += needed
    target.updated_at = utc_now()
    await db.flush()

    _record_canister_tx(
        db=db,
        pool=target,
        user_id=user_id,
        operation="DIRECT_RECEIPT",
        count=needed,
        liters_delta=liters,
        used_from_reserve=Decimal("0.000"),
        before_snap=before_snap,
        related_receipt_id=receipt_id,
        comment=f"Оприбуткування на склад → +{needed} повних каністр",
    )
    await sync_stock_balance_from_pools(db, stock)


async def list_canister_transactions(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    pool_id: Optional[int] = None,
    limit: int = 50,
) -> List[CanisterTransaction]:
    q = (
        select(CanisterTransaction)
        .options(selectinload(CanisterTransaction.pool), selectinload(CanisterTransaction.user))
        .order_by(CanisterTransaction.id.desc())
        .limit(limit)
    )
    if facility_id is not None:
        q = q.where(CanisterTransaction.facility_id == facility_id)
    if pool_id is not None:
        q = q.where(CanisterTransaction.pool_id == pool_id)
    return list((await db.execute(q)).scalars().all())
