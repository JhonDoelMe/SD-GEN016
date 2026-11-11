import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy import select, func, or_, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer, utc_now
from backend.app.models.canister import CanisterPool, CanisterTransaction
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.facility import Facility
from backend.app.schemas.fuel import (
    FuelStockCreate, FuelStockUpdate, FuelReceiptCreate, FuelTransferCreate, FuelBalancesSummary
)
from backend.app.services.audit_service import log_audit


def to_decimal(val, places: int = 2) -> Decimal:
    """Конвертує значення в Decimal із заданою кількістю знаків та банківським/арифметичним округленням"""
    if val is None:
        return Decimal("0").quantize(Decimal(f"0.{'0' * places}"))
    if isinstance(val, Decimal):
        d = val
    elif isinstance(val, (int, str)):
        d = Decimal(str(val))
    else:
        # float
        d = Decimal(str(round(val, places + 2)))
    return d.quantize(Decimal(f"0.{'0' * places}"), rounding=ROUND_HALF_UP)


def to_money(val) -> Decimal:
    """Точність для грошових розрахунків: 2 знаки після коми (грн, коп)"""
    return to_decimal(val, 2)


def to_liters(val) -> Decimal:
    """Точність для обліку об'єму пального: 3 знаки після коми (мл)"""
    return to_decimal(val, 3)


def to_float(val, places: int = 2) -> float:
    if val is None:
        return 0.0
    return float(round(float(val), places))


def normalize_fuel_family(fuel_type: Optional[str]) -> str:
    """
    Нормалізує назву або бренд палива до базової родини палив:
    - Бензин 95 / 100: "a95"
    - Дизель / ДП: "dp"
    - Бензин 92: "a92"
    - Газ / LPG / СПБТ: "gas"
    """
    if not fuel_type:
        return ""
    f = fuel_type.strip().lower()
    # Дизель / ДП
    if any(k in f for k in ("дизель", "дп", "dp", "dt", "дт", "diesel")):
        return "dp"
    # Бензин 95 / 100
    if any(k in f for k in ("95", "а-95", "a-95", "100", "pulls", "mustang", "бензин")):
        return "a95"
    # Бензин 92
    if any(k in f for k in ("92", "а-92", "a-92")):
        return "a92"
    # Газ
    if any(k in f for k in ("газ", "lpg", "спбт", "gas", "автогаз")):
        return "gas"
    return f


async def get_or_create_default_stock(db: AsyncSession, facility_id: Optional[int] = None) -> FuelStock:
    """
    FUEL-01: Отримати або створити стандартний склад ГСМ для вказаного об'єкта.
    Суворо ізольовано:
    - Заборонено повертати склад іншого об'єкта.
    - Заборонено неявний fallback на facility_id=1.
    - Перевіряється існування об'єкта перед створенням складу.
    """
    if facility_id is not None:
        fac = await db.get(Facility, facility_id)
        if not fac:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Об'єкт з ID {facility_id} не знайдено"
            )

        # Пошук активного складу суворо в межах цього об'єкта
        query = (
            select(FuelStock)
            .options(selectinload(FuelStock.facility))
            .where(FuelStock.facility_id == facility_id, FuelStock.is_active == True)
            .order_by(FuelStock.id.asc())
        )
        res = await db.execute(query)
        stock = res.scalars().first()

        if not stock:
            # Створюємо стандартний склад виключно для цього об'єкта
            stock = FuelStock(
                facility_id=facility_id,
                name="Основний склад ГСМ",
                fuel_type="А-95",
                current_balance_l=Decimal("0.000"),
                is_active=True
            )
            db.add(stock)
            try:
                await db.flush()
            except Exception:
                await db.rollback()
                # Захист від race condition при паралельному створенні
                res_retry = await db.execute(query)
                stock = res_retry.scalars().first()
                if not stock:
                    raise
            else:
                await db.commit()
                res_fetch = await db.execute(
                    select(FuelStock).options(selectinload(FuelStock.facility)).where(FuelStock.id == stock.id)
                )
                stock = res_fetch.scalars().first()
        return stock
    else:
        # facility_id is None: адміністративний глобальний контекст
        res_any = await db.execute(
            select(FuelStock)
            .options(selectinload(FuelStock.facility))
            .where(FuelStock.is_active == True)
            .order_by(FuelStock.id.asc())
        )
        stock = res_any.scalars().first()
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У системі відсутні активні склади ГСМ. Вкажіть facility_id для створення складу."
            )
        return stock


async def list_fuel_stocks(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    include_archived: bool = False
) -> List[FuelStock]:
    """Список складів ГСМ із фільтрацією за об'єктом та архівацією"""
    query = select(FuelStock).options(selectinload(FuelStock.facility))
    if not include_archived:
        query = query.where(FuelStock.is_active == True)

    if facility_id is not None:
        fac = await db.get(Facility, facility_id)
        if not fac:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Об'єкт з ID {facility_id} не знайдено"
            )
        query = query.where(FuelStock.facility_id == facility_id)

    res = await db.execute(query.order_by(FuelStock.id.asc()))
    stocks = res.scalars().all()

    if not stocks and facility_id is not None:
        # Забезпечуємо хоча б один активний склад для об'єкта
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Об'єкт з ID {data.facility_id} не знайдено")

    initial_bal = to_liters(data.initial_balance_l)
    stock = FuelStock(
        facility_id=data.facility_id,
        name=data.name.strip(),
        fuel_type=data.fuel_type.strip(),
        current_balance_l=initial_bal,
        is_active=True
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
            "initial_balance_l": float(stock.current_balance_l)
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
    """Оновити параметри складу ГСМ (назву, тип палива, об'єкт, статус активності)"""
    stock = await db.get(FuelStock, stock_id)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")

    old_details = {
        "name": stock.name,
        "fuel_type": stock.fuel_type,
        "facility_id": stock.facility_id,
        "is_active": stock.is_active
    }

    if data.name is not None and data.name.strip():
        stock.name = data.name.strip()

    if data.fuel_type is not None and data.fuel_type.strip():
        # Перевірка: якщо є залишок, змінювати базову родину пального заборонено без обнулення
        if to_liters(stock.current_balance_l) > Decimal("0.000") and normalize_fuel_family(data.fuel_type) != normalize_fuel_family(stock.fuel_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неможливо змінити тип палива складу з '{stock.fuel_type}' на '{data.fuel_type.strip()}', оскільки на складі є залишок {float(stock.current_balance_l):.1f} л."
            )
        stock.fuel_type = data.fuel_type.strip()
        await db.execute(
            update(CanisterPool)
            .where(CanisterPool.stock_id == stock.id)
            .values(fuel_type=stock.fuel_type)
        )

    if data.facility_id is not None and data.facility_id != stock.facility_id:
        fac = await db.get(Facility, data.facility_id)
        if not fac:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Цільовий об'єкт не знайдено")
        # Забороняємо переносити склад з історією або залишком на інший об'єкт
        if to_liters(stock.current_balance_l) > Decimal("0.000"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неможливо змінити об'єкт складу з ненульовим залишком. Перенесіть залишок або створіть новий склад."
            )
        stock.facility_id = data.facility_id

    if data.is_active is not None:
        if not data.is_active:
            # Деактивація (архівація) вимагає перевірки залишку
            if to_liters(stock.current_balance_l) > Decimal("0.000"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Неможливо архівувати склад із залишком {float(stock.current_balance_l):.1f} л."
                )
            active_count = await db.scalar(
                select(func.count(FuelStock.id)).where(
                    FuelStock.facility_id == stock.facility_id,
                    FuelStock.is_active == True,
                    FuelStock.id != stock_id
                )
            )
            if (active_count or 0) < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неможливо архівувати єдиний активний склад на цьому об'єкті."
                )
        stock.is_active = data.is_active

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
                "facility_id": stock.facility_id,
                "is_active": stock.is_active
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
    """
    FUEL-03: Безпечне видалення та архівація складу ГСМ.
    - Перевіряє наявність альтернативного активного складу на об'єкті.
    - Якщо склад має залишок — безпечно переносить його на альтернативний склад.
    - Якщо склад має історичні чеки/переміщення — виконується м'яка архівація (is_active=False).
    - Історичні записи НЕ переприв'язуються на інший склад і суворо зберігають автентичний stock_id!
    - Якщо склад порожній і без історії — виконується фізичне видалення.
    """
    stock = await db.get(FuelStock, stock_id)
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")

    # Знаходимо альтернативний активний склад цього ж об'єкта
    alt_stock = await db.scalar(
        select(FuelStock).where(
            FuelStock.facility_id == stock.facility_id,
            FuelStock.is_active == True,
            FuelStock.id != stock_id
        ).order_by(FuelStock.id.asc())
    )

    if not alt_stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо видалити єдиний склад ГСМ на цьому об'єкті. Створіть інший склад перед видаленням."
        )

    stock_name = stock.name
    fac_id = stock.facility_id

    from backend.app.services.measurement_service import ensure_facility_not_locked_by_measurement
    await ensure_facility_not_locked_by_measurement(db, fac_id, "fuel_adjustment")
    stock_balance = to_liters(stock.current_balance_l)

    active_pools_count = await db.scalar(
        select(func.count(CanisterPool.id)).where(
            CanisterPool.stock_id == stock_id,
            CanisterPool.is_active == True,  # noqa: E712
        )
    )
    if (active_pools_count or 0) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Спочатку видаліть або перенесіть активні пули каністр, прив'язані до цього складу ГСМ."
        )

    # Перевіряємо наявність історичних операцій
    receipts_count = await db.scalar(
        select(func.count(FuelReceipt.id)).where(FuelReceipt.stock_id == stock_id)
    )
    transfers_count = await db.scalar(
        select(func.count(FuelTransfer.id)).where(FuelTransfer.stock_id == stock_id)
    )
    has_history = ((receipts_count or 0) > 0) or ((transfers_count or 0) > 0)

    # Якщо на складі був залишок — переносимо його на альтернативний склад об'єкта
    if stock_balance > Decimal("0.000"):
        alt_stock.current_balance_l = to_liters(alt_stock.current_balance_l) + stock_balance
        alt_stock.updated_at = utc_now()
        stock.current_balance_l = Decimal("0.000")

    if has_history:
        # М'яка архівація — суворо зберігаємо історію без зміни зовнішніх ключів
        stock.is_active = False
        stock.updated_at = utc_now()
        await db.flush()

        await log_audit(
            db=db,
            action="FUEL_STOCK_DELETED",
            entity_type="FuelStock",
            entity_id=str(stock_id),
            user_id=user_id,
            details={
                "deleted_stock_name": stock_name,
                "transferred_balance_l": float(stock_balance),
                "target_stock_id": alt_stock.id,
                "target_stock_name": alt_stock.name,
                "receipts_count": receipts_count,
                "transfers_count": transfers_count,
                "archived": True
            },
            ip_address=ip_address
        )
    else:
        # Порожній склад без історії видаляється фізично
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
                "transferred_balance_l": float(stock_balance),
                "target_stock_id": alt_stock.id,
                "target_stock_name": alt_stock.name,
                "archived": False
            },
            ip_address=ip_address
        )

    await db.commit()

    detail_msg = f"Склад '{stock_name}' успішно видалено"
    if stock_balance > Decimal("0.000"):
        detail_msg += f". Залишок {float(stock_balance):.1f} л перенесено на склад '{alt_stock.name}'"

    return {
        "ok": True,
        "detail": detail_msg
    }


async def add_fuel_receipt(
    db: AsyncSession,
    receipt_data: FuelReceiptCreate,
    user_id: int,
    ip_address: Optional[str] = None,
    user_permissions: Optional[List[str]] = None,
    is_admin: bool = False,
    _skip_canister_sync: bool = False,
    _auto_commit: bool = True,
) -> FuelReceipt:
    """
    FUEL-02, FUEL-04, FUEL-05, FUEL-06, FUEL-07, FUEL-08:
    Оприбуткування палива з транзакційним блокуванням, перевіркою відповідності об'єкта,
    контролем типу палива, перевіркою дозволу force_confirm та точною арифметикою Decimal.
    """
    # Захист від повторного виконання (Idempotency)
    if receipt_data.idempotency_key:
        existing_receipt = (await db.execute(
            select(FuelReceipt).where(FuelReceipt.idempotency_key == receipt_data.idempotency_key)
        )).scalars().first()
        if existing_receipt:
            return existing_receipt

    # Отримуємо склад із блокуванням рядка для запобігання гонкам
    if receipt_data.stock_id:
        res_stock = await db.execute(
            select(FuelStock).where(FuelStock.id == receipt_data.stock_id).with_for_update()
        )
        stock = res_stock.scalars().first()
        if not stock:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")
    else:
        target_facility_id = receipt_data.facility_id or 1
        stock_init = await get_or_create_default_stock(db, facility_id=target_facility_id)
        res_stock = await db.execute(
            select(FuelStock).where(FuelStock.id == stock_init.id).with_for_update()
        )
        stock = res_stock.scalars().first()

    # Перевірка активності складу
    if not stock.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Склад '{stock.name}' архівовано. Оприбуткування палива на архівований склад заборонено."
        )

    # FUEL-04: Сувора валідація facility_id
    effective_facility_id = stock.facility_id
    if receipt_data.facility_id is not None and int(receipt_data.facility_id) != int(effective_facility_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невідповідність об'єкта: переданий facility_id ({receipt_data.facility_id}) не збігається з об'єктом складу ({effective_facility_id})."
        )

    from backend.app.services.measurement_service import ensure_facility_not_locked_by_measurement
    await ensure_facility_not_locked_by_measurement(db, effective_facility_id, "fuel_receipt")

    # Валідація кількості літрів
    liters = to_liters(receipt_data.liters)
    if liters <= Decimal("0.000"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість літрів має бути більше 0")

    # FUEL-07: Контроль типу пального
    effective_fuel_type = (receipt_data.fuel_type or stock.fuel_type or "А-95").strip()
    stock_current_bal = to_liters(stock.current_balance_l)
    rec_family = normalize_fuel_family(receipt_data.fuel_type)
    stock_family = normalize_fuel_family(stock.fuel_type)

    if stock_current_bal == Decimal("0.000"):
        # Якщо склад порожній (початковий стан), він може прийняти новий тип пального
        if not stock.fuel_type or (rec_family and rec_family != stock_family):
            stock.fuel_type = effective_fuel_type
    elif rec_family and stock_family and rec_family != stock_family:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невідповідність типу палива: чек містить '{receipt_data.fuel_type}', а склад '{stock.name}' містить залишок типу '{stock.fuel_type}'."
        )

    # FUEL-06: Визначення постачальника за ієрархією
    receipt_provider = (receipt_data.fuel_provider or "").strip().lower()
    if not receipt_provider:
        fac = await db.get(Facility, effective_facility_id)
        if fac and getattr(fac, "default_fuel_provider", None):
            receipt_provider = fac.default_fuel_provider.strip().lower()
        else:
            from backend.app.services.settings_service import get_runtime_setting
            receipt_provider = str(get_runtime_setting("fuel_default_provider", "wog")).strip().lower()
    if receipt_provider not in ("wog", "okko"):
        receipt_provider = "wog"

    # FUEL-08: Розрахунок вартості через точну арифметику Decimal
    price_source = "manual_total"
    if receipt_data.cost_total is not None and receipt_data.cost_total > 0:
        cost_total = to_money(receipt_data.cost_total)
        price_per_l = (cost_total / liters).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        price_source = "manual_total"
    elif receipt_data.price_per_liter is not None and receipt_data.price_per_liter > 0:
        price_per_l = to_money(receipt_data.price_per_liter)
        cost_total = (liters * price_per_l).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        price_source = "manual_unit_price"
    else:
        from backend.app.services.settings_service import resolve_fuel_price_per_liter
        price_resolved, price_source = await resolve_fuel_price_per_liter(
            db, effective_fuel_type, provider=receipt_provider
        )
        price_per_l = to_money(price_resolved)
        cost_total = (liters * price_per_l).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # FUEL-05: Запобіжники значного об'єму та аномальної ціни
    from backend.app.services.settings_service import get_runtime_setting
    max_liters_warn = to_liters(get_runtime_setting("fuel_receipt_max_liters_warning", 1000.0))
    min_price_warn = to_money(get_runtime_setting("fuel_receipt_min_price", 15.0))
    max_price_warn = to_money(get_runtime_setting("fuel_receipt_max_price", 250.0))

    is_volume_breach = liters > max_liters_warn
    is_price_breach = price_per_l < min_price_warn or price_per_l > max_price_warn
    is_safeguard_triggered = is_volume_breach or is_price_breach

    if is_safeguard_triggered:
        if not receipt_data.force_confirm:
            if is_volume_breach:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Запобіжник об'єму палива: вказано значний об'єм ({float(liters):.1f} л > {float(max_liters_warn):.0f} л). "
                        f"Перевірте введені дані (можлива опечатка) або підтвердіть дію."
                    )
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Запобіжник вартості палива: розрахункова ціна ({float(price_per_l):.2f} грн/л) виходить за межі "
                        f"очікуваного діапазону ({float(min_price_warn):.0f} - {float(max_price_warn):.0f} грн/л). "
                        f"Перевірте суму чека або підтвердіть дію."
                    )
                )
        else:
            # force_confirm передано: сувора серверна перевірка дозволу
            has_override_permission = is_admin or (
                user_permissions is not None and "fuel:receipt:override" in user_permissions
            )
            if not has_override_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Для підтвердження нетипового об'єму або ціни палива (force_confirm) потрібен дозвіл 'fuel:receipt:override'."
                )

    comment_text = receipt_data.comment
    if price_source in ("system_settings", "internet", "internet_okko"):
        if price_source == "system_settings":
            src_ua = "Налаштування системи"
        elif price_source == "internet_okko":
            src_ua = "АЗК OKKO (авторозрахунок)"
        else:
            src_ua = "АЗК WOG (авторозрахунок)"
        auto_note = f"[Авторозрахунок: {float(price_per_l):.2f} грн/л ({src_ua})]"
        comment_text = f"{comment_text} {auto_note}".strip() if comment_text else auto_note

    receipt = FuelReceipt(
        facility_id=effective_facility_id,
        stock_id=stock.id,
        user_id=user_id,
        fuel_provider=receipt_provider,
        fuel_type=effective_fuel_type,
        liters=liters,
        cost_total=cost_total,
        price_per_liter=price_per_l,
        driver_name=receipt_data.driver_name.strip(),
        receipt_number=receipt_data.receipt_number.strip(),
        comment=comment_text,
        idempotency_key=receipt_data.idempotency_key
    )
    db.add(receipt)

    stock_before = to_liters(stock.current_balance_l)
    stock_after = stock_before + liters
    stock.current_balance_l = stock_after
    stock.updated_at = utc_now()

    await db.flush()

    if not _skip_canister_sync:
        from backend.app.services.canister_service import apply_direct_receipt_to_canister_pool
        await apply_direct_receipt_to_canister_pool(
            db=db,
            stock=stock,
            liters=liters,
            user_id=user_id,
            receipt_id=receipt.id,
            canister_pool_id=getattr(receipt_data, "canister_pool_id", None),
        )
        stock_after = to_liters(stock.current_balance_l)

    await log_audit(
        db=db,
        action="FUEL_RECEIPT",
        entity_type="FuelStock",
        entity_id=str(stock.id),
        user_id=user_id,
        details={
            "receipt_id": receipt.id,
            "facility_id": effective_facility_id,
            "stock_id": stock.id,
            "stock_name": stock.name,
            "fuel_provider": receipt_provider,
            "liters": float(receipt.liters),
            "cost_total": float(receipt.cost_total),
            "price_per_l": float(price_per_l),
            "price_source": price_source,
            "stock_before": float(stock_before),
            "stock_after": float(stock_after),
            "receipt_no": receipt.receipt_number,
            "driver": receipt.driver_name,
            "is_override": bool(receipt_data.force_confirm),
            "idempotency_key": receipt_data.idempotency_key
        },
        ip_address=ip_address
    )
    if _auto_commit:
        await db.commit()
    return receipt


async def transfer_fuel_to_tank(
    db: AsyncSession,
    transfer_data: FuelTransferCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FuelTransfer:
    """
    FUEL-02, FUEL-04, FUEL-07, FUEL-08:
    Заправка бака генератора зі складу з транзакційними блокуваннями для виключення race condition,
    контролем належності до об'єкта, сумісності типу палива та захистом від переливу/від'ємного залишку.
    """
    # Захист від повторного виконання запиту
    if transfer_data.idempotency_key:
        existing_tr = (await db.execute(
            select(FuelTransfer).where(FuelTransfer.idempotency_key == transfer_data.idempotency_key)
        )).scalars().first()
        if existing_tr:
            return existing_tr

    # Послідовне взяття блокувань: спочатку склад, потім генератор
    if transfer_data.stock_id:
        res_st = await db.execute(
            select(FuelStock).where(FuelStock.id == transfer_data.stock_id).with_for_update()
        )
        stock = res_st.scalars().first()
    else:
        if not transfer_data.facility_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Вкажіть stock_id або facility_id")
        stock_init = await get_or_create_default_stock(db, facility_id=transfer_data.facility_id)
        res_st = await db.execute(
            select(FuelStock).where(FuelStock.id == stock_init.id).with_for_update()
        )
        stock = res_st.scalars().first()

    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")
    if not stock.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Склад '{stock.name}' архівовано. Заправка з архівованого складу неможлива."
        )

    # Отримуємо генератор із блокуванням
    if not transfer_data.generator_id:
        # Якщо генератор не вказано, шукаємо генератор цього об'єкта
        gen_q = select(Generator).where(Generator.facility_id == stock.facility_id).order_by(Generator.id.asc()).with_for_update()
        res_gen = await db.execute(gen_q)
        generator = res_gen.scalars().first()
    else:
        res_gen = await db.execute(
            select(Generator).where(Generator.id == transfer_data.generator_id).with_for_update()
        )
        generator = res_gen.scalars().first()

    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    # FUEL-04: Ізоляція об'єктів — генератор і склад повинні належати одному об'єкту
    if generator.facility_id and stock.facility_id and int(generator.facility_id) != int(stock.facility_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Неможливо виконати заправку: генератор '{generator.name}' (об'єкт ID {generator.facility_id}) "
                f"та склад ГСМ '{stock.name}' (об'єкт ID {stock.facility_id}) належать до різних об'єктів."
            )
        )

    if transfer_data.facility_id is not None and int(transfer_data.facility_id) != int(stock.facility_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невідповідність об'єкта: переданий facility_id ({transfer_data.facility_id}) не збігається з об'єктом складу ({stock.facility_id})."
        )

    facility_id = stock.facility_id

    from backend.app.services.measurement_service import (
        ensure_facility_not_locked_by_measurement,
        increment_active_measurement_added_fuel,
    )
    await ensure_facility_not_locked_by_measurement(db, facility_id, "fuel_transfer")

    # FUEL-07: Перевірка сумісності типу пального
    st_family = normalize_fuel_family(stock.fuel_type)
    gen_family = normalize_fuel_family(generator.fuel_type)
    if st_family != gen_family:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Несумісність типів палива: генератор '{generator.name}' потребує '{generator.fuel_type}', "
                f"а на складі '{stock.name}' зберігається '{stock.fuel_type}'."
            )
        )

    liters = to_liters(transfer_data.liters)
    if liters <= Decimal("0.000"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Кількість літрів заправки має бути більше 0")

    # FUEL-02: Перевірка достатності залишку на складі (захист від від'ємного залишку)
    src_before = to_liters(stock.current_balance_l)
    if src_before < liters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недостатньо палива на складі ГСМ! Доступно: {float(src_before):.1f} л, запитано: {float(liters):.1f} л"
        )

    # FUEL-02: Захист від переливу бака генератора
    tank_before = to_liters(generator.fuel_tank_level_l)
    tank_cap = to_liters(generator.tank_capacity_l)
    tank_after = tank_before + liters
    if tank_after > tank_cap:
        max_possible = tank_cap - tank_before
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Перевищення місткості бака! Місткість: {float(tank_cap):.1f} л, поточний рівень: {float(tank_before):.1f} л. "
                f"Можна додати максимум: {float(max_possible):.1f} л"
            )
        )

    src_after = src_before - liters
    stock.current_balance_l = src_after
    stock.updated_at = utc_now()

    generator.fuel_tank_level_l = float(tank_after)
    generator.updated_at = utc_now()

    transfer = FuelTransfer(
        facility_id=facility_id,
        stock_id=stock.id,
        generator_id=generator.id,
        user_id=user_id,
        liters=liters,
        source_balance_before=src_before,
        source_balance_after=src_after,
        tank_balance_before=tank_before,
        tank_balance_after=tank_after,
        comment=transfer_data.comment,
        idempotency_key=transfer_data.idempotency_key
    )
    db.add(transfer)
    await db.flush()

    from backend.app.services.canister_service import consume_from_canister_pool_for_transfer
    canister_breakdown = await consume_from_canister_pool_for_transfer(
        db=db,
        stock=stock,
        liters=liters,
        user_id=user_id,
        transfer_id=transfer.id,
        canister_pool_id=getattr(transfer_data, "canister_pool_id", None),
    )

    await increment_active_measurement_added_fuel(db, generator.id, liters)

    audit_details = {
        "facility_id": facility_id,
        "stock_id": stock.id,
        "generator_id": generator.id,
        "liters": float(transfer.liters),
        "stock_before": float(src_before),
        "stock_after": float(stock.current_balance_l),
        "tank_before": float(tank_before),
        "tank_after": float(tank_after),
        "idempotency_key": transfer_data.idempotency_key,
    }
    if canister_breakdown is not None:
        used_res, opened_cnt, res_after = canister_breakdown
        transfer._used_from_reserve_l = float(used_res)
        transfer._opened_canisters_count = int(opened_cnt)
        transfer._canister_reserve_after_l = float(res_after)
        audit_details.update({
            "used_from_reserve_l": float(used_res),
            "opened_canisters_count": int(opened_cnt),
            "canister_reserve_after_l": float(res_after),
        })
    else:
        transfer._used_from_reserve_l = None
        transfer._opened_canisters_count = None
        transfer._canister_reserve_after_l = None

    await log_audit(
        db=db,
        action="FUEL_TRANSFER_TO_TANK",
        entity_type="FuelTransfer",
        entity_id=str(transfer.id),
        user_id=user_id,
        details=audit_details,
        ip_address=ip_address
    )
    await db.commit()
    return transfer


async def get_fuel_balances_summary(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None
) -> FuelBalancesSummary:
    """
    FUEL-09: Розрахунок зведених залишків пального.
    - Для конкретного об'єкта повертає суму складів цього об'єкта та агрегат усіх його генераторів (без .first()).
    - Для глобального адміністративного запиту підсумовує всі склади та всі генератори системи.
    - Агрегати надходжень, витрат та середньої ціни розраховуються суворо за обраним масштабом.
    """
    if facility_id is not None:
        # 1. Складські залишки конкретного об'єкта (лише активні склади)
        stock_sum_q = select(func.coalesce(func.sum(FuelStock.current_balance_l), 0.0)).where(
            FuelStock.facility_id == facility_id,
            FuelStock.is_active == True
        )
        warehouse_balance = (await db.execute(stock_sum_q)).scalar_one()

        # 2. Залишки баків генераторів об'єкта
        if generator_id:
            gen_q = select(Generator).where(Generator.id == generator_id, Generator.facility_id == facility_id)
            gen = (await db.execute(gen_q)).scalars().first()
            tank_balance = gen.fuel_tank_level_l if gen else 0.0
            tank_capacity = gen.tank_capacity_l if gen else 0.0
        else:
            gen_agg_q = select(
                func.coalesce(func.sum(Generator.fuel_tank_level_l), 0.0),
                func.coalesce(func.sum(Generator.tank_capacity_l), 0.0)
            ).where(Generator.facility_id == facility_id)
            gen_agg = (await db.execute(gen_agg_q)).first()
            tank_balance, tank_capacity = gen_agg if gen_agg else (0.0, 0.0)

        # 3. Агрегат надходжень
        rec_query = select(
            func.coalesce(func.sum(FuelReceipt.liters), 0.0),
            func.coalesce(func.sum(FuelReceipt.cost_total), 0.0)
        ).outerjoin(FuelStock, FuelReceipt.stock_id == FuelStock.id).where(
            or_(FuelReceipt.facility_id == facility_id, FuelStock.facility_id == facility_id)
        )
        total_received_l, total_spent_uah = (await db.execute(rec_query)).first()

        # 4. Агрегат заправок баків
        tr_query = select(func.coalesce(func.sum(FuelTransfer.liters), 0.0))
        if generator_id:
            tr_query = tr_query.where(FuelTransfer.generator_id == generator_id)
        else:
            tr_query = tr_query.where(FuelTransfer.facility_id == facility_id)
        total_transferred_l = (await db.execute(tr_query)).scalar_one()

        # 5. Агрегат розрахункового споживання мотогодинами
        runs_query = select(func.coalesce(func.sum(GeneratorRun.calculated_consumption_l), 0.0)).join(
            Generator, GeneratorRun.generator_id == Generator.id
        )
        if generator_id:
            runs_query = runs_query.where(GeneratorRun.generator_id == generator_id)
        else:
            runs_query = runs_query.where(Generator.facility_id == facility_id)
        total_consumed_l = (await db.execute(runs_query)).scalar_one()

    else:
        # Глобальний звіт: сумуємо всі доступні активи
        stock_sum_q = select(func.coalesce(func.sum(FuelStock.current_balance_l), 0.0)).where(
            FuelStock.is_active == True
        )
        warehouse_balance = (await db.execute(stock_sum_q)).scalar_one()

        if generator_id:
            gen = await db.get(Generator, generator_id)
            tank_balance = gen.fuel_tank_level_l if gen else 0.0
            tank_capacity = gen.tank_capacity_l if gen else 0.0
        else:
            gen_agg_q = select(
                func.coalesce(func.sum(Generator.fuel_tank_level_l), 0.0),
                func.coalesce(func.sum(Generator.tank_capacity_l), 0.0)
            )
            gen_agg = (await db.execute(gen_agg_q)).first()
            tank_balance, tank_capacity = gen_agg if gen_agg else (0.0, 0.0)

        rec_query = select(
            func.coalesce(func.sum(FuelReceipt.liters), 0.0),
            func.coalesce(func.sum(FuelReceipt.cost_total), 0.0)
        )
        total_received_l, total_spent_uah = (await db.execute(rec_query)).first()

        tr_query = select(func.coalesce(func.sum(FuelTransfer.liters), 0.0))
        if generator_id:
            tr_query = tr_query.where(FuelTransfer.generator_id == generator_id)
        total_transferred_l = (await db.execute(tr_query)).scalar_one()

        runs_query = select(func.coalesce(func.sum(GeneratorRun.calculated_consumption_l), 0.0))
        if generator_id:
            runs_query = runs_query.where(GeneratorRun.generator_id == generator_id)
        total_consumed_l = (await db.execute(runs_query)).scalar_one()

    avg_price = round(float(total_spent_uah) / float(total_received_l), 2) if float(total_received_l) > 0 else 0.0

    canister_q = select(
        func.coalesce(func.sum(CanisterPool.total_count), 0),
        func.coalesce(func.sum(CanisterPool.full_count), 0),
        func.coalesce(func.sum(CanisterPool.empty_count), 0),
        func.coalesce(func.sum(CanisterPool.away_refill_count), 0),
        func.coalesce(func.sum(CanisterPool.reserve_liters), 0.0),
    ).where(CanisterPool.is_active == True)  # noqa: E712
    if facility_id is not None:
        canister_q = canister_q.where(CanisterPool.facility_id == facility_id)
    c_total, c_full, c_empty, c_away, c_reserve = (await db.execute(canister_q)).first()

    return FuelBalancesSummary(
        warehouse_balance_l=to_float(warehouse_balance, 3),
        tank_balance_l=to_float(tank_balance, 3),
        tank_capacity_l=to_float(tank_capacity, 3),
        total_received_l=to_float(total_received_l, 3),
        total_spent_uah=to_float(total_spent_uah, 2),
        avg_price_per_liter=avg_price,
        total_transferred_l=to_float(total_transferred_l, 3),
        total_calculated_consumed_l=to_float(total_consumed_l, 3),
        canisters_total=int(c_total or 0),
        canisters_full=int(c_full or 0),
        canisters_empty=int(c_empty or 0),
        canisters_away=int(c_away or 0),
        canister_reserve_l=to_float(c_reserve, 3),
    )


async def validate_and_reconcile_generator_tank_level(
    db: AsyncSession,
    generator: Generator,
    actual_fuel_l: float,
    user_id: Optional[int],
    ip_address: Optional[str] = None,
    context: str = "START",
    reason: Optional[str] = None,
    expected_before_l: Optional[float] = None
) -> float:
    """
    GEN-04, GEN-14: Валідація та звірка фактичного рівня пального в баку генератора
    в межах активної транзакції (без власного commit).
    Забороняє від'ємний залишок (< 0) та перевищення місткості бака (> tank_capacity_l).
    Якщо введений рівень відрізняється від розрахункового/попереднього, створює запис аудиту звірки.
    """
    actual_dec = to_liters(actual_fuel_l)
    cap_dec = to_liters(generator.tank_capacity_l)
    if actual_dec < Decimal("0.000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Рівень пального в баку не може бути від'ємним ({to_float(actual_dec, 3)} л)."
        )
    if actual_dec > cap_dec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Вказаний рівень пального ({to_float(actual_dec, 3)} л) перевищує місткість бака генератора ({to_float(cap_dec, 3)} л)."
        )

    prev_dec = to_liters(expected_before_l if expected_before_l is not None else generator.fuel_tank_level_l)
    diff_dec = actual_dec - prev_dec
    new_val_float = to_float(actual_dec, 3)
    generator.fuel_tank_level_l = new_val_float

    if abs(diff_dec) >= Decimal("0.001"):
        await log_audit(
            db=db,
            action="GENERATOR_FUEL_RECONCILED",
            entity_type="Generator",
            entity_id=str(generator.id),
            user_id=user_id,
            details={
                "context": context,
                "facility_id": generator.facility_id,
                "fuel_type": generator.fuel_type,
                "expected_balance_l": str(prev_dec),
                "actual_balance_l": str(actual_dec),
                "difference_l": str(diff_dec),
                "reason": (reason or f"Звірка фактичного рівня пального під час операції {context}")
            },
            ip_address=ip_address
        )
    return new_val_float


async def consume_generator_fuel(
    db: AsyncSession,
    generator: Generator,
    consumed_l: float,
    user_id: Optional[int],
    ip_address: Optional[str] = None,
    run_id: Optional[int] = None,
    actual_end_fuel_l: Optional[float] = None,
    discrepancy_reason: Optional[str] = None,
    allow_system_clamp: bool = False
) -> dict:
    """
    GEN-04, GEN-14: Єдиний сервісний механізм списання пального з бака генератора
    в межах спільної транзакції (без внутрішнього commit).
    - Забороняє від'ємне споживання (< 0).
    - Забороняє перехід залишку бака в мінус (< 0) для користувацьких операцій.
    - Забороняє встановлення залишку більше за місткість бака (> tank_capacity_l).
    - Фіксує розбіжність (discrepancy) між розрахунковим та фактичним залишком.
    """
    cons_dec = to_liters(consumed_l)
    if cons_dec < Decimal("0.000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обсяг спожитого пального не може бути від'ємним."
        )

    start_dec = to_liters(generator.fuel_tank_level_l)
    cap_dec = to_liters(generator.tank_capacity_l)
    expected_after_dec = start_dec - cons_dec
    fuel_shortage_dec = Decimal("0.000")

    if actual_end_fuel_l is not None:
        actual_dec = to_liters(actual_end_fuel_l)
        if actual_dec < Decimal("0.000"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцевий залишок пального в баку не може бути від'ємним ({to_float(actual_dec, 3)} л)."
            )
        if actual_dec > cap_dec:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцевий залишок пального ({to_float(actual_dec, 3)} л) перевищує місткість бака ({to_float(cap_dec, 3)} л)."
            )
        if expected_after_dec < Decimal("0.000"):
            fuel_shortage_dec = abs(expected_after_dec)
        final_dec = actual_dec
        generator.fuel_tank_level_l = to_float(final_dec, 3)

        diff_dec = actual_dec - expected_after_dec
        if abs(diff_dec) >= Decimal("0.001"):
            await log_audit(
                db=db,
                action="GENERATOR_FUEL_RECONCILED",
                entity_type="Generator",
                entity_id=str(generator.id),
                user_id=user_id,
                details={
                    "context": "STOP",
                    "run_id": run_id,
                    "facility_id": generator.facility_id,
                    "fuel_type": generator.fuel_type,
                    "start_balance_l": str(start_dec),
                    "calculated_consumption_l": str(cons_dec),
                    "expected_balance_l": str(expected_after_dec),
                    "actual_balance_l": str(actual_dec),
                    "difference_l": str(diff_dec),
                    "reason": discrepancy_reason or "Фактичний залишок пального при зупинці генератора"
                },
                ip_address=ip_address
            )
    else:
        if expected_after_dec < Decimal("0.000"):
            if allow_system_clamp:
                fuel_shortage_dec = abs(expected_after_dec)
                final_dec = Decimal("0.000")
                generator.fuel_tank_level_l = 0.0
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Недостатньо пального в баку генератора: наявно {to_float(start_dec, 3)} л, "
                        f"розрахункова витрата становить {to_float(cons_dec, 3)} л. "
                        f"Від'ємний залишок бака заборонено. Вкажіть фактичний кінцевий залишок або виконайте заправку."
                    )
                )
        else:
            final_dec = expected_after_dec
            generator.fuel_tank_level_l = to_float(final_dec, 3)

    return {
        "start_fuel_l": to_float(start_dec, 3),
        "end_fuel_l": to_float(final_dec, 3),
        "consumed_l": to_float(cons_dec, 3),
        "expected_end_fuel_l": to_float(expected_after_dec, 3),
        "fuel_shortage_l": to_float(fuel_shortage_dec, 3),
    }

