import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.report import OperationalReportOut
from backend.app.api.deps import require_permission
from backend.app.services.report_service import generate_operational_report, export_report_to_csv

router = APIRouter(prefix="/reports", tags=["Звітність"])


@router.get("/summary", response_model=OperationalReportOut)
async def get_report_summary(
    generator_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:view"))
):
    start_dt = datetime.datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.datetime.fromisoformat(end_date) if end_date else None

    return await generate_operational_report(
        db=db,
        generator_id=generator_id,
        start_date=start_dt,
        end_date=end_dt
    )


@router.get("/export")
async def export_report(
    generator_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("reports:export"))
):
    start_dt = datetime.datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.datetime.fromisoformat(end_date) if end_date else None

    report = await generate_operational_report(
        db=db,
        generator_id=generator_id,
        start_date=start_dt,
        end_date=end_dt
    )
    csv_content = export_report_to_csv(report)

    # Return CSV with UTF-8 BOM for Excel compatibility
    filename = f"generator_report_{report.start_date}_{report.end_date}.csv"
    response_bytes = ("\ufeff" + csv_content).encode("utf-8")

    return Response(
        content=response_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
