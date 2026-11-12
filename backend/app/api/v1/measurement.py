import urllib.parse
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.measurement import (
    MeasurementCancelRequest,
    MeasurementFinishFullRequest,
    MeasurementInventoryRequest,
    MeasurementStartRequest,
    MeasurementStatusEnvelope,
    MeasurementSummaryOut,
)
from backend.app.api.deps import (
    get_current_user,
    get_current_superadmin,
    get_client_ip,
    verify_facility_access,
)
from backend.app.services.measurement_service import (
    approve_measurement,
    cancel_measurement,
    finish_measurement_tank_full,
    generate_measurement_statement_pdf,
    get_measurement_status_envelope,
    list_measurements_history,
    start_measurement,
    submit_measurement_inventory,
)

router = APIRouter(prefix="/measurement", tags=["Режим вимірювання та інвентаризація"])


@router.get("/status", response_model=MeasurementStatusEnvelope)
async def get_measurement_status_api(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    eff_fac = verify_facility_access(current_user, facility_id)
    if eff_fac is None:
        eff_fac = facility_id or 1
    return await get_measurement_status_envelope(db, eff_fac)


@router.get("/history", response_model=List[MeasurementSummaryOut])
async def get_measurement_history_api(
    facility_id: Optional[int] = None,
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await list_measurements_history(db, facility_id=facility_id, limit=limit)


@router.post("/start", response_model=MeasurementSummaryOut)
async def start_measurement_api(
    data: MeasurementStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await start_measurement(db, data, current_user.id, get_client_ip(request))


@router.post("/{measurement_id}/finish-full", response_model=MeasurementSummaryOut)
async def finish_measurement_full_api(
    measurement_id: int,
    data: MeasurementFinishFullRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await finish_measurement_tank_full(db, measurement_id, data, current_user.id, get_client_ip(request))


@router.post("/{measurement_id}/inventory", response_model=MeasurementSummaryOut)
async def submit_measurement_inventory_api(
    measurement_id: int,
    data: MeasurementInventoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await submit_measurement_inventory(db, measurement_id, data, current_user.id, get_client_ip(request))


@router.get("/{measurement_id}/statement-pdf")
async def download_measurement_statement_pdf_api(
    measurement_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    pdf_bytes, filename = await generate_measurement_statement_pdf(
        db, measurement_id, current_user.id, get_client_ip(request)
    )
    ascii_name = filename.replace("ІНВ", "INV")
    encoded_name = urllib.parse.quote(filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
        },
    )


@router.post("/{measurement_id}/approve", response_model=MeasurementSummaryOut)
async def approve_measurement_api(
    measurement_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await approve_measurement(db, measurement_id, current_user.id, get_client_ip(request))


@router.post("/{measurement_id}/cancel", response_model=MeasurementSummaryOut)
async def cancel_measurement_api(
    measurement_id: int,
    data: MeasurementCancelRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    return await cancel_measurement(db, measurement_id, data, current_user.id, get_client_ip(request))
