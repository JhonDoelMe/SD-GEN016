import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import to_facility_time, now_facility, utc_now
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.fuel import FuelStock, FuelTransfer
from backend.app.models.canister import CanisterPool, CanisterTransaction
from backend.app.models.measurement import FuelMeasurement
from backend.app.models.user import User
from backend.app.schemas.measurement import (
    MeasurementCancelRequest,
    MeasurementFinishEmptyRequest,
    MeasurementInventoryRequest,
    MeasurementStartRequest,
    MeasurementStatusEnvelope,
    MeasurementSummaryOut,
    MeasurementTransferItemOut,
)
from backend.app.services.audit_service import log_audit
from backend.app.services.fuel_service import to_decimal, to_float, to_liters
from backend.app.services.canister_service import (
    _pool_available_dec,
    _record_canister_tx,
    _snapshot_pool,
    _validate_pool_invariants,
    sync_stock_balance_from_pools,
)
from backend.app.services.settings_service import get_runtime_setting


ACTIVE_MEASUREMENT_STATUSES = ("MEASURING", "PENDING_INVENTORY", "PENDING_APPROVAL")
LOCKED_MEASUREMENT_STATUSES = ("PENDING_INVENTORY", "PENDING_APPROVAL")


async def get_active_facility_measurement(
    db: AsyncSession,
    facility_id: Optional[int],
) -> Optional[FuelMeasurement]:
    if not facility_id:
        return None
    res = await db.execute(
        select(FuelMeasurement)
        .where(
            FuelMeasurement.facility_id == facility_id,
            FuelMeasurement.status.in_(ACTIVE_MEASUREMENT_STATUSES),
        )
        .order_by(FuelMeasurement.id.desc())
        .limit(1)
    )
    return res.scalars().first()


async def is_generator_in_measurement_mode(
    db: AsyncSession,
    generator_id: int,
) -> bool:
    res = await db.execute(
        select(FuelMeasurement.id)
        .where(
            FuelMeasurement.generator_id == generator_id,
            FuelMeasurement.status == "MEASURING",
        )
        .limit(1)
    )
    return res.scalars().first() is not None


async def ensure_facility_not_locked_by_measurement(
    db: AsyncSession,
    facility_id: Optional[int],
    operation_kind: str = "general",
) -> Optional[FuelMeasurement]:
    """
    Enforce measurement mode locks per facility:
    - PENDING_INVENTORY / PENDING_APPROVAL blocks ALL operational mutations and adjustments.
    - MEASURING permits normal fuel/generator operations while blocking ALL fuel/consumption adjustments.
    """
    active = await get_active_facility_measurement(db, facility_id)
    if not active:
        return None

    if active.status in LOCKED_MEASUREMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Операції на об'єкті заблоковано: контрольний замір завершено, "
                "очікується інвентаризація комісією, формування PDF-відомості та погодження Суперадміністратором."
            ),
        )

    if active.status == "MEASURING" and operation_kind == "fuel_adjustment":
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "У режимі вимірювання будь-які системні коригування палива, пулів каністр або норми розходу "
                "суворо заборонені до завершення заміру та інвентаризації!"
            ),
        )

    return active


async def increment_active_measurement_added_fuel(
    db: AsyncSession,
    generator_id: int,
    liters_dec: Decimal,
) -> None:
    res = await db.execute(
        select(FuelMeasurement)
        .where(
            FuelMeasurement.generator_id == generator_id,
            FuelMeasurement.status == "MEASURING",
        )
        .with_for_update()
    )
    m = res.scalars().first()
    if m:
        m.added_during_measurement_l = to_liters(m.added_during_measurement_l) + liters_dec
        m.updated_at = utc_now()


async def _load_facility_book_state(db: AsyncSession, facility_id: int) -> tuple[list[dict], list[dict]]:
    stocks = list(
        (
            await db.execute(
                select(FuelStock)
                .where(FuelStock.facility_id == facility_id, FuelStock.is_active == True)  # noqa: E712
                .order_by(FuelStock.id.asc())
            )
        ).scalars().all()
    )
    pools = list(
        (
            await db.execute(
                select(CanisterPool)
                .where(CanisterPool.facility_id == facility_id, CanisterPool.is_active == True)  # noqa: E712
                .order_by(CanisterPool.id.asc())
            )
        ).scalars().all()
    )
    pools_by_stock = {int(p.stock_id) for p in pools}
    stocks_data = [
        {
            "stock_id": int(s.id),
            "stock_name": s.name,
            "fuel_type": s.fuel_type,
            "book_balance_l": round(float(s.current_balance_l or 0.0), 3),
            "has_canister_pools": int(s.id) in pools_by_stock,
        }
        for s in stocks
    ]
    pools_data = [
        {
            "pool_id": int(p.id),
            "stock_id": int(p.stock_id),
            "pool_name": p.name,
            "fuel_type": p.fuel_type,
            "canister_volume_l": round(float(p.canister_volume_l or 20.0), 2),
            "total_count": int(p.total_count),
            "book_full": int(p.full_count),
            "book_empty": int(p.empty_count),
            "book_away": int(p.away_refill_count),
            "book_reserve_l": round(float(p.reserve_liters or 0.0), 3),
            "book_total_l": round(float(_pool_available_dec(p)), 3),
        }
        for p in pools
    ]
    return stocks_data, pools_data


async def _build_measurement_summary(db: AsyncSession, m: FuelMeasurement) -> MeasurementSummaryOut:
    res = await db.execute(
        select(FuelMeasurement)
        .options(
            selectinload(FuelMeasurement.facility),
            selectinload(FuelMeasurement.generator),
            selectinload(FuelMeasurement.started_by),
            selectinload(FuelMeasurement.approved_by),
        )
        .where(FuelMeasurement.id == m.id)
    )
    m_full = res.scalars().first() or m
    fac = m_full.facility or await db.get(Facility, m_full.facility_id)
    gen = m_full.generator or await db.get(Generator, m_full.generator_id)

    active_run = (
        await db.execute(
            select(GeneratorRun)
            .where(GeneratorRun.generator_id == m_full.generator_id, GeneratorRun.status == "RUNNING")
            .order_by(GeneratorRun.id.desc())
            .limit(1)
        )
    ).scalars().first()

    live_op_hours = float(gen.current_operating_hours or 0.0) if gen else float(m_full.start_operating_hours)
    if active_run and active_run.start_time and m_full.status == "MEASURING":
        live_op_hours += max(0.0, (utc_now() - active_run.start_time).total_seconds() / 3600.0)
    live_op_hours = round(live_op_hours, 2)

    start_tank = float(m_full.start_tank_level_l or 0.0)
    added_l = float(m_full.added_during_measurement_l or 0.0)
    total_measured = round(start_tank + added_l, 2)
    min_thresh = float(m_full.min_liters_threshold or 100.0)
    rem_to_min = round(max(0.0, min_thresh - total_measured), 2)
    progress_pct = round(min(100.0, (total_measured / min_thresh) * 100.0), 1) if min_thresh > 0 else 100.0

    elapsed_h = (
        float(m_full.total_hours_elapsed)
        if m_full.total_hours_elapsed is not None
        else round(max(0.0, live_op_hours - float(m_full.start_operating_hours)), 2)
    )
    est_cons = (
        float(m_full.calculated_consumption_l_per_h)
        if m_full.calculated_consumption_l_per_h is not None
        else (round(total_measured / elapsed_h, 3) if elapsed_h > 0.05 else None)
    )

    end_bound = m_full.tank_emptied_at or utc_now()
    tr_rows = list(
        (
            await db.execute(
                select(FuelTransfer)
                .options(selectinload(FuelTransfer.stock), selectinload(FuelTransfer.user))
                .where(
                    FuelTransfer.generator_id == m_full.generator_id,
                    FuelTransfer.created_at >= m_full.started_at,
                    FuelTransfer.created_at <= end_bound,
                )
                .order_by(FuelTransfer.id.asc())
            )
        ).scalars().all()
    )
    transfers_out = [
        MeasurementTransferItemOut(
            id=tr.id,
            created_at=tr.created_at,
            liters=round(float(tr.liters or 0.0), 2),
            stock_name=tr.stock.name if tr.stock else "Склад ГСМ",
            operator_name=(tr.user.full_name or tr.user.login) if tr.user else None,
            comment=tr.comment,
        )
        for tr in tr_rows
    ]

    stocks_data, pools_data = await _load_facility_book_state(db, m_full.facility_id)

    comm_members = []
    if m_full.commission_members_json:
        try:
            comm_members = json.loads(m_full.commission_members_json)
        except Exception:
            comm_members = []

    inv_fact = None
    if m_full.inventory_fact_json:
        try:
            inv_fact = json.loads(m_full.inventory_fact_json)
        except Exception:
            inv_fact = None

    return MeasurementSummaryOut(
        id=m_full.id,
        facility_id=m_full.facility_id,
        facility_name=fac.name if fac else None,
        generator_id=m_full.generator_id,
        generator_name=gen.name if gen else None,
        generator_model=gen.model if gen else None,
        fuel_type=gen.fuel_type if gen else None,
        tank_capacity_l=round(float(gen.tank_capacity_l or 0.0), 2) if gen else start_tank,
        status=m_full.status,
        started_at=m_full.started_at,
        started_by_name=(m_full.started_by.full_name or m_full.started_by.login) if m_full.started_by else None,
        start_operating_hours=round(float(m_full.start_operating_hours), 2),
        current_operating_hours=live_op_hours,
        start_tank_level_l=round(start_tank, 2),
        added_during_measurement_l=round(added_l, 2),
        measured_liters_total=total_measured,
        min_liters_threshold=round(min_thresh, 2),
        liters_remaining_to_min=rem_to_min,
        progress_pct=progress_pct,
        can_finish_empty=(m_full.status == "MEASURING" and total_measured + 1e-6 >= min_thresh and active_run is None),
        is_generator_running=(active_run is not None),
        elapsed_hours=elapsed_h,
        old_nominal_consumption_l_per_h=round(float(m_full.old_nominal_consumption_l_per_h), 3),
        est_consumption_l_per_h=est_cons,
        tank_emptied_at=m_full.tank_emptied_at,
        end_operating_hours=m_full.end_operating_hours,
        total_fuel_consumed_l=round(float(m_full.total_fuel_consumed_l), 2) if m_full.total_fuel_consumed_l is not None else None,
        total_hours_elapsed=m_full.total_hours_elapsed,
        calculated_consumption_l_per_h=m_full.calculated_consumption_l_per_h,
        statement_number=m_full.statement_number,
        inventory_entered_at=m_full.inventory_entered_at,
        document_generated_at=m_full.document_generated_at,
        document_downloaded_at=m_full.document_downloaded_at,
        can_approve=(m_full.status == "PENDING_APPROVAL" and m_full.document_downloaded_at is not None),
        approved_at=m_full.approved_at,
        approved_by_name=(m_full.approved_by.full_name or m_full.approved_by.login) if m_full.approved_by else None,
        cancelled_at=m_full.cancelled_at,
        cancel_reason=m_full.cancel_reason,
        commission_members=comm_members,
        inventory_fact=inv_fact,
        transfers=transfers_out,
        current_stocks=stocks_data,
        current_pools=pools_data,
    )


async def get_measurement_status_envelope(
    db: AsyncSession,
    facility_id: Optional[int],
) -> MeasurementStatusEnvelope:
    active = await get_active_facility_measurement(db, facility_id)
    if active:
        summary = await _build_measurement_summary(db, active)
        locked = active.status in LOCKED_MEASUREMENT_STATUSES
        measuring = active.status == "MEASURING"
        reason = None
        if locked:
            reason = "Вимірювання завершено: очікується інвентаризація комісією та погодження Суперадміністратором."
        return MeasurementStatusEnvelope(
            has_active=True,
            is_locked=locked,
            is_measuring=measuring,
            lock_reason=reason,
            active=summary,
            latest_completed=None,
        )

    latest_completed = None
    if facility_id:
        done_res = await db.execute(
            select(FuelMeasurement)
            .where(
                FuelMeasurement.facility_id == facility_id,
                FuelMeasurement.status == "APPROVED",
            )
            .order_by(FuelMeasurement.id.desc())
            .limit(1)
        )
        done_m = done_res.scalars().first()
        if done_m:
            latest_completed = await _build_measurement_summary(db, done_m)

    return MeasurementStatusEnvelope(
        has_active=False,
        is_locked=False,
        is_measuring=False,
        lock_reason=None,
        active=None,
        latest_completed=latest_completed,
    )


async def list_measurements_history(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    limit: int = 30,
) -> List[MeasurementSummaryOut]:
    q = select(FuelMeasurement).order_by(FuelMeasurement.id.desc()).limit(limit)
    if facility_id is not None:
        q = q.where(FuelMeasurement.facility_id == facility_id)
    rows = list((await db.execute(q)).scalars().all())
    return [await _build_measurement_summary(db, row) for row in rows]


async def start_measurement(
    db: AsyncSession,
    data: MeasurementStartRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> MeasurementSummaryOut:
    gen = (
        await db.execute(select(Generator).where(Generator.id == data.generator_id).with_for_update())
    ).scalars().first()
    if not gen or not getattr(gen, "is_active", True) or gen.status == "ARCHIVED":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Активний генератор не знайдено")

    facility_id = int(data.facility_id or gen.facility_id or 1)
    if gen.facility_id and int(gen.facility_id) != facility_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Генератор належить до іншого об'єкта.")

    existing = await get_active_facility_measurement(db, facility_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"На об'єкті вже триває режим вимірювання (ID #{existing.id}, статус: {existing.status}).",
        )

    if gen.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Перед увімкненням режиму вимірювання зупиніть генератор і заправте бак до повного.",
        )
    if gen.status in ("BLOCKED", "FAULTY"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо запустити вимірювання: генератор заблокований або несправний.",
        )

    cap = float(gen.tank_capacity_l or 0.0)
    tank = float(gen.fuel_tank_level_l or 0.0)
    if cap <= 0 or tank < cap - 0.1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Режим вимірювання можна увімкнути виключно при повному баку! "
                f"Місткість бака: {cap:.1f} л, зараз у баку: {tank:.1f} л."
            ),
        )

    stocks_snap, pools_snap = await _load_facility_book_state(db, facility_id)
    snap_payload = {"stocks": stocks_snap, "pools": pools_snap}

    m = FuelMeasurement(
        facility_id=facility_id,
        generator_id=gen.id,
        status="MEASURING",
        started_by_id=user_id,
        started_at=utc_now(),
        start_operating_hours=float(gen.current_operating_hours or 0.0),
        start_tank_level_l=to_liters(cap),
        old_nominal_consumption_l_per_h=float(gen.nominal_consumption_l_per_h or 2.2),
        min_liters_threshold=Decimal("100.000"),
        added_during_measurement_l=Decimal("0.000"),
        start_snapshot_json=json.dumps(snap_payload, ensure_ascii=False),
    )
    db.add(m)
    await db.flush()

    await log_audit(
        db=db,
        action="MEASUREMENT_STARTED",
        entity_type="FuelMeasurement",
        entity_id=str(m.id),
        user_id=user_id,
        details={
            "facility_id": facility_id,
            "generator_id": gen.id,
            "generator_name": gen.name,
            "start_operating_hours": m.start_operating_hours,
            "start_tank_level_l": float(m.start_tank_level_l),
            "old_nominal_consumption_l_per_h": m.old_nominal_consumption_l_per_h,
        },
        ip_address=ip_address,
    )
    await db.commit()
    return await _build_measurement_summary(db, m)


async def finish_measurement_tank_empty(
    db: AsyncSession,
    measurement_id: int,
    data: MeasurementFinishEmptyRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> MeasurementSummaryOut:
    m = (
        await db.execute(select(FuelMeasurement).where(FuelMeasurement.id == measurement_id).with_for_update())
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запис вимірювання не знайдено")
    if m.status != "MEASURING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Вимірювання вже не в активній фазі.")

    gen = (
        await db.execute(select(Generator).where(Generator.id == m.generator_id).with_for_update())
    ).scalars().first()
    if not gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if gen.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Спочатку зупиніть генератор із фіксацією мотогодин, а потім підтвердьте порожній бак.",
        )

    total_consumed_dec = to_liters(m.start_tank_level_l) + to_liters(m.added_during_measurement_l)
    min_thresh_dec = to_liters(m.min_liters_threshold or Decimal("100.000"))
    if total_consumed_dec + Decimal("0.001") < min_thresh_dec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Неможливо завершити вимірювання до відпрацювання принаймні {float(min_thresh_dec):.0f} л палива "
                f"(зараз обліковано {float(total_consumed_dec):.1f} л: повний бак {float(m.start_tank_level_l):.1f} л + "
                f"дозаправки {float(m.added_during_measurement_l):.1f} л)."
            ),
        )

    end_hours = float(data.end_operating_hours) if data.end_operating_hours is not None else float(gen.current_operating_hours or 0.0)
    if end_hours < float(gen.current_operating_hours or 0.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Кінцеві мотогодини ({end_hours}) не можуть бути меншими за поточний лічильник генератора ({gen.current_operating_hours}).",
        )
    elapsed_hours = round(end_hours - float(m.start_operating_hours), 4)
    if elapsed_hours <= 0.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Відпрацьовані мотогодини за період вимірювання повинні бути більшими за 0.",
        )

    calc_cons = round(float(total_consumed_dec) / elapsed_hours, 3)

    # Tank is physically confirmed empty (0.0 L)
    gen.fuel_tank_level_l = 0.0
    if end_hours > float(gen.current_operating_hours or 0.0):
        gen.current_operating_hours = round(end_hours, 3)
    gen.updated_at = utc_now()

    m.status = "PENDING_INVENTORY"
    m.tank_emptied_at = utc_now()
    m.tank_emptied_by_id = user_id
    m.end_operating_hours = round(end_hours, 3)
    m.total_fuel_consumed_l = total_consumed_dec
    m.total_hours_elapsed = elapsed_hours
    m.calculated_consumption_l_per_h = calc_cons
    m.updated_at = utc_now()

    await db.flush()
    await log_audit(
        db=db,
        action="MEASUREMENT_TANK_EMPTY",
        entity_type="FuelMeasurement",
        entity_id=str(m.id),
        user_id=user_id,
        details={
            "facility_id": m.facility_id,
            "generator_id": m.generator_id,
            "total_fuel_consumed_l": float(total_consumed_dec),
            "total_hours_elapsed": elapsed_hours,
            "calculated_consumption_l_per_h": calc_cons,
            "old_nominal_consumption_l_per_h": m.old_nominal_consumption_l_per_h,
        },
        ip_address=ip_address,
    )
    await db.commit()
    return await _build_measurement_summary(db, m)


async def submit_measurement_inventory(
    db: AsyncSession,
    measurement_id: int,
    data: MeasurementInventoryRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> MeasurementSummaryOut:
    m = (
        await db.execute(select(FuelMeasurement).where(FuelMeasurement.id == measurement_id).with_for_update())
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запис вимірювання не знайдено")
    if m.status not in ("PENDING_INVENTORY", "PENDING_APPROVAL"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Інвентаризація можлива лише після завершення етапу заміру («Бак пустий»).",
        )

    gen = await db.get(Generator, m.generator_id)
    if not gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    tank_cap = float(gen.tank_capacity_l or 25.0)
    if data.generator_tank_fact_l > tank_cap + 0.001:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Фактичний залишок у баку ({data.generator_tank_fact_l} л) перевищує місткість бака ({tank_cap} л).",
        )

    # Validate commission (>= 3 members with non-empty names and roles)
    clean_members = []
    for member in data.commission_members:
        nm = member.name.strip()
        rl = member.role.strip()
        if len(nm) < 2 or len(rl) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Кожен член комісії повинен мати ПІБ та посаду (не менше 2 символів).",
            )
        clean_members.append({"name": nm, "role": rl})
    if len(clean_members) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Склад комісії повинен налічувати щонайменше 3 особи.",
        )

    stocks = list(
        (
            await db.execute(
                select(FuelStock)
                .where(FuelStock.facility_id == m.facility_id, FuelStock.is_active == True)  # noqa: E712
                .order_by(FuelStock.id.asc())
            )
        ).scalars().all()
    )
    pools = list(
        (
            await db.execute(
                select(CanisterPool)
                .where(CanisterPool.facility_id == m.facility_id, CanisterPool.is_active == True)  # noqa: E712
                .order_by(CanisterPool.id.asc())
            )
        ).scalars().all()
    )

    pool_input_map = {int(item.pool_id): item for item in data.pools}
    stock_input_map = {int(item.stock_id): item for item in data.stocks}

    pools_fact_rows = []
    stock_fact_totals: Dict[int, float] = {}
    for p in pools:
        pin = pool_input_map.get(int(p.id))
        vol_dec = to_decimal(p.canister_volume_l, 2)
        if pin:
            res_dec = to_liters(pin.reserve_liters)
            total_c = _validate_pool_invariants(pin.full_count, pin.empty_count, pin.away_refill_count, vol_dec, res_dec)
            fact_full, fact_empty, fact_away, fact_res_dec = pin.full_count, pin.empty_count, pin.away_refill_count, res_dec
        else:
            total_c = int(p.total_count)
            fact_full = int(p.full_count)
            fact_empty = int(p.empty_count)
            fact_away = int(p.away_refill_count)
            fact_res_dec = to_liters(p.reserve_liters)

        fact_total_l = round(float(Decimal(fact_full) * vol_dec + fact_res_dec), 3)
        book_total_l = round(float(_pool_available_dec(p)), 3)
        stock_fact_totals[int(p.stock_id)] = round(stock_fact_totals.get(int(p.stock_id), 0.0) + fact_total_l, 3)

        pools_fact_rows.append(
            {
                "pool_id": int(p.id),
                "stock_id": int(p.stock_id),
                "pool_name": p.name,
                "fuel_type": p.fuel_type,
                "canister_volume_l": round(float(vol_dec), 2),
                "total_count": total_c,
                "book_full": int(p.full_count),
                "book_empty": int(p.empty_count),
                "book_away": int(p.away_refill_count),
                "book_reserve_l": round(float(p.reserve_liters or 0.0), 3),
                "book_total_l": book_total_l,
                "fact_full": fact_full,
                "fact_empty": fact_empty,
                "fact_away": fact_away,
                "fact_reserve_l": round(float(fact_res_dec), 3),
                "fact_total_l": fact_total_l,
                "diff_l": round(fact_total_l - book_total_l, 3),
            }
        )

    stocks_fact_rows = []
    for s in stocks:
        sid = int(s.id)
        book_bal = round(float(s.current_balance_l or 0.0), 3)
        if sid in stock_fact_totals:
            fact_bal = stock_fact_totals[sid]
        elif sid in stock_input_map:
            fact_bal = round(float(stock_input_map[sid].fact_balance_l), 3)
        else:
            fact_bal = book_bal

        stocks_fact_rows.append(
            {
                "stock_id": sid,
                "stock_name": s.name,
                "fuel_type": s.fuel_type,
                "book_balance_l": book_bal,
                "fact_balance_l": fact_bal,
                "diff_l": round(fact_bal - book_bal, 3),
            }
        )

    gen_book_tank = round(float(gen.fuel_tank_level_l or 0.0), 3)
    gen_fact_tank = round(float(data.generator_tank_fact_l), 3)

    inv_fact = {
        "generator_tank_book_l": gen_book_tank,
        "generator_tank_fact_l": gen_fact_tank,
        "generator_tank_diff_l": round(gen_fact_tank - gen_book_tank, 3),
        "stocks": stocks_fact_rows,
        "pools": pools_fact_rows,
        "notes": (data.notes or "").strip() or None,
    }

    now_dt = utc_now()
    if not m.statement_number:
        date_part = now_facility().strftime("%Y%m%d")
        m.statement_number = f"ІНВ-{date_part}-{m.id:03d}"

    m.commission_members_json = json.dumps(clean_members, ensure_ascii=False)
    m.inventory_fact_json = json.dumps(inv_fact, ensure_ascii=False)
    m.inventory_entered_at = now_dt
    m.document_generated_at = now_dt
    # Require downloading the newly updated PDF before SuperAdmin can click Approve
    m.document_downloaded_at = None
    m.status = "PENDING_APPROVAL"
    m.updated_at = now_dt

    await db.flush()
    await log_audit(
        db=db,
        action="MEASUREMENT_INVENTORY_SUBMITTED",
        entity_type="FuelMeasurement",
        entity_id=str(m.id),
        user_id=user_id,
        details={
            "facility_id": m.facility_id,
            "statement_number": m.statement_number,
            "commission_count": len(clean_members),
            "generator_tank_fact_l": gen_fact_tank,
            "stocks_fact_total_l": round(sum(r["fact_balance_l"] for r in stocks_fact_rows), 2),
        },
        ip_address=ip_address,
    )
    await db.commit()
    return await _build_measurement_summary(db, m)


def _resolve_cyrillic_font_pair() -> tuple[Optional[str], Optional[str]]:
    candidates = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ),
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf"),
    ]
    for reg, bold in candidates:
        if Path(reg).exists():
            return reg, (bold if Path(bold).exists() else reg)
    return None, None


def _fmt_pdf_dt(dt: Optional[datetime.datetime]) -> str:
    if not dt:
        return "-"
    return to_facility_time(dt).strftime("%d.%m.%Y %H:%M")


def _pdf_safe_text(text: Any, has_unicode_font: bool) -> str:
    s = str(text if text is not None else "-")
    if has_unicode_font:
        return s
    return s.encode("latin-1", "replace").decode("latin-1")


async def generate_measurement_statement_pdf(
    db: AsyncSession,
    measurement_id: int,
    user_id: int,
    ip_address: Optional[str] = None,
) -> tuple[bytes, str]:
    m = (
        await db.execute(
            select(FuelMeasurement)
            .options(
                selectinload(FuelMeasurement.facility),
                selectinload(FuelMeasurement.generator),
                selectinload(FuelMeasurement.approved_by),
            )
            .where(FuelMeasurement.id == measurement_id)
        )
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Відомість вимірювання не знайдено")
    if m.status not in ("PENDING_APPROVAL", "APPROVED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Спочатку внесіть дані інвентаризації комісії, щоб сформувати PDF-відомість.",
        )

    inv_fact = json.loads(m.inventory_fact_json or "{}")
    commission = json.loads(m.commission_members_json or "[]")
    fac = m.facility or await db.get(Facility, m.facility_id)
    gen = m.generator or await db.get(Generator, m.generator_id)
    org_name = str(get_runtime_setting("organization_name", "MAXI-UA LLC") or "MAXI-UA LLC")
    stmt_no = m.statement_number or f"ІНВ-{m.id:03d}"

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.set_margins(12, 10, 12)
    pdf.add_page()

    reg_font, bold_font = _resolve_cyrillic_font_pair()
    has_utf8 = bool(reg_font)
    if has_utf8:
        pdf.add_font("CyrFont", "", reg_font)
        pdf.add_font("CyrFont", "B", bold_font)
        font_family = "CyrFont"
    else:
        font_family = "Helvetica"

    t = lambda s: _pdf_safe_text(s, has_utf8)

    # Header top row
    pdf.set_font(font_family, "B", 9)
    pdf.cell(175, 5, t(f"Організація: {org_name}"), border=0, align="L")
    pdf.cell(98, 5, t("ПОГОДЖЕНО / ЗАТВЕРДЖУЮ"), border=0, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(font_family, "", 8.5)
    pdf.cell(175, 4.5, t(f"Дата формування: {_fmt_pdf_dt(m.document_generated_at or utc_now())}"), border=0, align="L")
    approver_line = (
        f"Суперадміністратор: {(m.approved_by.full_name or m.approved_by.login)}"
        if m.approved_by else "Суперадміністратор: ________________________"
    )
    pdf.cell(98, 4.5, t(approver_line), border=0, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)
    pdf.set_font(font_family, "B", 13)
    pdf.cell(273, 7, t(f"ВІДОМІСТЬ ІНВЕНТАРИЗАЦІЇ ГСМ ТА КОНТРОЛЬНОГО ЗАМІРУ № {stmt_no}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_family, "", 9)
    fac_desc = f"Об'єкт: {fac.name if fac else '-'} ({fac.address or '-'})" if fac else "Об'єкт: -"
    gen_desc = (
        f"Генератор: {gen.name} | Тип/Модель: {gen.model} ({gen.manufacturer}) | Паливо: {gen.fuel_type} | "
        f"S/N: {gen.serial_number} | Бак: {float(gen.tank_capacity_l or 0):.1f} л"
    ) if gen else "Генератор: -"
    pdf.cell(273, 5, t(fac_desc), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(273, 5, t(gen_desc), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Section 1: Measurement summary table (273 mm width)
    pdf.set_font(font_family, "B", 10)
    pdf.cell(273, 6, t("1. Результати контрольного заміру витрат палива («повний бак → порожній бак»)"), new_x="LMARGIN", new_y="NEXT")

    m_cols = [
        ("Початок", 31),
        ("Кінець", 31),
        ("Мотогодини", 36),
        ("Відпр., год", 24),
        ("Повн. бак, л", 25),
        ("Дозапр., л", 25),
        ("Спалено, л", 26),
        ("Було, л/год", 34),
        ("ФАКТ, л/год", 41),
    ]
    pdf.set_fill_color(226, 232, 240)
    pdf.set_font(font_family, "B", 8)
    for label, w in m_cols:
        pdf.cell(w, 6.5, t(label), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font(font_family, "", 8.5)
    m_vals = [
        _fmt_pdf_dt(m.started_at),
        _fmt_pdf_dt(m.tank_emptied_at),
        f"{float(m.start_operating_hours):.1f} → {float(m.end_operating_hours or 0):.1f}",
        f"{float(m.total_hours_elapsed or 0):.2f}",
        f"{float(m.start_tank_level_l or 0):.1f}",
        f"{float(m.added_during_measurement_l or 0):.1f}",
        f"{float(m.total_fuel_consumed_l or 0):.1f}",
        f"{float(m.old_nominal_consumption_l_per_h or 0):.3f}",
        f"{float(m.calculated_consumption_l_per_h or 0):.3f}",
    ]
    for idx, ((_, w), val) in enumerate(zip(m_cols, m_vals)):
        if idx == len(m_cols) - 1:
            pdf.set_font(font_family, "B", 9)
        else:
            pdf.set_font(font_family, "", 8.5)
        pdf.cell(w, 6.5, t(val), border=1, align="C")
    pdf.ln(9)

    # Section 2: Inventory reconciliation table (273 mm width)
    pdf.set_font(font_family, "B", 10)
    pdf.cell(273, 6, t("2. Відомість фактичних залишків пального та закріпленої тари на об'єкті"), new_x="LMARGIN", new_y="NEXT")

    i_cols = [
        ("№", 10),
        ("Об'єкт обліку (Бак / Склад / Пул каністр)", 83),
        ("Паливо", 22),
        ("Каністри факт (П / Пор / АЗС)", 54),
        ("Резерв факт, л", 26),
        ("За обліком, л", 26),
        ("Факт, л", 26),
        ("Відхилення, л", 26),
    ]
    pdf.set_font(font_family, "B", 8)
    for label, w in i_cols:
        pdf.cell(w, 6.5, t(label), border=1, align="C", fill=True)
    pdf.ln()

    inv_rows: list[list[str]] = []
    # Generator tank row
    g_book = float(inv_fact.get("generator_tank_book_l", 0.0))
    g_fact = float(inv_fact.get("generator_tank_fact_l", 0.0))
    g_diff = round(g_fact - g_book, 2)
    inv_rows.append([
        "1",
        f"Бак генератора: {gen.name if gen else '-'}",
        gen.fuel_type if gen else "-",
        "—",
        "—",
        f"{g_book:.2f}",
        f"{g_fact:.2f}",
        f"{g_diff:+.2f}",
    ])

    row_no = 2
    pools_list = inv_fact.get("pools") or []
    stocks_by_pool = {int(pr["stock_id"]) for pr in pools_list if pr.get("stock_id") is not None}
    for pr in pools_list:
        diff_v = float(pr.get("diff_l", 0.0))
        inv_rows.append([
            str(row_no),
            f"{pr.get('pool_name', 'Пул каністр')} ({float(pr.get('canister_volume_l', 20)):.0f} л)",
            str(pr.get("fuel_type", "-")),
            f"{int(pr.get('fact_full', 0))} / {int(pr.get('fact_empty', 0))} / {int(pr.get('fact_away', 0))} (всього {int(pr.get('total_count', 0))})",
            f"{float(pr.get('fact_reserve_l', 0.0)):.2f}",
            f"{float(pr.get('book_total_l', 0.0)):.2f}",
            f"{float(pr.get('fact_total_l', 0.0)):.2f}",
            f"{diff_v:+.2f}",
        ])
        row_no += 1

    for st in (inv_fact.get("stocks") or []):
        if int(st.get("stock_id", 0)) in stocks_by_pool:
            continue
        diff_v = float(st.get("diff_l", 0.0))
        inv_rows.append([
            str(row_no),
            f"Склад ГСМ: {st.get('stock_name', '-')}",
            str(st.get("fuel_type", "-")),
            "—",
            "—",
            f"{float(st.get('book_balance_l', 0.0)):.2f}",
            f"{float(st.get('fact_balance_l', 0.0)):.2f}",
            f"{diff_v:+.2f}",
        ])
        row_no += 1

    # Total row across tank + stocks
    total_book_all = g_book + sum(float(s.get("book_balance_l", 0.0)) for s in (inv_fact.get("stocks") or []))
    total_fact_all = g_fact + sum(float(s.get("fact_balance_l", 0.0)) for s in (inv_fact.get("stocks") or []))
    total_diff_all = round(total_fact_all - total_book_all, 2)

    pdf.set_font(font_family, "", 8.2)
    for r_vals in inv_rows:
        for idx, ((_, w), val) in enumerate(zip(i_cols, r_vals)):
            align = "L" if idx == 1 else "C"
            pdf.cell(w, 6, t(val), border=1, align=align)
        pdf.ln()

    pdf.set_font(font_family, "B", 8.5)
    pdf.cell(195, 6.5, t("РАЗОМ ПО ОБ'ЄКТУ (Бак + Склади ГСМ):"), border=1, align="R", fill=True)
    pdf.cell(26, 6.5, t(f"{total_book_all:.2f}"), border=1, align="C", fill=True)
    pdf.cell(26, 6.5, t(f"{total_fact_all:.2f}"), border=1, align="C", fill=True)
    pdf.cell(26, 6.5, t(f"{total_diff_all:+.2f}"), border=1, align="C", fill=True)
    pdf.ln(7)

    if inv_fact.get("notes"):
        pdf.set_font(font_family, "", 8.5)
        pdf.multi_cell(273, 5, t(f"Примітка комісії: {inv_fact['notes']}"))
        pdf.ln(2)

    # Section 3: Commission Signatures (minimum 3 members)
    pdf.set_font(font_family, "B", 10)
    pdf.cell(273, 6, t("3. Склад інвентаризаційної комісії та підписи сторін"), new_x="LMARGIN", new_y="NEXT")

    c_cols = [("№", 12), ("Посада", 85), ("Прізвище, ім'я, по батькові", 95), ("Підпис", 51), ("Дата", 30)]
    pdf.set_font(font_family, "B", 8)
    for label, w in c_cols:
        pdf.cell(w, 6, t(label), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font(font_family, "", 8.5)
    for idx, member in enumerate(commission, start=1):
        pdf.cell(12, 7.5, str(idx), border=1, align="C")
        pdf.cell(85, 7.5, t(member.get("role", "-")), border=1, align="L")
        pdf.cell(95, 7.5, t(member.get("name", "-")), border=1, align="L")
        pdf.cell(51, 7.5, "", border=1, align="C")
        pdf.cell(30, 7.5, "____.__.202__", border=1, align="C")
        pdf.ln()

    raw_bytes = pdf.output()
    pdf_bytes = bytes(raw_bytes)

    if m.status == "PENDING_APPROVAL" and m.document_downloaded_at is None:
        m.document_downloaded_at = utc_now()
        m.updated_at = utc_now()
        await log_audit(
            db=db,
            action="MEASUREMENT_STATEMENT_DOWNLOADED",
            entity_type="FuelMeasurement",
            entity_id=str(m.id),
            user_id=user_id,
            details={"facility_id": m.facility_id, "statement_number": stmt_no},
            ip_address=ip_address,
        )
        await db.commit()

    safe_filename = f"Inventory_{stmt_no}_Gen{m.generator_id}.pdf".replace(" ", "_")
    return pdf_bytes, safe_filename


async def approve_measurement(
    db: AsyncSession,
    measurement_id: int,
    user_id: int,
    ip_address: Optional[str] = None,
) -> MeasurementSummaryOut:
    m = (
        await db.execute(select(FuelMeasurement).where(FuelMeasurement.id == measurement_id).with_for_update())
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запис вимірювання не знайдено")
    if m.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Погодження можливе лише після внесення інвентаризації та формування відомості.",
        )
    if not m.document_downloaded_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Спочатку скачайте сформовану PDF-відомість інвентаризації для підпису комісією!",
        )

    gen = (
        await db.execute(select(Generator).where(Generator.id == m.generator_id).with_for_update())
    ).scalars().first()
    if not gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    inv_fact = json.loads(m.inventory_fact_json or "{}")
    commission = json.loads(m.commission_members_json or "[]")
    stmt_no = m.statement_number or f"ІНВ-{m.id:03d}"

    # 1. Update generator nominal consumption and factual tank balance
    old_cons = float(gen.nominal_consumption_l_per_h)
    new_cons = float(m.calculated_consumption_l_per_h or old_cons)
    fact_tank = round(float(inv_fact.get("generator_tank_fact_l", 0.0)), 3)

    gen.nominal_consumption_l_per_h = new_cons
    gen.fuel_tank_level_l = fact_tank
    gen.updated_at = utc_now()

    # 2. Apply factual canister pool counts & reserves + resync stocks
    pools_fact = inv_fact.get("pools") or []
    updated_stock_ids = set()
    for p_fact in pools_fact:
        pool = (
            await db.execute(select(CanisterPool).where(CanisterPool.id == int(p_fact["pool_id"])).with_for_update())
        ).scalars().first()
        if not pool:
            continue
        stock = (
            await db.execute(select(FuelStock).where(FuelStock.id == pool.stock_id).with_for_update())
        ).scalars().first()

        before_snap = _snapshot_pool(pool)
        old_avail = _pool_available_dec(pool)
        vol_dec = to_decimal(pool.canister_volume_l, 2)

        f_full = int(p_fact["fact_full"])
        f_empty = int(p_fact["fact_empty"])
        f_away = int(p_fact["fact_away"])
        f_res = to_liters(p_fact["fact_reserve_l"])
        new_total = _validate_pool_invariants(f_full, f_empty, f_away, vol_dec, f_res)

        pool.full_count = f_full
        pool.empty_count = f_empty
        pool.away_refill_count = f_away
        pool.total_count = new_total
        pool.reserve_liters = f_res
        pool.updated_at = utc_now()
        await db.flush()

        new_avail = _pool_available_dec(pool)
        _record_canister_tx(
            db=db,
            pool=pool,
            user_id=user_id,
            operation="INVENTORY_CORRECTION",
            count=abs(f_full - before_snap[0]),
            liters_delta=new_avail - old_avail,
            used_from_reserve=Decimal("0.000"),
            before_snap=before_snap,
            comment=f"Інвентаризація за відомістю {stmt_no} ({float(old_avail):.1f} → {float(new_avail):.1f} л)",
        )
        if stock:
            await sync_stock_balance_from_pools(db, stock)
            updated_stock_ids.add(int(stock.id))

    # For any stock without canister pools
    for st_fact in (inv_fact.get("stocks") or []):
        sid = int(st_fact["stock_id"])
        if sid in updated_stock_ids:
            continue
        stock = (
            await db.execute(select(FuelStock).where(FuelStock.id == sid).with_for_update())
        ).scalars().first()
        if stock:
            stock.current_balance_l = to_liters(st_fact["fact_balance_l"])
            stock.updated_at = utc_now()

    m.status = "APPROVED"
    m.approved_by_id = user_id
    m.approved_at = utc_now()
    m.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="MEASUREMENT_APPROVED",
        entity_type="FuelMeasurement",
        entity_id=str(m.id),
        user_id=user_id,
        details={
            "facility_id": m.facility_id,
            "generator_id": gen.id,
            "generator_name": gen.name,
            "statement_number": stmt_no,
            "old_nominal_consumption_l_per_h": old_cons,
            "new_nominal_consumption_l_per_h": new_cons,
            "total_fuel_consumed_l": float(m.total_fuel_consumed_l or 0.0),
            "total_hours_elapsed": float(m.total_hours_elapsed or 0.0),
            "commission_members": [f"{cm['name']} ({cm['role']})" for cm in commission],
            "generator_tank_fact_l": fact_tank,
        },
        ip_address=ip_address,
    )
    await db.commit()
    return await _build_measurement_summary(db, m)


async def cancel_measurement(
    db: AsyncSession,
    measurement_id: int,
    data: MeasurementCancelRequest,
    user_id: int,
    ip_address: Optional[str] = None,
) -> MeasurementSummaryOut:
    m = (
        await db.execute(select(FuelMeasurement).where(FuelMeasurement.id == measurement_id).with_for_update())
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запис вимірювання не знайдено")
    if m.status not in ACTIVE_MEASUREMENT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Цей замір вже завершено або скасовано.")

    m.status = "CANCELLED"
    m.cancelled_by_id = user_id
    m.cancelled_at = utc_now()
    m.cancel_reason = data.reason.strip()
    m.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="MEASUREMENT_CANCELLED",
        entity_type="FuelMeasurement",
        entity_id=str(m.id),
        user_id=user_id,
        details={
            "facility_id": m.facility_id,
            "generator_id": m.generator_id,
            "reason": m.cancel_reason,
            "measured_liters_before_cancel": round(float(m.start_tank_level_l or 0) + float(m.added_during_measurement_l or 0), 2),
        },
        ip_address=ip_address,
    )
    await db.commit()
    return await _build_measurement_summary(db, m)
