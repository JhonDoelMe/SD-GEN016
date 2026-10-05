from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.generator import Generator
from backend.app.models.facility import Facility
from backend.app.schemas.fuel import (
    FuelStockCreate, FuelStockOut, FuelReceiptCreate, FuelReceiptOut,
    FuelTransferCreate, FuelTransferOut, FuelBalancesSummary
)
from backend.app.api.deps import get_current_user, require_permission, get_client_ip
from backend.app.services.fuel_service import (
    get_or_create_default_stock, list_fuel_stocks, create_fuel_stock,
    add_fuel_receipt, transfer_fuel_to_tank, get_fuel_balances_summary
)

router = APIRouter(prefix="/fuel", tags=["Паливо"])


@router.get("/summary", response_model=FuelBalancesSummary)
async def fuel_summary(
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_fuel_balances_summary(db, facility_id=facility_id, generator_id=generator_id)


@router.get("/stocks", response_model=List[FuelStockOut])
async def get_stocks_list(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список усіх складів ГСМ (за об'єктом або загальний)"""
    stocks = await list_fuel_stocks(db, facility_id=facility_id)
    return [
        FuelStockOut(
            id=s.id,
            facility_id=s.facility_id,
            facility_name=s.facility.name if s.facility else None,
            name=s.name,
            fuel_type=s.fuel_type,
            current_balance_l=s.current_balance_l,
            updated_at=s.updated_at
        )
        for s in stocks
    ]


@router.post("/stock/new", response_model=FuelStockOut, status_code=status.HTTP_201_CREATED)
async def create_stock_api(
    data: FuelStockCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:receipt"))
):
    """Створити новий склад ГСМ для обраного об'єкта"""
    client_ip = get_client_ip(request)
    stock = await create_fuel_stock(db, data, current_user.id, client_ip)
    return FuelStockOut(
        id=stock.id,
        facility_id=stock.facility_id,
        facility_name=stock.facility.name if stock.facility else None,
        name=stock.name,
        fuel_type=stock.fuel_type,
        current_balance_l=stock.current_balance_l,
        updated_at=stock.updated_at
    )


@router.get("/stock", response_model=FuelStockOut)
async def get_stock(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stock = await get_or_create_default_stock(db, facility_id=facility_id)
    return FuelStockOut(
        id=stock.id,
        facility_id=stock.facility_id,
        facility_name=stock.facility.name if stock.facility else None,
        name=stock.name,
        fuel_type=stock.fuel_type,
        current_balance_l=stock.current_balance_l,
        updated_at=stock.updated_at
    )


@router.post("/receipt", response_model=FuelReceiptOut, status_code=status.HTTP_201_CREATED)
async def create_receipt(
    data: FuelReceiptCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:receipt"))
):
    receipt = await add_fuel_receipt(
        db=db,
        receipt_data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    # Eagerly fetch stock & facility details
    stock = None
    fac_name = None
    if receipt.stock_id:
        stock_res = await db.execute(
            select(FuelStock).options(selectinload(FuelStock.facility)).where(FuelStock.id == receipt.stock_id)
        )
        stock = stock_res.scalars().first()
        if stock and stock.facility:
            fac_name = stock.facility.name
    if not fac_name and receipt.facility_id:
        fac = await db.get(Facility, receipt.facility_id)
        if fac:
            fac_name = fac.name

    return FuelReceiptOut(
        id=receipt.id,
        facility_id=receipt.facility_id,
        facility_name=fac_name,
        stock_id=receipt.stock_id,
        stock_name=stock.name if stock else "Склад ГСМ",
        user_id=receipt.user_id,
        user_name=current_user.full_name,
        fuel_type=receipt.fuel_type,
        liters=receipt.liters,
        cost_total=receipt.cost_total,
        price_per_liter=receipt.price_per_liter,
        driver_name=receipt.driver_name,
        receipt_number=receipt.receipt_number,
        comment=receipt.comment,
        created_at=receipt.created_at
    )


@router.get("/receipts", response_model=List[FuelReceiptOut])
async def list_receipts(
    facility_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(FuelReceipt).options(
        selectinload(FuelReceipt.user),
        selectinload(FuelReceipt.stock).selectinload(FuelStock.facility)
    ).order_by(FuelReceipt.id.desc()).limit(limit)

    if facility_id:
        q = q.outerjoin(FuelStock, FuelReceipt.stock_id == FuelStock.id).where(
            or_(FuelReceipt.facility_id == facility_id, FuelStock.facility_id == facility_id)
        )

    res = await db.execute(q)
    receipts = res.scalars().all()
    return [
        FuelReceiptOut(
            id=r.id,
            facility_id=r.facility_id or (r.stock.facility_id if r.stock else None),
            facility_name=r.stock.facility.name if r.stock and r.stock.facility else None,
            stock_id=r.stock_id,
            stock_name=r.stock.name if r.stock else "Склад ГСМ",
            user_id=r.user_id,
            user_name=r.user.full_name if r.user else None,
            fuel_type=r.fuel_type,
            liters=r.liters,
            cost_total=r.cost_total,
            price_per_liter=r.price_per_liter,
            driver_name=r.driver_name,
            receipt_number=r.receipt_number,
            comment=r.comment,
            created_at=r.created_at
        )
        for r in receipts
    ]


@router.post("/transfer", response_model=FuelTransferOut, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    data: FuelTransferCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:transfer"))
):
    transfer = await transfer_fuel_to_tank(
        db=db,
        transfer_data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    stock = None
    fac_name = None
    if transfer.stock_id:
        stock_res = await db.execute(
            select(FuelStock).options(selectinload(FuelStock.facility)).where(FuelStock.id == transfer.stock_id)
        )
        stock = stock_res.scalars().first()
        if stock and stock.facility:
            fac_name = stock.facility.name
    if not fac_name and transfer.facility_id:
        fac = await db.get(Facility, transfer.facility_id)
        if fac:
            fac_name = fac.name

    gen = await db.get(Generator, transfer.generator_id) if transfer.generator_id else None

    return FuelTransferOut(
        id=transfer.id,
        facility_id=transfer.facility_id,
        facility_name=fac_name,
        stock_id=transfer.stock_id,
        stock_name=stock.name if stock else "Склад ГСМ",
        generator_id=transfer.generator_id,
        generator_name=gen.name if gen else "Генератор",
        user_id=transfer.user_id,
        user_name=current_user.full_name,
        liters=transfer.liters,
        source_balance_before=transfer.source_balance_before,
        source_balance_after=transfer.source_balance_after,
        tank_balance_before=transfer.tank_balance_before,
        tank_balance_after=transfer.tank_balance_after,
        comment=transfer.comment,
        created_at=transfer.created_at
    )


@router.get("/transfers", response_model=List[FuelTransferOut])
async def list_transfers(
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(FuelTransfer).options(
        selectinload(FuelTransfer.user),
        selectinload(FuelTransfer.stock).selectinload(FuelStock.facility),
        selectinload(FuelTransfer.generator)
    ).order_by(FuelTransfer.id.desc()).limit(limit)

    if generator_id:
        q = q.where(FuelTransfer.generator_id == generator_id)
    elif facility_id:
        q = q.where(FuelTransfer.facility_id == facility_id)

    res = await db.execute(q)
    transfers = res.scalars().all()
    return [
        FuelTransferOut(
            id=t.id,
            facility_id=t.facility_id,
            facility_name=t.stock.facility.name if t.stock and t.stock.facility else None,
            stock_id=t.stock_id,
            stock_name=t.stock.name if t.stock else "Склад ГСМ",
            generator_id=t.generator_id,
            generator_name=t.generator.name if t.generator else "Генератор",
            user_id=t.user_id,
            user_name=t.user.full_name if t.user else None,
            liters=t.liters,
            source_balance_before=t.source_balance_before,
            source_balance_after=t.source_balance_after,
            tank_balance_before=t.tank_balance_before,
            tank_balance_after=t.tank_balance_after,
            comment=t.comment,
            created_at=t.created_at
        )
        for t in transfers
    ]
