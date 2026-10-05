import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.config import settings
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, Role, Permission
from backend.app.models.fuel import FuelStock
from backend.app.models.facility import Facility

logger = logging.getLogger("init_service")

ALL_PERMISSIONS = [
    # Generator
    ("generator:view", "Перегляд генератора та його статусу"),
    ("generator:start", "Запуск генератора"),
    ("generator:stop", "Зупинка генератора"),
    ("generator:configure", "Налаштування параметрів та графіка генератора"),
    # Fuel
    ("fuel:view", "Перегляд залишків та історії палива"),
    ("fuel:receipt", "Оприбуткування палива на склад ГСМ"),
    ("fuel:transfer", "Заправка бака генератора зі складу"),
    # Maintenance
    ("maintenance:view", "Перегляд планів та історії ТО"),
    ("maintenance:create_intermediate", "Фіксація проміжного ТО"),
    ("maintenance:perform_scheduled", "Виконання регламентного ТО"),
    # Faults
    ("faults:view", "Перегляд несправностей"),
    ("faults:create", "Реєстрація несправності"),
    ("faults:manage", "Керування статусом та закриттям несправностей"),
    # Reports & Audit
    ("reports:view", "Перегляд експлуатаційних звітів"),
    ("reports:export", "Експорт звітів"),
    ("audit:view", "Перегляд журналу аудиту"),
    ("system:adjust", "Виконання системних коригувань лічильників (SuperAdmin)"),
    # Users
    ("users:manage", "Керування користувачами та призначення ролей"),
]

ROLE_PERMISSIONS_MAP = {
    "superadmin": [code for code, _ in ALL_PERMISSIONS],
    "admin": [
        code for code, _ in ALL_PERMISSIONS
        if code not in ("system:adjust",)
    ],
    "operator": [
        "generator:view", "generator:start", "generator:stop",
        "fuel:view", "fuel:receipt", "fuel:transfer",
        "maintenance:view", "maintenance:create_intermediate", "maintenance:perform_scheduled",
        "faults:view", "faults:create",
        "reports:view"
    ],
    "viewer": [
        "generator:view", "fuel:view", "maintenance:view", "faults:view", "reports:view"
    ],
}


async def seed_initial_data(db: AsyncSession) -> None:
    # 1. Seed Permissions
    existing_perms_res = await db.execute(select(Permission))
    existing_perms = {p.code: p for p in existing_perms_res.scalars().all()}

    for code, desc in ALL_PERMISSIONS:
        if code not in existing_perms:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            existing_perms[code] = perm
    await db.flush()

    # 2. Seed Roles
    existing_roles_res = await db.execute(select(Role))
    existing_roles = {r.name: r for r in existing_roles_res.scalars().all()}

    for role_name, perm_codes in ROLE_PERMISSIONS_MAP.items():
        if role_name not in existing_roles:
            role = Role(
                name=role_name,
                description=f"Роль {role_name.capitalize()}"
            )
            for p_code in perm_codes:
                if p_code in existing_perms:
                    role.permissions.append(existing_perms[p_code])
            db.add(role)
            existing_roles[role_name] = role
        else:
            role = existing_roles[role_name]
            # Ensure permissions are up to date
            current_codes = {p.code for p in role.permissions}
            for p_code in perm_codes:
                if p_code not in current_codes and p_code in existing_perms:
                    role.permissions.append(existing_perms[p_code])
    await db.flush()

    # 3. Seed Default Facility if none exists
    fac_res = await db.execute(select(Facility))
    default_fac = fac_res.scalars().first()
    if not default_fac:
        default_fac = Facility(
            id=1,
            name="Основний об'єкт",
            address="вул. Центральна, 1",
            description="Головна виробничо-офісна локація",
            timezone="Europe/Kyiv"
        )
        db.add(default_fac)
        await db.flush()

    # 4. Seed or update Initial SuperAdmin
    admin_login = settings.INITIAL_ADMIN_LOGIN.strip()
    admin_pass = settings.INITIAL_ADMIN_PASSWORD

    admin_res = await db.execute(select(User).where(func.lower(User.login) == func.lower(admin_login)))
    superadmin_user = admin_res.scalars().first()

    if not superadmin_user:
        superadmin_user = User(
            login=admin_login,
            email=settings.INITIAL_ADMIN_EMAIL,
            password_hash=get_password_hash(admin_pass),
            full_name=settings.INITIAL_ADMIN_FULL_NAME,
            is_active=True,
            is_superadmin=True,
            facility_id=default_fac.id if default_fac else 1,
        )
        if "superadmin" in existing_roles:
            superadmin_user.roles.append(existing_roles["superadmin"])
        db.add(superadmin_user)
        await db.flush()
        logger.info(f"Initialized new SuperAdmin user: '{admin_login}'")
    else:
        # Guarantee superadmin has updated password hash from settings.INITIAL_ADMIN_PASSWORD,
        # is active, and has superadmin role
        superadmin_user.password_hash = get_password_hash(admin_pass)
        superadmin_user.is_active = True
        superadmin_user.is_superadmin = True
        if "superadmin" in existing_roles and existing_roles["superadmin"] not in superadmin_user.roles:
            superadmin_user.roles.append(existing_roles["superadmin"])
        await db.flush()
        logger.info(f"Synchronized SuperAdmin user '{admin_login}' with current settings/env password")

    # 5. Seed Default FuelStock if none exists
    stock_res = await db.execute(select(FuelStock))
    if not stock_res.scalars().first():
        stock = FuelStock(
            name="Основний склад ГСМ",
            fuel_type="А-95",
            current_balance_l=0.0,
            facility_id=default_fac.id if default_fac else 1,
        )
        db.add(stock)
        await db.flush()

    await db.commit()
