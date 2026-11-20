import asyncio
from typing import List
from fastapi import APIRouter, Depends, Request, Response, status, HTTPException
from pydantic import BaseModel
from backend.app.models.facility import Facility
from backend.app.services.yasno_service import fetch_raw_yasno_schedule, get_facility_outage_schedule
from backend.app.services.weather_service import get_facility_weather
from backend.app.services.alert_service import get_facility_alert, set_demo_alert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.generator import Generator
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.models.fuel import FuelStock
from backend.app.models.canister import CanisterPool
from backend.app.models.fault import Fault
from backend.app.models.measurement import FuelMeasurement
from backend.app.schemas.facility import FacilityCreate, FacilityUpdate, FacilityOut
from backend.app.services.fuel_service import compute_live_tank_levels_map
from backend.app.services.settings_service import get_runtime_setting
from sqlalchemy import select
from backend.app.api.deps import (
    get_current_user,
    get_current_superadmin,
    require_permission,
    get_client_ip,
    is_user_admin_or_super,
    verify_facility_access,
)
from backend.app.services.facility_service import (
    get_all_facilities, get_facility_by_id, create_facility,
    update_facility, delete_facility
)

router = APIRouter(prefix="/facilities", tags=["Об'єкти (Multi-site)"])


@router.get("", response_model=List[FacilityOut])
async def list_facilities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати перелік об'єктів/локацій (для операторів — лише їхній закріплений об'єкт)"""
    all_facs = await get_all_facilities(db)
    if not is_user_admin_or_super(current_user):
        if not current_user.facility_id:
            return []
        return [f for f in all_facs if f.id == current_user.facility_id]
    return all_facs


@router.get("/overview")
async def get_facilities_network_overview(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Агреговане зведення стану всіх дозволених об'єктів мережі на одному екрані."""
    all_facs = await get_all_facilities(db)
    if not is_user_admin_or_super(current_user):
        if not current_user.facility_id:
            facs = []
        else:
            facs = [f for f in all_facs if f.id == current_user.facility_id]
    else:
        facs = list(all_facs)

    if not facs:
        return {
            "summary": {
                "total_facilities": 0,
                "running_generators": 0,
                "maintenance_due_count": 0,
                "low_fuel_count": 0,
                "critical_faults_count": 0,
                "active_air_alerts_count": 0,
                "weather_warnings_count": 0,
            },
            "facilities": [],
        }

    fac_ids = [f.id for f in facs]
    low_fuel_threshold = float(get_runtime_setting("low_fuel_threshold_l", 5.0) or 5.0)
    def_maint_interval = float(get_runtime_setting("default_maintenance_interval_hours", 300.0) or 300.0)

    gens = list(
        (
            await db.execute(
                select(Generator)
                .where(Generator.facility_id.in_(fac_ids), Generator.is_active == True)  # noqa: E712
                .order_by(Generator.id.asc())
            )
        ).scalars().all()
    )
    gen_ids = [g.id for g in gens]
    live_tank_map = await compute_live_tank_levels_map(db, gens) if gens else {}

    sched_map = {}
    if gen_ids:
        sched_rows = (
            await db.execute(
                select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id.in_(gen_ids))
            )
        ).scalars().all()
        sched_map = {s.generator_id: s for s in sched_rows}

    stock_rows = (
        await db.execute(
            select(FuelStock).where(FuelStock.facility_id.in_(fac_ids), FuelStock.is_active == True)  # noqa: E712
        )
    ).scalars().all()
    stock_by_fac = {fid: 0.0 for fid in fac_ids}
    for st in stock_rows:
        stock_by_fac[st.facility_id] = round(stock_by_fac.get(st.facility_id, 0.0) + float(st.current_balance_l or 0.0), 1)

    pool_rows = (
        await db.execute(
            select(CanisterPool).where(CanisterPool.facility_id.in_(fac_ids), CanisterPool.is_active == True)  # noqa: E712
        )
    ).scalars().all()
    can_by_fac = {fid: {"full": 0, "total": 0} for fid in fac_ids}
    for pl in pool_rows:
        bucket = can_by_fac.setdefault(pl.facility_id, {"full": 0, "total": 0})
        bucket["full"] += int(pl.full_count or 0)
        bucket["total"] += int(pl.total_count or 0)

    fault_rows = (
        await db.execute(
            select(Fault, Generator.facility_id)
            .join(Generator, Fault.generator_id == Generator.id)
            .where(
                Generator.facility_id.in_(fac_ids),
                Fault.status.notin_(["RESOLVED", "CLOSED"]),
            )
        )
    ).all()
    faults_by_fac = {fid: {"open": 0, "critical": 0} for fid in fac_ids}
    for flt, fid in fault_rows:
        fb = faults_by_fac.setdefault(fid, {"open": 0, "critical": 0})
        fb["open"] += 1
        if str(getattr(flt, "priority", "") or "").upper() == "CRITICAL":
            fb["critical"] += 1

    meas_rows = (
        await db.execute(
            select(FuelMeasurement).where(
                FuelMeasurement.facility_id.in_(fac_ids),
                FuelMeasurement.status.in_(["MEASURING", "PENDING_INVENTORY", "PENDING_APPROVAL"]),
            )
        )
    ).scalars().all()
    meas_by_fac = {m.facility_id: m.status for m in meas_rows}

    gens_by_fac = {fid: [] for fid in fac_ids}
    for g in gens:
        gens_by_fac.setdefault(g.facility_id, []).append(g)

    summary = {
        "total_facilities": len(facs),
        "running_generators": 0,
        "maintenance_due_count": 0,
        "low_fuel_count": 0,
        "critical_faults_count": 0,
        "active_air_alerts_count": 0,
        "weather_warnings_count": 0,
    }

    cards = []
    for f in facs:
        fac_gens_out = []
        for g in gens_by_fac.get(f.id, []):
            live_tank = round(float(live_tank_map.get(g.id, g.fuel_tank_level_l or 0.0)), 1)
            cap = float(g.tank_capacity_l or 0.0)
            fuel_pct = round(min(100.0, max(0.0, (live_tank / cap) * 100.0)), 0) if cap > 0 else 0.0
            sched = sched_map.get(g.id)
            interval_h = float(sched.interval_hours) if sched else def_maint_interval
            next_due = float(sched.next_due_hours) if sched else interval_h
            cur_h = round(float(g.current_operating_hours or 0.0), 1)
            hours_rem = round(next_due - cur_h, 1)
            is_due = hours_rem <= 20.0
            is_overdue = hours_rem <= 0.0

            if g.status == "RUNNING":
                summary["running_generators"] += 1
            if is_due or is_overdue or g.status == "MAINTENANCE_REQUIRED":
                summary["maintenance_due_count"] += 1
            if live_tank <= low_fuel_threshold:
                summary["low_fuel_count"] += 1

            fac_gens_out.append({
                "id": g.id,
                "name": g.name,
                "model": g.model,
                "status": g.status,
                "current_operating_hours": cur_h,
                "fuel_tank_level_l": live_tank,
                "tank_capacity_l": round(cap, 1),
                "fuel_percent": int(fuel_pct),
                "maintenance_interval_hours": round(interval_h, 1),
                "hours_to_maintenance": hours_rem,
                "is_maint_due": is_due,
                "is_maint_overdue": is_overdue,
            })

        try:
            weather_info = await get_facility_weather(db, f.id, force=force)
        except Exception:
            weather_info = {"is_available": False, "warnings": [], "has_warnings": False, "max_warning_level": "none"}

        try:
            alert_info = await get_facility_alert(db, f.id, force=force)
        except Exception:
            alert_info = {"level": "green", "threat_title": "Відбій", "threat_icon": "🟢"}

        f_counts = faults_by_fac.get(f.id, {"open": 0, "critical": 0})
        summary["critical_faults_count"] += int(f_counts["critical"])
        if alert_info.get("level") in ("red", "yellow"):
            summary["active_air_alerts_count"] += 1
        if weather_info.get("has_warnings"):
            summary["weather_warnings_count"] += 1

        c_counts = can_by_fac.get(f.id, {"full": 0, "total": 0})
        cards.append({
            "id": f.id,
            "name": f.name,
            "city": weather_info.get("city") or getattr(f, "city", None) or "",
            "region": weather_info.get("region") or "",
            "address": f.address or "",
            "generators": fac_gens_out,
            "stock_balance_l": stock_by_fac.get(f.id, 0.0),
            "canisters_full": c_counts["full"],
            "canisters_total": c_counts["total"],
            "open_faults_count": f_counts["open"],
            "critical_faults_count": f_counts["critical"],
            "measurement_status": meas_by_fac.get(f.id),
            "weather": {
                "is_available": bool(weather_info.get("is_available")),
                "temp_formatted": weather_info.get("temp_formatted") or "--",
                "icon_emoji": weather_info.get("icon_emoji") or "⛅",
                "description": weather_info.get("description") or "",
                "has_warnings": bool(weather_info.get("has_warnings")),
                "max_warning_level": weather_info.get("max_warning_level") or "none",
                "warnings_count": len(weather_info.get("warnings") or []),
                "top_warning": (weather_info.get("warnings") or [None])[0],
            },
            "alert": {
                "level": alert_info.get("level") or "green",
                "threat_title": alert_info.get("threat_title") or "Відбій",
                "threat_icon": alert_info.get("threat_icon") or "🟢",
            },
        })

    return {"summary": summary, "facilities": cards}


@router.post("", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
async def add_facility(
    data: FacilityCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("facility:configure"))
):
    """Створити новий об'єкт (локацію)"""
    client_ip = get_client_ip(request)
    return await create_facility(db, data, current_user.id, client_ip)


@router.get("/{facility_id}", response_model=FacilityOut)
async def get_facility(
    facility_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати дані конкретного об'єкту"""
    verify_facility_access(current_user, facility_id)
    return await get_facility_by_id(db, facility_id)


@router.put("/{facility_id}", response_model=FacilityOut)
async def edit_facility(
    facility_id: int,
    data: FacilityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("facility:configure"))
):
    """Оновити параметри об'єкту"""
    verify_facility_access(current_user, facility_id)
    client_ip = get_client_ip(request)
    return await update_facility(db, facility_id, data, current_user.id, client_ip)


@router.delete("/{facility_id}")
async def remove_facility(
    facility_id: int,
    request: Request,
    cascade: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    """Видалити об'єкт (доступно виключно для SuperAdmin)"""
    verify_facility_access(current_user, facility_id)
    client_ip = get_client_ip(request)
    return await delete_facility(db, facility_id, current_user.id, cascade=cascade, ip_address=client_ip)


@router.get("/{facility_id}/outage-schedule")
async def get_facility_outage(
    facility_id: int,
    force_refresh: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати розпарсений графік відключень YASNO для конкретного об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    fac = await db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Об'єкт #{facility_id} не знайдено")

    if not fac.yasno_enabled or not fac.yasno_group:
        return get_facility_outage_schedule(fac)

    raw_data = await fetch_raw_yasno_schedule(
        region_id=fac.yasno_region_id or 3,
        dso_id=fac.yasno_dso_id or 301,
        force_refresh=force_refresh
    )
    return get_facility_outage_schedule(fac, raw_schedule=raw_data)


@router.get("/{facility_id}/weather")
async def get_facility_weather_data(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати поточну погоду для об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return await get_facility_weather(db, facility_id, force=force)


@router.get("/{facility_id}/alert")
async def get_facility_alert_data(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати статус повітряної тривоги для об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return await get_facility_alert(db, facility_id, force=force)


@router.get("/{facility_id}/status-indicators")
async def get_facility_indicators(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати об'єднані індикатори погоди та тривог в одному швидкому запиті"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    # Warm facility in session identity map so concurrent tasks do not contend on AsyncSession
    await db.get(Facility, facility_id)
    weather, alert = await asyncio.gather(
        get_facility_weather(db, facility_id, force=force),
        get_facility_alert(db, facility_id, force=force)
    )
    return {
        "weather": weather,
        "alert": alert
    }


class DemoAlertRequest(BaseModel):
    level: str = "green"  # green, yellow, red
    threat_type: str = "none"


@router.post("/demo-alert")
async def trigger_demo_alert(
    data: DemoAlertRequest,
    current_user: User = Depends(get_current_superadmin)
):
    """Тестовий перемикач рівнів тривог для перевірки UI (доступно для SuperAdmin)"""
    set_demo_alert(data.level, data.threat_type)
    return {"ok": True, "level": data.level, "threat_type": data.threat_type}
