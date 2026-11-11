from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.canister import CanisterTransaction
from backend.app.models.generator import Generator
from backend.app.models.facility import Facility
from backend.app.schemas.fuel import (
    FuelStockCreate, FuelStockUpdate, FuelStockOut, FuelReceiptCreate, FuelReceiptOut,
    FuelTransferCreate, FuelTransferOut, FuelBalancesSummary,
    CanisterPoolCreate, CanisterPoolUpdate, CanisterPoolOut,
    CanisterDispatchRequest, CanisterReceiveRequest, CanisterReturnEmptyRequest,
    CanisterTransactionOut,
)
from backend.app.api.deps import (
    get_current_user,
    require_permission,
    get_client_ip,
    is_user_admin_or_super,
    verify_facility_access,
    verify_generator_facility_access,
)
from backend.app.services.fuel_service import (
    get_or_create_default_stock, list_fuel_stocks, create_fuel_stock,
    update_fuel_stock, delete_fuel_stock,
    add_fuel_receipt, transfer_fuel_to_tank, get_fuel_balances_summary
)
from backend.app.services.canister_service import (
    get_stock_canister_aggregates,
    list_canister_pools,
    create_canister_pool,
    update_canister_pool,
    delete_canister_pool,
    dispatch_canisters,
    return_empty_canisters,
    receive_canisters,
    list_canister_transactions,
    to_pool_out,
)

router = APIRouter(prefix="/fuel", tags=["Паливо"])


def _build_stock_out(stock: FuelStock, agg_map: dict) -> FuelStockOut:
    info = agg_map.get(int(stock.id), {})
    return FuelStockOut(
        id=stock.id,
        facility_id=stock.facility_id,
        facility_name=stock.facility.name if stock.facility else None,
        name=stock.name,
        fuel_type=stock.fuel_type,
        current_balance_l=float(stock.current_balance_l),
        is_active=stock.is_active,
        updated_at=stock.updated_at,
        has_canister_pools=bool(info.get("has_canister_pools", False)),
        canisters_total=int(info.get("canisters_total", 0)),
        canisters_full=int(info.get("canisters_full", 0)),
        canisters_empty=int(info.get("canisters_empty", 0)),
        canisters_away=int(info.get("canisters_away", 0)),
        canister_reserve_l=float(info.get("canister_reserve_l", 0.0)),
    )


@router.get("/summary", response_model=FuelBalancesSummary)
async def fuel_summary(
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view"))
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    await verify_generator_facility_access(db, current_user, generator_id)
    return await get_fuel_balances_summary(db, facility_id=eff_facility_id, generator_id=generator_id)


@router.get("/stocks", response_model=List[FuelStockOut])
async def get_stocks_list(
    facility_id: Optional[int] = None,
    include_archived: bool = Query(False, description="Включити архівовані склади"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view"))
):
    """Список усіх складів ГСМ (за об'єктом або загальний)"""
    eff_facility_id = verify_facility_access(current_user, facility_id)
    stocks = await list_fuel_stocks(db, facility_id=eff_facility_id, include_archived=include_archived)
    agg_map = await get_stock_canister_aggregates(db, [s.id for s in stocks])
    return [_build_stock_out(s, agg_map) for s in stocks]


@router.post("/stocks", response_model=FuelStockOut, status_code=status.HTTP_201_CREATED)
@router.post("/stock/new", response_model=FuelStockOut, status_code=status.HTTP_201_CREATED)
async def create_stock_api(
    data: FuelStockCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure"))
):
    """Створити новий склад ГСМ для обраного об'єкта"""
    verify_facility_access(current_user, data.facility_id)
    client_ip = get_client_ip(request)
    stock = await create_fuel_stock(db, data, current_user.id, client_ip)
    return _build_stock_out(stock, {})


@router.put("/stocks/{stock_id}", response_model=FuelStockOut)
async def update_stock_api(
    stock_id: int,
    data: FuelStockUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure"))
):
    """Редагувати склад ГСМ (назву, тип палива, об'єкт, статус активності)"""
    existing = await db.get(FuelStock, stock_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    if data.facility_id is not None:
        verify_facility_access(current_user, data.facility_id)
    client_ip = get_client_ip(request)
    stock = await update_fuel_stock(db, stock_id, data, current_user.id, client_ip)
    agg_map = await get_stock_canister_aggregates(db, [stock.id])
    return _build_stock_out(stock, agg_map)


@router.delete("/stocks/{stock_id}")
async def delete_stock_api(
    stock_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure"))
):
    """Видалити або перевести в архів склад ГСМ (збереження історії)"""
    existing = await db.get(FuelStock, stock_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    client_ip = get_client_ip(request)
    return await delete_fuel_stock(db, stock_id, current_user.id, client_ip)


@router.get("/stock", response_model=FuelStockOut)
async def get_stock(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view"))
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    stock = await get_or_create_default_stock(db, facility_id=eff_facility_id)
    agg_map = await get_stock_canister_aggregates(db, [stock.id])
    return _build_stock_out(stock, agg_map)


@router.post("/receipt", response_model=FuelReceiptOut, status_code=status.HTTP_201_CREATED)
async def create_receipt(
    data: FuelReceiptCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:receipt"))
):
    if data.facility_id is not None:
        verify_facility_access(current_user, data.facility_id)
    elif current_user.facility_id:
        data.facility_id = current_user.facility_id
    elif not data.stock_id:
        data.facility_id = 1

    if data.stock_id:
        st = await db.get(FuelStock, data.stock_id)
        if not st:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")
        verify_facility_access(current_user, st.facility_id)

    user_perms = [perm.code for role in (current_user.roles or []) for perm in (role.permissions or [])]
    is_admin = is_user_admin_or_super(current_user)

    receipt = await add_fuel_receipt(
        db=db,
        receipt_data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        user_permissions=user_perms,
        is_admin=is_admin
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
        fuel_provider=getattr(receipt, "fuel_provider", "wog") or "wog",
        fuel_type=receipt.fuel_type,
        liters=float(receipt.liters),
        cost_total=float(receipt.cost_total),
        price_per_liter=float(receipt.price_per_liter),
        driver_name=receipt.driver_name,
        receipt_number=receipt.receipt_number,
        comment=receipt.comment,
        idempotency_key=receipt.idempotency_key,
        created_at=receipt.created_at
    )


@router.get("/receipts", response_model=List[FuelReceiptOut])
async def list_receipts(
    facility_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view"))
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    q = select(FuelReceipt).options(
        selectinload(FuelReceipt.user),
        selectinload(FuelReceipt.stock).selectinload(FuelStock.facility)
    ).order_by(FuelReceipt.id.desc()).limit(limit)

    if eff_facility_id:
        q = q.outerjoin(FuelStock, FuelReceipt.stock_id == FuelStock.id).where(
            or_(FuelReceipt.facility_id == eff_facility_id, FuelStock.facility_id == eff_facility_id)
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
            user_name=(r.user.full_name or r.user.login) if r.user else None,
            fuel_provider=getattr(r, "fuel_provider", "wog") or "wog",
            fuel_type=r.fuel_type,
            liters=float(r.liters),
            cost_total=float(r.cost_total),
            price_per_liter=float(r.price_per_liter),
            driver_name=r.driver_name,
            receipt_number=r.receipt_number,
            comment=r.comment,
            idempotency_key=r.idempotency_key,
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
    if data.facility_id is not None:
        verify_facility_access(current_user, data.facility_id)
    elif current_user.facility_id:
        data.facility_id = current_user.facility_id
    elif not data.stock_id:
        data.facility_id = 1

    if data.generator_id is not None:
        await verify_generator_facility_access(db, current_user, data.generator_id)

    if data.stock_id is not None:
        st = await db.get(FuelStock, data.stock_id)
        if not st:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")
        verify_facility_access(current_user, st.facility_id)

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
        liters=float(transfer.liters),
        source_balance_before=float(transfer.source_balance_before),
        source_balance_after=float(transfer.source_balance_after),
        tank_balance_before=float(transfer.tank_balance_before),
        tank_balance_after=float(transfer.tank_balance_after),
        used_from_reserve_l=getattr(transfer, "_used_from_reserve_l", None),
        opened_canisters_count=getattr(transfer, "_opened_canisters_count", None),
        canister_reserve_after_l=getattr(transfer, "_canister_reserve_after_l", None),
        comment=transfer.comment,
        idempotency_key=transfer.idempotency_key,
        created_at=transfer.created_at
    )


@router.get("/transfers", response_model=List[FuelTransferOut])
async def list_transfers(
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    await verify_generator_facility_access(db, current_user, generator_id)

    q = select(FuelTransfer).options(
        selectinload(FuelTransfer.user),
        selectinload(FuelTransfer.stock).selectinload(FuelStock.facility),
        selectinload(FuelTransfer.generator)
    ).order_by(FuelTransfer.id.desc()).limit(limit)

    if generator_id:
        q = q.where(FuelTransfer.generator_id == generator_id)
    elif eff_facility_id:
        q = q.where(FuelTransfer.facility_id == eff_facility_id)

    res = await db.execute(q)
    transfers = res.scalars().all()

    ctx_by_transfer = {}
    t_ids = [t.id for t in transfers]
    if t_ids:
        ctx_res = await db.execute(
            select(CanisterTransaction).where(CanisterTransaction.related_transfer_id.in_(t_ids))
        )
        for ctx in ctx_res.scalars().all():
            if ctx.related_transfer_id is not None:
                ctx_by_transfer[int(ctx.related_transfer_id)] = ctx

    out = []
    for t in transfers:
        ctx = ctx_by_transfer.get(int(t.id))
        out.append(
            FuelTransferOut(
                id=t.id,
                facility_id=t.facility_id,
                facility_name=t.stock.facility.name if t.stock and t.stock.facility else None,
                stock_id=t.stock_id,
                stock_name=t.stock.name if t.stock else "Склад ГСМ",
                generator_id=t.generator_id,
                generator_name=t.generator.name if t.generator else "Генератор",
                user_id=t.user_id,
                user_name=(t.user.full_name or t.user.login) if t.user else None,
                liters=float(t.liters),
                source_balance_before=float(t.source_balance_before),
                source_balance_after=float(t.source_balance_after),
                tank_balance_before=float(t.tank_balance_before),
                tank_balance_after=float(t.tank_balance_after),
                used_from_reserve_l=float(ctx.used_from_reserve_l) if ctx else None,
                opened_canisters_count=int(ctx.count) if ctx else None,
                canister_reserve_after_l=float(ctx.reserve_after) if ctx else None,
                comment=t.comment,
                idempotency_key=t.idempotency_key,
                created_at=t.created_at
            )
        )
    return out


# ---------------------------------------------------------------------------
# Canister Pools & Reserve Buffer API (Stage 2)
# ---------------------------------------------------------------------------

@router.get("/canisters", response_model=List[CanisterPoolOut])
async def get_canisters_list(
    facility_id: Optional[int] = None,
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view")),
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    pools = await list_canister_pools(db, facility_id=eff_facility_id, include_inactive=include_inactive)
    return [to_pool_out(p) for p in pools]


@router.post("/canisters", response_model=CanisterPoolOut, status_code=status.HTTP_201_CREATED)
async def create_canister_pool_api(
    data: CanisterPoolCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure")),
):
    verify_facility_access(current_user, data.facility_id)
    pool = await create_canister_pool(db, data, current_user.id, get_client_ip(request))
    return to_pool_out(pool)


@router.put("/canisters/{pool_id}", response_model=CanisterPoolOut)
async def update_canister_pool_api(
    pool_id: int,
    data: CanisterPoolUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure")),
):
    from backend.app.models.canister import CanisterPool
    existing = await db.get(CanisterPool, pool_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    pool = await update_canister_pool(db, pool_id, data, current_user.id, get_client_ip(request))
    return to_pool_out(pool)


@router.delete("/canisters/{pool_id}")
async def delete_canister_pool_api(
    pool_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:configure")),
):
    from backend.app.models.canister import CanisterPool
    existing = await db.get(CanisterPool, pool_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    return await delete_canister_pool(db, pool_id, current_user.id, get_client_ip(request))


@router.post("/canisters/{pool_id}/dispatch", response_model=CanisterPoolOut)
async def dispatch_canisters_api(
    pool_id: int,
    data: CanisterDispatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:transfer")),
):
    from backend.app.models.canister import CanisterPool
    existing = await db.get(CanisterPool, pool_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    pool = await dispatch_canisters(db, pool_id, data, current_user.id, get_client_ip(request))
    return to_pool_out(pool)


@router.post("/canisters/{pool_id}/return-empty", response_model=CanisterPoolOut)
async def return_empty_canisters_api(
    pool_id: int,
    data: CanisterReturnEmptyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:transfer")),
):
    from backend.app.models.canister import CanisterPool
    existing = await db.get(CanisterPool, pool_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    pool = await return_empty_canisters(db, pool_id, data, current_user.id, get_client_ip(request))
    return to_pool_out(pool)


@router.post("/canisters/{pool_id}/receive", response_model=CanisterPoolOut)
async def receive_canisters_api(
    pool_id: int,
    data: CanisterReceiveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:receipt")),
):
    from backend.app.models.canister import CanisterPool
    existing = await db.get(CanisterPool, pool_id)
    if existing:
        verify_facility_access(current_user, existing.facility_id)
    user_perms = [perm.code for role in (current_user.roles or []) for perm in (role.permissions or [])]
    is_admin = is_user_admin_or_super(current_user)
    pool = await receive_canisters(
        db, pool_id, data, current_user.id, get_client_ip(request),
        user_permissions=user_perms, is_admin=is_admin,
    )
    return to_pool_out(pool)


@router.get("/canisters/transactions", response_model=List[CanisterTransactionOut])
async def list_canister_transactions_api(
    facility_id: Optional[int] = None,
    pool_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("fuel:view")),
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    txs = await list_canister_transactions(db, facility_id=eff_facility_id, pool_id=pool_id, limit=limit)
    return [
        CanisterTransactionOut(
            id=tx.id,
            facility_id=tx.facility_id,
            pool_id=tx.pool_id,
            pool_name=tx.pool.name if tx.pool else None,
            user_id=tx.user_id,
            user_name=(tx.user.full_name or tx.user.login) if tx.user else None,
            operation=tx.operation,
            count=int(tx.count),
            liters_delta=float(tx.liters_delta),
            used_from_reserve_l=float(tx.used_from_reserve_l),
            full_before=int(tx.full_before),
            full_after=int(tx.full_after),
            empty_before=int(tx.empty_before),
            empty_after=int(tx.empty_after),
            away_before=int(tx.away_before),
            away_after=int(tx.away_after),
            reserve_before=float(tx.reserve_before),
            reserve_after=float(tx.reserve_after),
            related_transfer_id=tx.related_transfer_id,
            related_receipt_id=tx.related_receipt_id,
            comment=tx.comment,
            created_at=tx.created_at,
        )
        for tx in txs
    ]
