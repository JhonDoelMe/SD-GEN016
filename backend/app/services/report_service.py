import csv
import io
import datetime
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.maintenance import MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.schemas.report import OperationalReportOut


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def generate_operational_report(
    db: AsyncSession,
    generator_id: Optional[int] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None
) -> OperationalReportOut:
    gen_res = await db.execute(select(Generator))
    generator = await db.get(Generator, generator_id) if generator_id else gen_res.scalars().first()
    gen_name = generator.name if generator else "Генератор"

    # Default to 30 days if not set
    now = utc_now()
    if not end_date:
        end_date = now
    if not start_date:
        start_date = end_date - datetime.timedelta(days=30)

    # 1. Runs aggregate
    runs_q = select(
        func.count(GeneratorRun.id),
        func.coalesce(func.sum(GeneratorRun.duration_hours), 0.0),
        func.coalesce(func.sum(GeneratorRun.calculated_consumption_l), 0.0)
    ).where(
        GeneratorRun.start_time >= start_date,
        GeneratorRun.start_time <= end_date,
        GeneratorRun.status == "COMPLETED"
    )
    if generator:
        runs_q = runs_q.where(GeneratorRun.generator_id == generator.id)
    runs_res = await db.execute(runs_q)
    total_runs, total_hours, total_cons = runs_res.first()

    # 2. Fuel receipts aggregate
    rec_q = select(
        func.coalesce(func.sum(FuelReceipt.liters), 0.0),
        func.coalesce(func.sum(FuelReceipt.cost_total), 0.0)
    ).where(
        FuelReceipt.created_at >= start_date,
        FuelReceipt.created_at <= end_date
    )
    rec_res = await db.execute(rec_q)
    fuel_rec_l, fuel_rec_cost = rec_res.first()
    avg_price = round(fuel_rec_cost / fuel_rec_l, 2) if fuel_rec_l > 0 else 0.0

    # 3. Fuel transfers aggregate
    tr_q = select(
        func.coalesce(func.sum(FuelTransfer.liters), 0.0)
    ).where(
        FuelTransfer.created_at >= start_date,
        FuelTransfer.created_at <= end_date
    )
    if generator:
        tr_q = tr_q.where(FuelTransfer.generator_id == generator.id)
    tr_res = await db.execute(tr_q)
    fuel_transferred_l = tr_res.scalar_one()

    # Current stock & tank
    stock_res = await db.execute(select(FuelStock))
    stock = stock_res.scalars().first()
    stock_bal = stock.current_balance_l if stock else 0.0
    tank_bal = generator.fuel_tank_level_l if generator else 0.0

    # 4. Maintenance aggregate
    m_all_q = select(func.count(MaintenanceRecord.id), func.coalesce(func.sum(MaintenanceRecord.cost), 0.0)).where(
        MaintenanceRecord.created_at >= start_date,
        MaintenanceRecord.created_at <= end_date
    )
    m_all_res = await db.execute(m_all_q)
    m_count, m_cost = m_all_res.first()

    m_sched_q = select(func.count(MaintenanceRecord.id)).where(
        MaintenanceRecord.created_at >= start_date,
        MaintenanceRecord.created_at <= end_date,
        MaintenanceRecord.maintenance_type == "SCHEDULED"
    )
    m_sched_cnt = (await db.execute(m_sched_q)).scalar_one()
    m_inter_cnt = m_count - m_sched_cnt

    # 5. Faults aggregate
    f_total_q = select(func.count(Fault.id)).where(
        Fault.created_at >= start_date,
        Fault.created_at <= end_date
    )
    f_total = (await db.execute(f_total_q)).scalar_one()

    f_res_q = select(func.count(Fault.id)).where(
        Fault.created_at >= start_date,
        Fault.created_at <= end_date,
        Fault.status.in_(["RESOLVED", "CLOSED"])
    )
    f_resolved = (await db.execute(f_res_q)).scalar_one()

    return OperationalReportOut(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        generator_name=gen_name,
        total_runs_count=total_runs,
        total_operating_hours=round(total_hours, 2),
        total_calculated_consumption_l=round(total_cons, 2),
        total_fuel_received_l=round(fuel_rec_l, 2),
        total_fuel_receipts_cost_uah=round(fuel_rec_cost, 2),
        avg_fuel_price_per_liter=avg_price,
        total_fuel_transferred_to_tank_l=round(fuel_transferred_l, 2),
        current_stock_balance_l=round(stock_bal, 2),
        current_tank_level_l=round(tank_bal, 2),
        total_maintenance_count=m_count,
        scheduled_maintenance_count=m_sched_cnt,
        intermediate_maintenance_count=m_inter_cnt,
        total_maintenance_cost_uah=round(m_cost, 2),
        total_faults_count=f_total,
        resolved_faults_count=f_resolved,
        open_faults_count=(f_total - f_resolved)
    )


def export_report_to_csv(report: OperationalReportOut) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow(["Параметр", "Значення", "Одиниця виміру"])
    writer.writerow(["Період звіт", f"{report.start_date} - {report.end_date}", ""])
    writer.writerow(["Генератор", report.generator_name, ""])
    writer.writerow(["Кількість робочих циклів (пусків)", report.total_runs_count, "шт"])
    writer.writerow(["Відпрацьовано мотогодин", report.total_operating_hours, "год"])
    writer.writerow(["Розрахункова витрата палива", report.total_calculated_consumption_l, "л"])
    writer.writerow(["Оприбутковано палива на склад", report.total_fuel_received_l, "л"])
    writer.writerow(["Загальна вартість закупленого палива", report.total_fuel_receipts_cost_uah, "грн"])
    writer.writerow(["Середня вартість літра", report.avg_fuel_price_per_liter, "грн/л"])
    writer.writerow(["Заправлено в бак генератора", report.total_fuel_transferred_to_tank_l, "л"])
    writer.writerow(["Поточний залишок на складі ГСМ", report.current_stock_balance_l, "л"])
    writer.writerow(["Поточний рівень у баку", report.current_tank_level_l, "л"])
    writer.writerow(["Кількість проведених ТО", report.total_maintenance_count, "шт"])
    writer.writerow(["- з них регламентних ТО", report.scheduled_maintenance_count, "шт"])
    writer.writerow(["- з них проміжних ТО", report.intermediate_maintenance_count, "шт"])
    writer.writerow(["Витрати на ТО та матеріали", report.total_maintenance_cost_uah, "грн"])
    writer.writerow(["Зареєстровано несправностей", report.total_faults_count, "шт"])
    writer.writerow(["Усунено несправностей", report.resolved_faults_count, "шт"])
    writer.writerow(["Відкритих несправностей", report.open_faults_count, "шт"])

    return output.getvalue()
