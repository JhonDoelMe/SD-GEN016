from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.schemas.fuel import (
    FuelStockOut, FuelReceiptCreate, FuelReceiptOut,
    FuelTransferCreate, FuelTransferOut, FuelBalancesSummary
)
from backend.app.api.deps import get_current_user, require_permission, get_client_ip
from backend.app.services.fuel_service import (
    get_or_create_default_stock, add_fuel_receipt,
    transfer_fuel_to_tank, get_fuel_balances_summary
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


@router.get("/stock", response_model=FuelStockOut)
async def get_stock(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stock = await get_or_create_default_stock(db, facility_id=facility_id)
    return stock


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
    return FuelReceiptOut(
        id=receipt.id,
        stock_id=receipt.stock_id,
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
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(FuelReceipt).order_by(FuelReceipt.id.desc()).limit(limit)
    )
    receipts = res.scalars().all()
    return [
        FuelReceiptOut(
            id=r.id,
            stock_id=r.stock_id,
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
    return FuelTransferOut(
        id=transfer.id,
        stock_id=transfer.stock_id,
        generator_id=transfer.generator_id,
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
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(FuelTransfer).order_by(FuelTransfer.id.desc()).limit(limit)
    )
    transfers = res.scalars().all()
    return [
        FuelTransferOut(
            id=t.id,
            stock_id=t.stock_id,
            generator_id=t.generator_id,
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
