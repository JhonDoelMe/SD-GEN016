from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, Role
from backend.app.schemas.auth import UserCreate, UserUpdate, UserPasswordReset, UserOut, RoleOut
from backend.app.api.deps import get_current_superadmin, require_permission, get_client_ip
from backend.app.services.audit_service import log_audit

router = APIRouter(prefix="/users", tags=["Користувачі та Ролі"])


@router.get("", response_model=List[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:manage"))
):
    res = await db.execute(
        select(User).options(selectinload(User.roles)).order_by(User.id.asc())
    )
    users = res.scalars().all()
    return users


@router.get("/roles", response_model=List[RoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("users:manage"))
):
    res = await db.execute(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.id.asc())
    )
    roles = res.scalars().all()
    return roles


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    clean_login = data.login.strip()
    existing = await db.execute(select(User).where(func.lower(User.login) == func.lower(clean_login)))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Користувач із логіном '{clean_login}' вже існує"
        )

    # Fetch roles
    roles = []
    if data.role_ids:
        roles_res = await db.execute(select(Role).where(Role.id.in_(data.role_ids)))
        roles = list(roles_res.scalars().all())

    new_user = User(
        login=clean_login,
        email=data.email.strip() if data.email else None,
        full_name=data.full_name.strip(),
        password_hash=get_password_hash(data.password),
        is_active=True,
        is_superadmin=False,
    )
    new_user.roles = roles
    db.add(new_user)
    await db.flush()

    await log_audit(
        db=db,
        action="USER_CREATED",
        entity_type="User",
        entity_id=str(new_user.id),
        user_id=current_user.id,
        details={"login": new_user.login, "roles": [r.name for r in roles]},
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return new_user


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    target_user_res = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    target_user = target_user_res.scalars().first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Користувача не знайдено")

    if target_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Редагування облікового запису головного суперадміністратора заборонено"
        )

    # Login uniqueness check
    if data.login is not None:
        clean_login = data.login.strip()
        if clean_login.lower() != target_user.login.lower():
            dup_res = await db.execute(
                select(User).where(func.lower(User.login) == func.lower(clean_login), User.id != user_id)
            )
            if dup_res.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Користувач із логіном '{clean_login}' вже існує"
                )
            target_user.login = clean_login

    if data.full_name is not None:
        target_user.full_name = data.full_name.strip()
    if data.email is not None:
        target_user.email = data.email.strip() if data.email else None
    if data.is_active is not None:
        if target_user.id == current_user.id and not data.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неможливо заблокувати власний обліковий запис"
            )
        target_user.is_active = data.is_active

    if data.role_ids is not None:
        roles_res = await db.execute(select(Role).where(Role.id.in_(data.role_ids)))
        target_user.roles = list(roles_res.scalars().all())

    if data.password:
        target_user.password_hash = get_password_hash(data.password)

    await db.flush()

    await log_audit(
        db=db,
        action="USER_UPDATED",
        entity_type="User",
        entity_id=str(target_user.id),
        user_id=current_user.id,
        details={
            "login": target_user.login,
            "full_name": target_user.full_name,
            "email": target_user.email,
            "is_active": target_user.is_active,
            "roles": [r.name for r in target_user.roles]
        },
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return target_user


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    data: UserPasswordReset,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Користувача не знайдено")

    if target_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Скидання пароля головного суперадміністратора заборонено"
        )

    target_user.password_hash = get_password_hash(data.new_password)
    await db.flush()

    await log_audit(
        db=db,
        action="USER_PASSWORD_RESET",
        entity_type="User",
        entity_id=str(target_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return {"message": f"Пароль для користувача '{target_user.login}' успішно змінено"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Користувача не знайдено")

    if target_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неможливо видалити головного суперадміністратора")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неможливо видалити власний обліковий запис")

    user_login = target_user.login
    try:
        async with db.begin_nested():
            await db.delete(target_user)
            await db.flush()
        action_msg = f"Користувача '{user_login}' успішно видалено з системи"
        audit_action = "USER_DELETED"
    except Exception:
        target_user.is_active = False
        await db.flush()
        action_msg = f"Користувач '{user_login}' має пов'язані записи в системі, тому його акаунт деактивовано для збереження історії"
        audit_action = "USER_DEACTIVATED"

    await log_audit(
        db=db,
        action=audit_action,
        entity_type="User",
        entity_id=str(user_id),
        user_id=current_user.id,
        details={"login": user_login},
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return {"message": action_msg}
