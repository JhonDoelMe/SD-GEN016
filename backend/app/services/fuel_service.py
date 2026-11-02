from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy import select, func, or_, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer, utc_now
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.facility import Facility
from backend.app.schemas.fuel import (
    FuelStockCreate, FuelStockUpdate, FuelReceiptCreate, FuelTransferCreate, FuelBalancesSummary
)
from backend.app.services.audit_service import log_audit


async def get_or_create_default_stock(db: AsyncSession, facility_id: Optional[int] = None) -> FuelStock:
    query = select(FuelStock).options(selectinload(FuelStock.facility))
    if facility_id:
        query = query.where(FuelStock.facility_id == facility_id)
    res = await db.execute(query)
    stock = res.scalars().first()
    if not stock:
        res_any = await db.execute(select(FuelStock).options(selectinload(FuelStock.facility)))
        stock = res_any.scalars().first()
        if not stock:
            stock = FuelStock(
                facility_id=facility_id or 1,
                name="Основний склад ГСМ",
                fuel_type="А-95",
                current_balance_l=0.0
            )
            db.add(stock)
            await db.flush()
    return stock


async def list_fuel_stocks(db: AsyncSession, facility_id: Optional[int] = None) -> List[FuelStock]:
    """Список усіх складів ГСМ, опціонально за об'єктом"""
    query = select(FuelStock).options(selectinload(FuelStock.facility))
    if facility_id:
        query = query.where(FuelStock.facility_id == facility_id)
    res = await db.execute(query.order_by(FuelStock.id.asc()))
    stocks = res.scalars().all()
    if not stocks and facility_id:
        # Автоматично забезпечуємо хоча б один склад для об'єкта
        def_stock = await get_or_create_default_stock(db, facility_id=facility_id)
        return [def_stock]
    return stocks


async def create_fuel_stock(
    db: AsyncSession,
    data: FuelStockCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelStock:
    """Створити новий склад ГСМ для об'єкта"""
    fac = await db.get(Facility, data.facility_id)
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Об'єкт не знайдено")

    stock = FuelStock(
        facility_id=data.facility_id,
        name=data.name.strip(),
        fuel_type=data.fuel_type.strip(),
        current_balance_l=round(data.initial_balance_l, 2)
    )
    db.add(stock)
    await db.flush()

    await log_audit(
        db=db,
        action="FUEL_STOCK_CREATED",
        entity_type="FuelStock",
        entity_id=str(stock.id),
        user_id=user_id,
        details={
            "name": stock.name,
            "facility_id": stock.facility_id,
            "fuel_type": stock.fuel_type,
            "initial_balance_l": stock.current_balance_l
        },
        ip_address=ip_address
    )
    await db.commit()

    res = await db.execute(
        select(FuelStock).options(selectinload(FuelStock.facility)).where(FuelStock.id == stock.id)
    )
    return res.scalars().first()


async def update_fuel_stock(
    db: AsyncSession,
    stock_id: int,
    data: FuelStockUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelStock:
    """Оновити склад ГСМ (назву, тип палива, об'єкт)"""
    stock = await db.get(FuelStock, stock_id)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")

    old_details = {
        "name": stock.name,
        "fuel_type": stock.fuel_type,
        "facility_id": stock.facility_id
    }

    if data.name is not None and data.name.strip():
        stock.name = data.name.strip()
    if data.fuel_type is not None and data.fuel_type.strip():
        stock.fuel_type = data.fuel_type.strip()
    if data.facility_id is not None:
        fac = await db.get(Facility, data.facility_id)
        if not fac:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Цільовий об'єкт не знайдено")
        stock.facility_id = data.facility_id

    stock.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="FUEL_STOCK_UPDATED",
        entity_type="FuelStock",
        entity_id=str(stock.id),
        user_id=user_id,
        details={
            "old": old_details,
            "new": {
                "name": stock.name,
                "fuel_type": stock.fuel_type,
                "facility_id": stock.facility_id
            }
        },
        ip_address=ip_address
    )
    await db.commit()

    res = await db.execute(
        select(FuelStock).options(selectinload(FuelStock.facility)).where(FuelStock.id == stock.id)
    )
    return res.scalars().first()


async def delete_fuel_stock(
    db: AsyncSession,
    stock_id: int,
    user_id: int,
    ip_address: Optional[str] = None
) -> dict:
    """Видалити склад ГСМ із безпечним перенесенням залишків та історії на інший склад об'єкта"""
    stock = await db.get(FuelStock, stock_id)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")

    # Перевірка: не дозволяти видалити останній склад на об'єкті
    stocks_count = await db.scalar(
        select(func.count(FuelStock.id)).where(FuelStock.facility_id == stock.facility_id)
    )
    if (stocks_count or 0) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо видалити єдиний склад ГСМ на цьому об'єкті. Створіть інший склад перед видаленням."
        )

    # Знаходимо альтернативний склад цього ж об'єкта
    alt_stock = await db.scalar(
        select(FuelStock)
        .where(FuelStock.facility_id == stock.facility_id, FuelStock.id != stock.id)
        .order_by(FuelStock.id.asc())
    )

    stock_name = stock.name
    stock_balance = stock.current_balance_l

    # Якщо на складі був залишок — безпечно переносимо його на альтернативний склад
    if alt_stock and stock_balance > 0:
        alt_stock.current_balance_l = round(alt_stock.current_balance_l + stock_balance, 2)
        alt_stock.updated_at = utc_now()

    # Переприв'язуємо чеки та переміщення, щоб зберегти фінансову історію
    if alt_stock:
        await db.execute(
            update(FuelReceipt).where(FuelReceipt.stock_id == stock_id).values(stock_id=alt_stock.id)
        )
        await db.execute(
            update(FuelTransfer).where(FuelTransfer.stock_id == stock_id).values(stock_id=alt_stock.id)
        )

    await db.delete(stock)
    await db.flush()

    await log_audit(
        db=db,
        action="FUEL_STOCK_DELETED",
        entity_type="FuelStock",
        entity_id=str(stock_id),
        user_id=user_id,
        details={
            "deleted_stock_name": stock_name,
            "transferred_balance_l": stock_balance,
            "target_stock_id": alt_stock.id if alt_stock else None,
            "target_stock_name": alt_stock.name if alt_stock else None
        },
        ip_address=ip_address
    )
    await db.commit()

    return {
        "ok": True,
        "detail": f"Склад '{stock_name}' успішно видалено" + (
            f". Залишок {stock_balance:.1f} л перенесено на склад '{alt_stock.name}'" if (alt_stock and stock_balance > 0) else ""
        )
    }


async def add_fuel_receipt(
    db: AsyncSession,
    receipt_data: FuelReceiptCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelReceipt:
    stock = None
    if receipt_data.stock_id:
        stock = await db.get(FuelStock, receipt_data.stock_id)
    if not stock:
        stock = await get_or_create_default_stock(db, facility_id=receipt_data.facility_id)

    facility_id = receipt_data.facility_id or stock.facility_id or 1

    if receipt_data.liters <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість літрів має бути більше 0")

    effective_fuel_type = receipt_data.fuel_type or stock.fuel_type or "А-95"
    price_source = "manual_total"

    if receipt_data.cost_total is not None and receipt_data.cost_total > 0:
        cost_total = round(receipt_data.cost_total, 2)
        price_per_l = round(cost_total / receipt_data.liters, 2)
        price_source = "manual_total"
    elif receipt_data.price_per_liter is not None and receipt_data.price_per_liter > 0:
        price_per_l = round(receipt_data.price_per_liter, 2)
        cost_total = round(receipt_data.liters * price_per_l, 2)
        price_source = "manual_unit_price"
    else:
        from backend.app.services.settings_service import resolve_fuel_price_per_liter
        price_per_l, price_source = await resolve_fuel_price_per_liter(db, effective_fuel_type)
        cost_total = round(receipt_data.liters * price_per_l, 2)

    # Fuel Receipt Safeguard: Scale & Price Sanity Checks
    from backend.app.services.settings_service import get_runtime_setting
    max_liters_warn = float(get_runtime_setting("fuel_receipt_max_liters_warning", 1000.0))
    min_price_warn = float(get_runtime_setting("fuel_receipt_min_price", 15.0))
    max_price_warn = float(get_runtime_setting("fuel_receipt_max_price", 250.0))

    if not receipt_data.force_confirm:
        if receipt_data.liters > max_liters_warn:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Запобіжник об'єму палива: вказано значний об'єм ({receipt_data.liters:.1f} л > {max_liters_warn:.0f} л). "
                    f"Перевірте введені дані (можлива опечатка) або підтвердіть дію."
                )
            )
        if price_per_l < min_price_warn or price_per_l > max_price_warn:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Запобіжник вартості палива: розрахункова ціна ({price_per_l:.2f} грн/л) виходить за межі "
                    f"очікуваного діапазону ({min_price_warn:.0f} - {max_price_warn:.0f} грн/л). "
                    f"Перевірте суму чека або підтвердіть дію."
                )
            )

    comment_text = receipt_data.comment
    if price_source in ("system_settings", "internet"):
        src_ua = "Налаштування системи" if price_source == "system_settings" else "Авто-ціна з інтернету"
        auto_note = f"[Авторозрахунок: {price_per_l:.2f} грн/л ({src_ua})]"
        comment_text = f"{comment_text} {auto_note}".strip() if comment_text else auto_note

    receipt = FuelReceipt(
        facility_id=facility_id,
        stock_id=stock.id,
        user_id=user_id,
        fuel_type=effective_fuel_type,
        liters=round(receipt_data.liters, 2),
        cost_total=cost_total,
        price_per_liter=price_per_l,
        driver_name=receipt_data.driver_name.strip(),
        receipt_number=receipt_data.receipt_number.strip(),
        comment=comment_text
    )
    db.add(receipt)

    stock_before = stock.current_balance_l
    stock.current_balance_l = round(stock.current_balance_l + receipt.liters, 2)

    await db.flush()

    await log_audit(
        db=db,
        action="FUEL_RECEIPT",
        entity_type="FuelStock",
        entity_id=str(stock.id),
        user_id=user_id,
        details={
            "receipt_id": receipt.id,
            "facility_id": facility_id,
            "stock_id": stock.id,
            "stock_name": stock.name,
            "liters": receipt.liters,
            "cost_total": receipt.cost_total,
            "price_per_l": price_per_l,
            "price_source": price_source,
            "stock_before": stock_before,
            "stock_after": stock.current_balance_l,
            "receipt_no": receipt.receipt_number,
            "driver": receipt.driver_name,
        },
        ip_address=ip_address
    )
    await db.commit()
    return receipt


async def transfer_fuel_to_tank(
    db: AsyncSession,
    transfer_data: FuelTransferCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelTransfer:
    stock = await db.get(FuelStock, transfer_data.stock_id) if transfer_data.stock_id else await get_or_create_default_stock(db, facility_id=transfer_data.facility_id)
    if not stock:
        stock = await get_or_create_default_stock(db, facility_id=transfer_data.facility_id)

    # Fetch generator
    gen_res = await db.execute(select(Generator))
    generator = await db.get(Generator, transfer_data.generator_id) if transfer_data.generator_id else gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    # Invariant: cross-facility fuel transfer protection
    if generator.facility_id and stock.facility_id and int(generator.facility_id) != int(stock.facility_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неможливо виконати заправку: генератор '{generator.name}' (об'єкт ID {generator.facility_id}) та склад ГСМ '{stock.name}' (об'єкт ID {stock.facility_id}) належать до різних об'єктів"
        )

    facility_id = transfer_data.facility_id or generator.facility_id or stock.facility_id or 1

    if transfer_data.liters <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість літрів заправки має бути більше 0")

    # Invariant: cannot take more than stock balance (no negative balances!)
    if stock.current_balance_l < transfer_data.liters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недостатньо палива на складі ГСМ! Доступно: {stock.current_balance_l:.1f} л, запитано: {transfer_data.liters:.1f} л"
        )

    # Invariant: cannot overflow generator tank capacity
    target_tank_level = generator.fuel_tank_level_l + transfer_data.liters
    if target_tank_level > generator.tank_capacity_l:
        max_possible = round(generator.tank_capacity_l - generator.fuel_tank_level_l, 1)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Перевищення місткості бака! Місткість: {generator.tank_capacity_l} л, поточний рівень: {generator.fuel_tank_level_l} л. Можна додати максимум: {max_possible} л"
        )

    src_before = stock.current_balance_l
    src_after = round(stock.current_balance_l - transfer_data.liters, 2)

    tank_before = generator.fuel_tank_level_l
    tank_after = round(target_tank_level, 2)

    stock.current_balance_l = src_after
    generator.fuel_tank_level_l = tank_after

    transfer = FuelTransfer(
        facility_id=facility_id,
        stock_id=stock.id,
        generator_id=generator.id,
        user_id=user_id,
        liters=round(transfer_data.liters, 2),
        source_balance_before=src_before,
        source_balance_after=src_after,
        tank_balance_before=tank_before,
        tank_balance_after=tank_after,
        comment=transfer_data.comment
    )
    db.add(transfer)
    await db.flush()

    await log_audit(
        db=db,
        action="FUEL_TRANSFER_TO_TANK",
        entity_type="FuelTransfer",
        entity_id=str(transfer.id),
        user_id=user_id,
        details={
            "facility_id": facility_id,
            "stock_id": stock.id,
            "generator_id": generator.id,
            "liters": transfer.liters,
            "stock_before": src_before,
            "stock_after": src_after,
            "tank_before": tank_before,
            "tank_after": tank_after,
        },
        ip_address=ip_address
    )
    await db.commit()
    return transfer


async def get_fuel_balances_summary(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None
) -> FuelBalancesSummary:
    stock = await get_or_create_default_stock(db, facility_id=facility_id)

    gen_query = select(Generator)
    if generator_id:
        gen_query = gen_query.where(Generator.id == generator_id)
    elif facility_id:
        gen_query = gen_query.where(Generator.facility_id == facility_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()

    tank_balance = generator.fuel_tank_level_l if generator else 0.0
    tank_capacity = generator.tank_capacity_l if generator else 25.0

    # Total warehouse balance across all stocks of this facility (or overall)
    if facility_id:
        tot_stock_q = select(func.coalesce(func.sum(FuelStock.current_balance_l), 0.0)).where(FuelStock.facility_id == facility_id)
        warehouse_balance = (await db.execute(tot_stock_q)).scalar_one()
    else:
        warehouse_balance = stock.current_balance_l

    # Receipts aggregate
    rec_query = select(
        func.coalesce(func.sum(FuelReceipt.liters), 0.0),
        func.coalesce(func.sum(FuelReceipt.cost_total), 0.0)
    )
    if facility_id:
        rec_query = rec_query.outerjoin(FuelStock, FuelReceipt.stock_id == FuelStock.id).where(
            or_(FuelReceipt.facility_id == facility_id, FuelStock.facility_id == facility_id)
        )
    else:
        rec_query = rec_query.where(FuelReceipt.stock_id == stock.id)
    rec_res = await db.execute(rec_query)
    total_received_l, total_spent_uah = rec_res.first()

    avg_price = round(total_spent_uah / total_received_l, 2) if total_received_l > 0 else 0.0

    # Transfers aggregate
    tr_query = select(func.coalesce(func.sum(FuelTransfer.liters), 0.0))
    if generator:
        tr_query = tr_query.where(FuelTransfer.generator_id == generator.id)
    elif facility_id:
        tr_query = tr_query.where(FuelTransfer.facility_id == facility_id)
    tr_res = await db.execute(tr_query)
    total_transferred_l = tr_res.scalar_one()

    # Consumed aggregate
    runs_query = select(func.coalesce(func.sum(GeneratorRun.calculated_consumption_l), 0.0))
    if generator:
        runs_query = runs_query.where(GeneratorRun.generator_id == generator.id)
    runs_res = await db.execute(runs_query)
    total_consumed_l = runs_res.scalar_one()

    return FuelBalancesSummary(
        warehouse_balance_l=round(warehouse_balance, 2),
        tank_balance_l=round(tank_balance, 2),
        tank_capacity_l=round(tank_capacity, 2),
        total_received_l=round(total_received_l, 2),
        total_spent_uah=round(total_spent_uah, 2),
        avg_price_per_liter=avg_price,
        total_transferred_l=round(total_transferred_l, 2),
        total_calculated_consumed_l=round(total_consumed_l, 2)
    )

