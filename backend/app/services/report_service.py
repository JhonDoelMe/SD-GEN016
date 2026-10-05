import io
import csv
import datetime
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.app.core.timezone import to_facility_time, now_facility
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.maintenance import MaintenanceRecord, MaintenanceSchedule
from backend.app.models.fault import Fault
from backend.app.models.audit import AuditLog
from backend.app.models.facility import Facility
from backend.app.schemas.report import OperationalReportOut


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def fmt_dt(dt: Optional[datetime.datetime]) -> str:
    if not dt:
        return "-"
    return to_facility_time(dt).strftime("%Y-%m-%d %H:%M:%S")


def fmt_date(dt: Optional[datetime.datetime]) -> str:
    if not dt:
        return "-"
    return to_facility_time(dt).strftime("%Y-%m-%d")


def fmt_time(dt: Optional[datetime.datetime]) -> str:
    if not dt:
        return "-"
    return to_facility_time(dt).strftime("%H:%M:%S")


def fmt_duration(seconds: Optional[int], hours: Optional[float]) -> str:
    if seconds is not None and seconds >= 0:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    if hours is not None and hours >= 0:
        tot_sec = int(round(hours * 3600))
        h = tot_sec // 3600
        m = (tot_sec % 3600) // 60
        s = tot_sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    return "00:00:00"


def auto_adjust_column_widths(ws, min_width=12, padding=3):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if "\n" in val_str:
                lines = val_str.split("\n")
                max_len = max(max_len, max(len(l) for l in lines))
            else:
                max_len = max(max_len, len(val_str))
        ws.column_dimensions[col_letter].width = max(max_len + padding, min_width)


# Styling Definitions
PRIMARY_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")     # Deep Navy
SECONDARY_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")   # Blue
SECTION_FILL = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")     # Teal
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")       # Light Slate
TOTAL_FILL = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")       # Total grey

HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
SECTION_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
BOLD_FONT = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
REGULAR_FONT = Font(name="Segoe UI", size=10, color="0F172A")
TOTAL_FONT = Font(name="Segoe UI", size=10, bold=True, color="1E3A8A")

THIN_BORDER_SIDE = Side(border_style="thin", color="CBD5E1")
DOUBLE_BOTTOM_SIDE = Side(border_style="double", color="1E3A8A")

CELL_BORDER = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
TOTAL_BORDER = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=DOUBLE_BOTTOM_SIDE)

ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


async def generate_operational_report(
    db: AsyncSession,
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None
) -> OperationalReportOut:
    gen_query = select(Generator)
    if generator_id:
        gen_query = gen_query.where(Generator.id == generator_id)
    elif facility_id:
        gen_query = gen_query.where(Generator.facility_id == facility_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()
    gen_name = generator.name if generator else "Генератор"

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

    # Stock & tank
    stock_q = select(FuelStock)
    if facility_id:
        stock_q = stock_q.where(FuelStock.facility_id == facility_id)
    stock_res = await db.execute(stock_q)
    stock = stock_res.scalars().first()
    stock_bal = stock.current_balance_l if stock else 0.0
    tank_bal = generator.fuel_tank_level_l if generator else 0.0

    # 4. Maintenance aggregate
    m_all_q = select(func.count(MaintenanceRecord.id), func.coalesce(func.sum(MaintenanceRecord.cost), 0.0)).where(
        MaintenanceRecord.created_at >= start_date,
        MaintenanceRecord.created_at <= end_date
    )
    if generator:
        m_all_q = m_all_q.where(MaintenanceRecord.generator_id == generator.id)
    m_all_res = await db.execute(m_all_q)
    m_count, m_cost = m_all_res.first()

    m_sched_q = select(func.count(MaintenanceRecord.id)).where(
        MaintenanceRecord.created_at >= start_date,
        MaintenanceRecord.created_at <= end_date,
        MaintenanceRecord.maintenance_type == "SCHEDULED"
    )
    if generator:
        m_sched_q = m_sched_q.where(MaintenanceRecord.generator_id == generator.id)
    m_sched_cnt = (await db.execute(m_sched_q)).scalar_one()
    m_inter_cnt = m_count - m_sched_cnt

    # 5. Faults aggregate
    f_total_q = select(func.count(Fault.id)).where(
        Fault.created_at >= start_date,
        Fault.created_at <= end_date
    )
    if generator:
        f_total_q = f_total_q.where(Fault.generator_id == generator.id)
    f_total = (await db.execute(f_total_q)).scalar_one()

    f_res_q = select(func.count(Fault.id)).where(
        Fault.created_at >= start_date,
        Fault.created_at <= end_date,
        Fault.status.in_(["RESOLVED", "CLOSED"])
    )
    if generator:
        f_res_q = f_res_q.where(Fault.generator_id == generator.id)
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


async def generate_excel_report(
    db: AsyncSession,
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    start_date: Optional[datetime.datetime] = None,
    end_date: Optional[datetime.datetime] = None
) -> bytes:
    """
    Генерує повнофункціональний, професійно оформлений звіт у форматі Excel (.xlsx).
    Містить 5 тематичних вкладок:
    1. Загальний звіт (Дашборд KPI, параметри об'єкта та генератора)
    2. Звіт по днях (Детальні цикли роботи, години, паливо, тривалість)
    3. Рух палива та Склад ГСМ (Надходження, заправки в бак, залишки)
    4. Технічне обслуговування (Журнал регламентних та проміжних ТО, витрати)
    5. Журнал інцидентів та дій (Несправності та аудит дій)
    """
    now = utc_now()
    if not end_date:
        end_date = now
    if not start_date:
        start_date = end_date - datetime.timedelta(days=30)

    # 1. Fetch Facility & Generator
    gen_query = select(Generator).options(selectinload(Generator.facility))
    if generator_id:
        gen_query = gen_query.where(Generator.id == generator_id)
    elif facility_id:
        gen_query = gen_query.where(Generator.facility_id == facility_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()

    facility = None
    if generator and generator.facility:
        facility = generator.facility
    elif facility_id:
        fac_res = await db.execute(select(Facility).where(Facility.id == facility_id))
        facility = fac_res.scalars().first()
    else:
        fac_res = await db.execute(select(Facility).order_by(Facility.id.asc()))
        facility = fac_res.scalars().first()

    facility_name = facility.name if facility else "Основний об'єкт"
    generator_name = generator.name if generator else "Бензиновий генератор"
    gen_model = generator.model if generator else "-"
    gen_serial = generator.serial_number if generator else "-"

    # 2. Fetch Operational Report Metrics
    op_report = await generate_operational_report(
        db=db,
        generator_id=generator.id if generator else None,
        facility_id=facility.id if facility else None,
        start_date=start_date,
        end_date=end_date
    )

    # 3. Fetch Maintenance Schedule
    m_sched_q = select(MaintenanceSchedule)
    if generator:
        m_sched_q = m_sched_q.where(MaintenanceSchedule.generator_id == generator.id)
    m_sched = (await db.execute(m_sched_q)).scalars().first()
    interval_hours = m_sched.interval_hours if m_sched else 300.0
    last_maint_hours = m_sched.last_performed_hours if m_sched else 0.0
    next_due_hours = m_sched.next_due_hours if m_sched else 300.0
    current_hours = generator.current_operating_hours if generator else 0.0
    hours_remaining = round(next_due_hours - current_hours, 1)

    # 4. Fetch Generator Runs
    runs_q = select(GeneratorRun).options(selectinload(GeneratorRun.user)).where(
        GeneratorRun.start_time >= start_date,
        GeneratorRun.start_time <= end_date
    )
    if generator:
        runs_q = runs_q.where(GeneratorRun.generator_id == generator.id)
    runs_q = runs_q.order_by(GeneratorRun.start_time.asc())
    runs = (await db.execute(runs_q)).scalars().all()

    # 5. Fetch Fuel Receipts
    rec_q = select(FuelReceipt).options(selectinload(FuelReceipt.user), selectinload(FuelReceipt.stock)).where(
        FuelReceipt.created_at >= start_date,
        FuelReceipt.created_at <= end_date
    )
    if facility:
        rec_q = rec_q.join(FuelStock).where(FuelStock.facility_id == facility.id)
    rec_q = rec_q.order_by(FuelReceipt.created_at.asc())
    receipts = (await db.execute(rec_q)).scalars().all()

    # 6. Fetch Fuel Transfers
    tr_q = select(FuelTransfer).options(
        selectinload(FuelTransfer.user),
        selectinload(FuelTransfer.stock),
        selectinload(FuelTransfer.generator)
    ).where(
        FuelTransfer.created_at >= start_date,
        FuelTransfer.created_at <= end_date
    )
    if generator:
        tr_q = tr_q.where(FuelTransfer.generator_id == generator.id)
    tr_q = tr_q.order_by(FuelTransfer.created_at.asc())
    transfers = (await db.execute(tr_q)).scalars().all()

    # 7. Fetch Maintenance Records
    m_q = select(MaintenanceRecord).options(
        selectinload(MaintenanceRecord.user),
        selectinload(MaintenanceRecord.generator)
    ).where(
        MaintenanceRecord.created_at >= start_date,
        MaintenanceRecord.created_at <= end_date
    )
    if generator:
        m_q = m_q.where(MaintenanceRecord.generator_id == generator.id)
    m_q = m_q.order_by(MaintenanceRecord.created_at.asc())
    maint_records = (await db.execute(m_q)).scalars().all()

    # 8. Fetch Faults
    f_q = select(Fault).options(selectinload(Fault.user)).where(
        Fault.created_at >= start_date,
        Fault.created_at <= end_date
    )
    if generator:
        f_q = f_q.where(Fault.generator_id == generator.id)
    f_q = f_q.order_by(Fault.created_at.asc())
    faults = (await db.execute(f_q)).scalars().all()

    # 9. Fetch Audit Logs
    audit_q = select(AuditLog).options(selectinload(AuditLog.user)).where(
        AuditLog.created_at >= start_date,
        AuditLog.created_at <= end_date
    ).order_by(AuditLog.created_at.desc()).limit(200)
    audit_logs = (await db.execute(audit_q)).scalars().all()

    # Create Workbook
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # -------------------------------------------------------------
    # ВКЛАДКА 1: ЗАГАЛЬНИЙ ЗВІТ
    # -------------------------------------------------------------
    ws1 = wb.create_sheet(title="Загальний звіт")
    ws1.views.sheetView[0].showGridLines = True

    # Title
    ws1.merge_cells("A1:F1")
    title_cell = ws1["A1"]
    title_cell.value = "SERVICE DESK БЕНЗИНОВОГО ГЕНЕРАТОРА — ЗАГАЛЬНИЙ ЗВІТ"
    title_cell.font = TITLE_FONT
    title_cell.alignment = ALIGN_LEFT
    ws1.row_dimensions[1].height = 28

    # Metadata Block
    export_now_str = now_facility().strftime("%Y-%m-%d %H:%M:%S")
    meta_info = [
        ("Об'єкт (локація):", facility_name, "Період звіту:", f"{op_report.start_date} — {op_report.end_date}"),
        ("Генератор:", f"{generator_name} ({gen_model})", "Дата експорту:", export_now_str),
        ("Серійний номер:", gen_serial, "Поточний статус:", generator.status if generator else "-"),
        ("Поточні мотогодини:", f"{current_hours:.1f} год", "Запас палива в баку:", f"{generator.fuel_tank_level_l if generator else 0.0:.1f} л"),
    ]
    for row_idx, (k1, v1, k2, v2) in enumerate(meta_info, start=3):
        ws1.cell(row=row_idx, column=1, value=k1).font = BOLD_FONT
        ws1.cell(row=row_idx, column=2, value=v1).font = REGULAR_FONT
        ws1.cell(row=row_idx, column=4, value=k2).font = BOLD_FONT
        ws1.cell(row=row_idx, column=5, value=v2).font = REGULAR_FONT
        ws1.row_dimensions[row_idx].height = 20

    # Summary KPI Tables
    kpi_sections = [
        (
            "1. Експлуатація та напрацювання",
            SECTION_FILL,
            [
                ("Кількість робочих циклів (пусків)", op_report.total_runs_count, "шт"),
                ("Відпрацьовано мотогодин за період", op_report.total_operating_hours, "год"),
                ("Розрахункова витрата бензину", op_report.total_calculated_consumption_l, "л"),
                ("Поточні загальні мотогодини генератора", current_hours, "год"),
            ]
        ),
        (
            "2. Паливо та запаси",
            PRIMARY_FILL,
            [
                ("Оприбутковано палива на склад", op_report.total_fuel_received_l, "л"),
                ("Загальна вартість закупленого палива", op_report.total_fuel_receipts_cost_uah, "грн"),
                ("Середня закупівельна ціна літра", op_report.avg_fuel_price_per_liter, "грн/л"),
                ("Заправлено з складу в бак генератора", op_report.total_fuel_transferred_to_tank_l, "л"),
                ("Поточний залишок на складі ГСМ", op_report.current_stock_balance_l, "л"),
                ("Поточний рівень у паливному баку", op_report.current_tank_level_l, "л"),
            ]
        ),
        (
            "3. Технічне обслуговування (ТО)",
            SECONDARY_FILL,
            [
                ("Проведено регламентних ТО (SCHEDULED)", op_report.scheduled_maintenance_count, "шт"),
                ("Проведено проміжних ТО (INTERMEDIATE)", op_report.intermediate_maintenance_count, "шт"),
                ("Загальні витрати на ТО та матеріали", op_report.total_maintenance_cost_uah, "грн"),
                ("Нормативний інтервал ТО", interval_hours, "год"),
                ("Останнє пройдене ТО на відмітці", last_maint_hours, "год"),
                ("Наступне планове ТО на відмітці", next_due_hours, "год"),
                ("Залишилося мотогодин до наступного ТО", hours_remaining, "год"),
            ]
        ),
        (
            "4. Несправності та інциденти",
            SECTION_FILL,
            [
                ("Зареєстровано інцидентів / несправностей", op_report.total_faults_count, "шт"),
                ("Усунено та закрито інцидентів", op_report.resolved_faults_count, "шт"),
                ("Відкритих активних несправностей", op_report.open_faults_count, "шт"),
            ]
        )
    ]

    curr_row = 8
    for sec_title, fill_style, items in kpi_sections:
        ws1.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=3)
        h_cell = ws1.cell(row=curr_row, column=1, value=sec_title)
        h_cell.fill = fill_style
        h_cell.font = SECTION_FONT
        h_cell.alignment = ALIGN_LEFT
        ws1.row_dimensions[curr_row].height = 24
        curr_row += 1

        for label, val, unit in items:
            c1 = ws1.cell(row=curr_row, column=1, value=label)
            c2 = ws1.cell(row=curr_row, column=2, value=val)
            c3 = ws1.cell(row=curr_row, column=3, value=unit)
            c1.font = REGULAR_FONT
            c2.font = BOLD_FONT
            c3.font = REGULAR_FONT
            c1.border = CELL_BORDER
            c2.border = CELL_BORDER
            c3.border = CELL_BORDER
            c1.alignment = ALIGN_LEFT
            c2.alignment = ALIGN_RIGHT
            c3.alignment = ALIGN_CENTER
            if isinstance(val, float):
                c2.number_format = "#,##0.00"
            elif isinstance(val, int):
                c2.number_format = "#,##0"
            ws1.row_dimensions[curr_row].height = 20
            curr_row += 1
        curr_row += 1

    auto_adjust_column_widths(ws1, min_width=15)

    # -------------------------------------------------------------
    # ВКЛАДКА 2: ЗВІТ ПО ДНЯХ (РОБОЧІ ЦИКЛИ)
    # -------------------------------------------------------------
    ws2 = wb.create_sheet(title="Звіт по днях")
    ws2.views.sheetView[0].showGridLines = True
    ws2.freeze_panes = "A2"

    headers2 = [
        "№", "Дата (РРРР-ММ-ДД)", "Час старту", "Час зупинки",
        "Тривалість (год)", "Тривалість (ГГ:ХХ:СС)",
        "Початкові мотогодини", "Кінцеві мотогодини",
        "Початкове паливо (л)", "Кінцеве паливо (л)",
        "Витрата палива (л)", "Заправка в бак (л)",
        "Оператор", "Статус", "Примітки"
    ]
    ws2.row_dimensions[1].height = 26
    for col_idx, h in enumerate(headers2, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.fill = PRIMARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER

    # Map daily transfers to runs if occurred that day
    transfers_by_date = {}
    for tr in transfers:
        d_str = to_facility_time(tr.created_at).strftime("%Y-%m-%d")
        transfers_by_date[d_str] = transfers_by_date.get(d_str, 0.0) + tr.liters

    tot_dur_hours = 0.0
    tot_cons_l = 0.0
    tot_fuel_added = 0.0

    for idx, r in enumerate(runs, start=1):
        r_row = idx + 1
        date_str = fmt_date(r.start_time)
        start_t = fmt_time(r.start_time)
        end_t = fmt_time(r.end_time) if r.end_time else "-"
        dur_h = round(r.duration_hours or 0.0, 2)
        dur_str = r.duration_formatted or fmt_duration(r.duration_seconds, r.duration_hours)
        consumption = round(r.calculated_consumption_l or 0.0, 2)
        fuel_added = round(transfers_by_date.get(date_str, 0.0), 2)
        op_name = r.user.full_name if r.user else "Оператор"

        tot_dur_hours += dur_h
        tot_cons_l += consumption
        tot_fuel_added += fuel_added

        values = [
            idx,
            date_str,
            start_t,
            end_t,
            dur_h,
            dur_str,
            r.start_hours,
            r.end_hours or "-",
            r.start_fuel_level_l if r.start_fuel_level_l is not None else "-",
            r.end_fuel_level_l if r.end_fuel_level_l is not None else "-",
            consumption,
            fuel_added if fuel_added > 0 else "-",
            op_name,
            r.status,
            r.note or ""
        ]

        ws2.row_dimensions[r_row].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(values, start=1):
            cell = ws2.cell(row=r_row, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill

            if c_idx in [1, 2, 3, 4, 6, 14]:
                cell.alignment = ALIGN_CENTER
            elif c_idx in [5, 7, 8, 9, 10, 11, 12]:
                cell.alignment = ALIGN_RIGHT
                if isinstance(val, float):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = ALIGN_LEFT

    # Total row for Sheet 2
    last_r = len(runs) + 2
    ws2.row_dimensions[last_r].height = 22
    for c_idx in range(1, len(headers2) + 1):
        cell = ws2.cell(row=last_r, column=c_idx)
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        cell.font = TOTAL_FONT

    ws2.cell(row=last_r, column=1, value="РАЗОМ").alignment = ALIGN_CENTER
    c_tot_dur = ws2.cell(row=last_r, column=5, value=round(tot_dur_hours, 2))
    c_tot_dur.alignment = ALIGN_RIGHT
    c_tot_dur.number_format = "#,##0.00"

    tot_dur_formatted = fmt_duration(None, tot_dur_hours)
    ws2.cell(row=last_r, column=6, value=tot_dur_formatted).alignment = ALIGN_CENTER

    c_tot_cons = ws2.cell(row=last_r, column=11, value=round(tot_cons_l, 2))
    c_tot_cons.alignment = ALIGN_RIGHT
    c_tot_cons.number_format = "#,##0.00"

    if tot_fuel_added > 0:
        c_tot_add = ws2.cell(row=last_r, column=12, value=round(tot_fuel_added, 2))
        c_tot_add.alignment = ALIGN_RIGHT
        c_tot_add.number_format = "#,##0.00"

    ws2.auto_filter.ref = f"A1:{get_column_letter(len(headers2))}{last_r - 1}"
    auto_adjust_column_widths(ws2, min_width=12)

    # -------------------------------------------------------------
    # ВКЛАДКА 3: РУХ ПАЛИВА ТА СКЛАД ГСМ
    # -------------------------------------------------------------
    ws3 = wb.create_sheet(title="Рух палива та Склад ГСМ")
    ws3.views.sheetView[0].showGridLines = True
    ws3.freeze_panes = "A3"

    # Section 1: Receipts
    ws3.merge_cells("A1:K1")
    s1_title = ws3["A1"]
    s1_title.value = "1. Оприбуткування палива на склад ГСМ (закупівля / чеки)"
    s1_title.font = SECTION_FONT
    s1_title.fill = PRIMARY_FILL
    s1_title.alignment = ALIGN_LEFT
    ws3.row_dimensions[1].height = 24

    headers3_rec = [
        "№", "Дата / Час", "Склад ГСМ", "Чек / Накладна №",
        "Водій / Постачальник", "Тип палива", "Об'єм (л)",
        "Сума (грн)", "Ціна за літр (грн/л)", "Хто прийняв", "Коментар"
    ]
    ws3.row_dimensions[2].height = 24
    for c_idx, h in enumerate(headers3_rec, start=1):
        cell = ws3.cell(row=2, column=c_idx, value=h)
        cell.fill = SECONDARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER

    tot_rec_l = 0.0
    tot_rec_uah = 0.0
    row_cur = 3
    for idx, rc in enumerate(receipts, start=1):
        tot_rec_l += rc.liters
        tot_rec_uah += rc.cost_total
        stock_name = rc.stock.name if rc.stock else "Склад ГСМ"
        rec_user = rc.user.full_name if rc.user else "Користувач"
        vals = [
            idx,
            fmt_dt(rc.created_at),
            stock_name,
            rc.receipt_number,
            rc.driver_name,
            rc.fuel_type,
            rc.liters,
            rc.cost_total,
            rc.price_per_liter,
            rec_user,
            rc.comment or ""
        ]
        ws3.row_dimensions[row_cur].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(vals, start=1):
            cell = ws3.cell(row=row_cur, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill
            if c_idx in [1, 2, 4, 6]:
                cell.alignment = ALIGN_CENTER
            elif c_idx in [7, 8, 9]:
                cell.alignment = ALIGN_RIGHT
                if isinstance(val, (int, float)):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = ALIGN_LEFT
        row_cur += 1

    # Receipts Total Row
    ws3.row_dimensions[row_cur].height = 22
    for c_idx in range(1, len(headers3_rec) + 1):
        cell = ws3.cell(row=row_cur, column=c_idx)
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        cell.font = TOTAL_FONT
    ws3.cell(row=row_cur, column=1, value="РАЗОМ").alignment = ALIGN_CENTER
    c_tot_l = ws3.cell(row=row_cur, column=7, value=round(tot_rec_l, 2))
    c_tot_l.alignment = ALIGN_RIGHT
    c_tot_l.number_format = "#,##0.00"
    c_tot_u = ws3.cell(row=row_cur, column=8, value=round(tot_rec_uah, 2))
    c_tot_u.alignment = ALIGN_RIGHT
    c_tot_u.number_format = "#,##0.00"
    if tot_rec_l > 0:
        c_avg = ws3.cell(row=row_cur, column=9, value=round(tot_rec_uah / tot_rec_l, 2))
        c_avg.alignment = ALIGN_RIGHT
        c_avg.number_format = "#,##0.00"
    row_cur += 3

    # Section 2: Transfers to Tank
    ws3.merge_cells(start_row=row_cur, start_column=1, end_row=row_cur, end_column=10)
    s2_title = ws3.cell(row=row_cur, column=1, value="2. Заправки зі складу ГСМ у бак генератора")
    s2_title.font = SECTION_FONT
    s2_title.fill = PRIMARY_FILL
    s2_title.alignment = ALIGN_LEFT
    ws3.row_dimensions[row_cur].height = 24
    row_cur += 1

    headers3_tr = [
        "№", "Дата / Час", "Звідки (Склад ГСМ)", "Куди (Генератор)",
        "Заправлено (л)", "Склад до (л)", "Склад після (л)",
        "Бак до (л)", "Бак після (л)", "Оператор"
    ]
    ws3.row_dimensions[row_cur].height = 24
    for c_idx, h in enumerate(headers3_tr, start=1):
        cell = ws3.cell(row=row_cur, column=c_idx, value=h)
        cell.fill = SECONDARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER
    row_cur += 1

    tot_tr_l = 0.0
    for idx, tr in enumerate(transfers, start=1):
        tot_tr_l += tr.liters
        stock_name = tr.stock.name if tr.stock else "Склад ГСМ"
        gen_tr_name = tr.generator.name if tr.generator else generator_name
        tr_user = tr.user.full_name if tr.user else "Оператор"
        vals = [
            idx,
            fmt_dt(tr.created_at),
            stock_name,
            gen_tr_name,
            tr.liters,
            tr.source_balance_before,
            tr.source_balance_after,
            tr.tank_balance_before,
            tr.tank_balance_after,
            tr_user
        ]
        ws3.row_dimensions[row_cur].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(vals, start=1):
            cell = ws3.cell(row=row_cur, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill
            if c_idx in [1, 2]:
                cell.alignment = ALIGN_CENTER
            elif c_idx in [5, 6, 7, 8, 9]:
                cell.alignment = ALIGN_RIGHT
                if isinstance(val, (int, float)):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = ALIGN_LEFT
        row_cur += 1

    # Transfers Total Row
    ws3.row_dimensions[row_cur].height = 22
    for c_idx in range(1, len(headers3_tr) + 1):
        cell = ws3.cell(row=row_cur, column=c_idx)
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        cell.font = TOTAL_FONT
    ws3.cell(row=row_cur, column=1, value="РАЗОМ").alignment = ALIGN_CENTER
    c_tot_trl = ws3.cell(row=row_cur, column=5, value=round(tot_tr_l, 2))
    c_tot_trl.alignment = ALIGN_RIGHT
    c_tot_trl.number_format = "#,##0.00"

    auto_adjust_column_widths(ws3, min_width=12)

    # -------------------------------------------------------------
    # ВКЛАДКА 4: ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ (ТО)
    # -------------------------------------------------------------
    ws4 = wb.create_sheet(title="Технічне обслуговування")
    ws4.views.sheetView[0].showGridLines = True
    ws4.freeze_panes = "A2"

    headers4 = [
        "№", "Дата / Час", "Генератор", "Тип ТО",
        "Мотогодини при ТО", "Опис виконаних робіт",
        "Використані матеріали / запчастини", "Вартість (грн)",
        "Виконавець", "Примітки"
    ]
    ws4.row_dimensions[1].height = 26
    for c_idx, h in enumerate(headers4, start=1):
        cell = ws4.cell(row=1, column=c_idx, value=h)
        cell.fill = PRIMARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER

    tot_maint_cost = 0.0
    for idx, mr in enumerate(maint_records, start=1):
        r_row = idx + 1
        tot_maint_cost += mr.cost or 0.0
        m_gen = mr.generator.name if mr.generator else generator_name
        m_user = mr.user.full_name if mr.user else "Майстер"
        type_trans = "Регламентне ТО" if mr.maintenance_type == "SCHEDULED" else "Проміжне ТО"
        vals = [
            idx,
            fmt_dt(mr.created_at),
            m_gen,
            type_trans,
            mr.operating_hours,
            mr.work_description,
            mr.consumables_used or "-",
            mr.cost,
            m_user,
            mr.comment or ""
        ]
        ws4.row_dimensions[r_row].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(vals, start=1):
            cell = ws4.cell(row=r_row, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill
            if c_idx in [1, 2, 4]:
                cell.alignment = ALIGN_CENTER
            elif c_idx in [5, 8]:
                cell.alignment = ALIGN_RIGHT
                if isinstance(val, (int, float)):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = ALIGN_LEFT

    # Total row Sheet 4
    last_r4 = len(maint_records) + 2
    ws4.row_dimensions[last_r4].height = 22
    for c_idx in range(1, len(headers4) + 1):
        cell = ws4.cell(row=last_r4, column=c_idx)
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        cell.font = TOTAL_FONT
    ws4.cell(row=last_r4, column=1, value="РАЗОМ").alignment = ALIGN_CENTER
    c_m_tot = ws4.cell(row=last_r4, column=8, value=round(tot_maint_cost, 2))
    c_m_tot.alignment = ALIGN_RIGHT
    c_m_tot.number_format = "#,##0.00"

    ws4.auto_filter.ref = f"A1:{get_column_letter(len(headers4))}{last_r4 - 1}"
    auto_adjust_column_widths(ws4, min_width=12)

    # -------------------------------------------------------------
    # ВКЛАДКА 5: ЖУРНАЛ ІНЦИДЕНТІВ ТА АУДИТ
    # -------------------------------------------------------------
    ws5 = wb.create_sheet(title="Журнал інцидентів та дій")
    ws5.views.sheetView[0].showGridLines = True
    ws5.freeze_panes = "A3"

    # Section 1: Faults
    ws5.merge_cells("A1:H1")
    f_title = ws5["A1"]
    f_title.value = "1. Журнал несправностей та інцидентів"
    f_title.font = SECTION_FONT
    f_title.fill = PRIMARY_FILL
    f_title.alignment = ALIGN_LEFT
    ws5.row_dimensions[1].height = 24

    headers5_f = [
        "№", "Дата / Час", "Статус", "Вплив на роботу",
        "Опис несправності", "Дії з усунення", "Хто зафіксував", "Вирішено"
    ]
    ws5.row_dimensions[2].height = 24
    for c_idx, h in enumerate(headers5_f, start=1):
        cell = ws5.cell(row=2, column=c_idx, value=h)
        cell.fill = SECONDARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER

    row_f = 3
    for idx, fl in enumerate(faults, start=1):
        f_user = fl.user.full_name if fl.user else "Користувач"
        resolved_t = fmt_dt(fl.resolved_at) if fl.resolved_at else "Не усунено"
        vals = [
            idx,
            fmt_dt(fl.created_at),
            fl.status,
            fl.operational_impact,
            fl.description,
            fl.resolution_actions or "-",
            f_user,
            resolved_t
        ]
        ws5.row_dimensions[row_f].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(vals, start=1):
            cell = ws5.cell(row=row_f, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill
            if c_idx in [1, 2, 3, 4, 8]:
                cell.alignment = ALIGN_CENTER
            else:
                cell.alignment = ALIGN_LEFT
        row_f += 1

    row_f += 2

    # Section 2: Audit Logs
    ws5.merge_cells(start_row=row_f, start_column=1, end_row=row_f, end_column=7)
    a_title = ws5.cell(row=row_f, column=1, value="2. Журнал операційного аудиту (останні ключові дії)")
    a_title.font = SECTION_FONT
    a_title.fill = PRIMARY_FILL
    a_title.alignment = ALIGN_LEFT
    ws5.row_dimensions[row_f].height = 24
    row_f += 1

    headers5_a = [
        "№", "Дата / Час", "Дія", "Сутність", "Користувач", "IP-адреса", "Деталі"
    ]
    ws5.row_dimensions[row_f].height = 24
    for c_idx, h in enumerate(headers5_a, start=1):
        cell = ws5.cell(row=row_f, column=c_idx, value=h)
        cell.fill = SECONDARY_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = CELL_BORDER
    row_f += 1

    for idx, al in enumerate(audit_logs, start=1):
        a_user = al.user.full_name if al.user else "Система"
        details_str = str(al.details_json) if al.details_json else ""
        vals = [
            idx,
            fmt_dt(al.created_at),
            al.action,
            f"{al.entity_type} #{al.entity_id or ''}",
            a_user,
            al.ip_address or "-",
            details_str
        ]
        ws5.row_dimensions[row_f].height = 20
        fill = ZEBRA_FILL if idx % 2 == 0 else PatternFill(fill_type=None)
        for c_idx, val in enumerate(vals, start=1):
            cell = ws5.cell(row=row_f, column=c_idx, value=val)
            cell.font = REGULAR_FONT
            cell.border = CELL_BORDER
            if fill.fill_type:
                cell.fill = fill
            if c_idx in [1, 2, 3, 4, 6]:
                cell.alignment = ALIGN_CENTER
            else:
                cell.alignment = ALIGN_LEFT
        row_f += 1

    auto_adjust_column_widths(ws5, min_width=12)

    # Save workbook to memory
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
