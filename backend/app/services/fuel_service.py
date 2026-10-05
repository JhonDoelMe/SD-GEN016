from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.facility import Facility
from backend.app.schemas.fuel import (
    FuelStockCreate, FuelReceiptCreate, FuelTransferCreate, FuelBalancesSummary
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
    if receipt_data.cost_total <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сума за чеком має бути більше 0")

    price_per_l = round(receipt_data.cost_total / receipt_data.liters, 2)

    receipt = FuelReceipt(
        facility_id=facility_id,
        stock_id=stock.id,
        user_id=user_id,
        fuel_type=receipt_data.fuel_type or stock.fuel_type,
        liters=round(receipt_data.liters, 2),
        cost_total=round(receipt_data.cost_total, 2),
        price_per_liter=price_per_l,
        driver_name=receipt_data.driver_name.strip(),
        receipt_number=receipt_data.receipt_number.strip(),
        comment=receipt_data.comment
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

