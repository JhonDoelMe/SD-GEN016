import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.report import OperationalReportOut
from backend.app.api.deps import require_permission
from backend.app.services.report_service import (
    generate_operational_report, export_report_to_csv, generate_excel_report
)

router = APIRouter(prefix="/reports", tags=["Звітність"])


def parse_report_dt(dt_str: Optional[str], is_end: bool = False) -> Optional[datetime.datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
    except ValueError:
        return None
    if is_end and len(dt_str) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


@router.get("/summary", response_model=OperationalReportOut)
async def get_report_summary(
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:view"))
):
    start_dt = parse_report_dt(start_date, is_end=False)
    end_dt = parse_report_dt(end_date, is_end=True)

    return await generate_operational_report(
        db=db,
        generator_id=generator_id,
        facility_id=facility_id,
        start_date=start_dt,
        end_date=end_dt
    )


@router.get("/export")
async def export_report(
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:export"))
):
    start_dt = parse_report_dt(start_date, is_end=False)
    end_dt = parse_report_dt(end_date, is_end=True)

    report = await generate_operational_report(
        db=db,
        generator_id=generator_id,
        facility_id=facility_id,
        start_date=start_dt,
        end_date=end_dt
    )
    csv_content = export_report_to_csv(report)

    filename = f"generator_report_{report.start_date}_{report.end_date}.csv"
    response_bytes = ("\ufeff" + csv_content).encode("utf-8")

    return Response(
        content=response_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/export-excel")
async def export_excel_report(
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:export"))
):
    """Експорт детального багатосторінкового звіту в Excel (.xlsx)"""
    start_dt = parse_report_dt(start_date, is_end=False)
    end_dt = parse_report_dt(end_date, is_end=True)

    excel_bytes = await generate_excel_report(
        db=db,
        generator_id=generator_id,
        facility_id=facility_id,
        start_date=start_dt,
        end_date=end_dt
    )

    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ServiceDesk_Report_{date_str}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
