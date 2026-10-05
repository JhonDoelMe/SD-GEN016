from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.schemas.fuel import FuelReceiptCreate, FuelTransferCreate, FuelBalancesSummary
from backend.app.services.audit_service import log_audit


async def get_or_create_default_stock(db: AsyncSession) -> FuelStock:
    res = await db.execute(select(FuelStock))
    stock = res.scalars().first()
    if not stock:
        stock = FuelStock(name="Основний склад ГСМ", fuel_type="А-95", current_balance_l=0.0)
        db.add(stock)
        await db.flush()
    return stock


async def add_fuel_receipt(
    db: AsyncSession,
    receipt_data: FuelReceiptCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelReceipt:
    stock = await db.get(FuelStock, receipt_data.stock_id) if receipt_data.stock_id else await get_or_create_default_stock(db)
    if not stock:
        stock = await get_or_create_default_stock(db)

    if receipt_data.liters <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість літрів має бути більше 0")
    if receipt_data.cost_total <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сума за чеком має бути більше 0")

    price_per_l = round(receipt_data.cost_total / receipt_data.liters, 2)

    receipt = FuelReceipt(
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
    stock = await db.get(FuelStock, transfer_data.stock_id) if transfer_data.stock_id else await get_or_create_default_stock(db)
    if not stock:
        stock = await get_or_create_default_stock(db)

    # Fetch generator
    gen_res = await db.execute(select(Generator))
    generator = await db.get(Generator, transfer_data.generator_id) if transfer_data.generator_id else gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

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


async def get_fuel_balances_summary(db: AsyncSession) -> FuelBalancesSummary:
    stock = await get_or_create_default_stock(db)
    gen_res = await db.execute(select(Generator))
    generator = gen_res.scalars().first()

    tank_balance = generator.fuel_tank_level_l if generator else 0.0
    tank_capacity = generator.tank_capacity_l if generator else 25.0

    # Receipts aggregate
    rec_res = await db.execute(
        select(
            func.coalesce(func.sum(FuelReceipt.liters), 0.0),
            func.coalesce(func.sum(FuelReceipt.cost_total), 0.0)
        )
    )
    total_received_l, total_spent_uah = rec_res.first()

    avg_price = round(total_spent_uah / total_received_l, 2) if total_received_l > 0 else 0.0

    # Transfers aggregate
    tr_res = await db.execute(
        select(func.coalesce(func.sum(FuelTransfer.liters), 0.0))
    )
    total_transferred_l = tr_res.scalar_one()

    # Consumed aggregate
    runs_res = await db.execute(
        select(func.coalesce(func.sum(GeneratorRun.calculated_consumption_l), 0.0))
    )
    total_consumed_l = runs_res.scalar_one()

    return FuelBalancesSummary(
        warehouse_balance_l=round(stock.current_balance_l, 2),
        tank_balance_l=round(tank_balance, 2),
        tank_capacity_l=round(tank_capacity, 2),
        total_received_l=round(total_received_l, 2),
        total_spent_uah=round(total_spent_uah, 2),
        avg_price_per_liter=avg_price,
        total_transferred_l=round(total_transferred_l, 2),
        total_calculated_consumed_l=round(total_consumed_l, 2)
    )
