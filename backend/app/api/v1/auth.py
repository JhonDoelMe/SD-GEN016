import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.core.security import verify_password, create_access_token
from backend.app.models.user import User
from backend.app.schemas.auth import LoginRequest, TokenResponse, UserSummary
from backend.app.api.deps import get_current_user, get_client_ip
from backend.app.services.audit_service import log_audit

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["Автентифікація"])


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    ip = get_client_ip(request)
    login_clean = login_data.login.strip()

    res = await db.execute(select(User).where(func.lower(User.login) == func.lower(login_clean)))
    user = res.scalars().first()

    if not user or not verify_password(login_data.password, user.password_hash):
        await log_audit(
            db=db,
            action="AUTH_LOGIN_FAILED",
            entity_type="User",
            entity_id=login_clean,
            details={"reason": "Invalid login or password"},
            ip_address=ip
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний логін або пароль"
        )

    if not user.is_active:
        await log_audit(
            db=db,
            action="AUTH_LOGIN_BLOCKED",
            entity_type="User",
            entity_id=str(user.id),
            user_id=user.id,
            details={"reason": "User is inactive/blocked"},
            ip_address=ip
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Обліковий запис заблокований адміністратором"
        )

    # Gather user roles and permissions
    role_names = [r.name for r in user.roles]
    permissions_set = set()
    for r in user.roles:
        for p in r.permissions:
            permissions_set.add(p.code)

    token = create_access_token({"sub": str(user.id), "login": user.login})

    # Set secure HTTP-only cookie
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )

    await log_audit(
        db=db,
        action="AUTH_LOGIN_SUCCESS",
        entity_type="User",
        entity_id=str(user.id),
        user_id=user.id,
        ip_address=ip
    )
    await db.commit()

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserSummary(
            id=user.id,
            login=user.login,
            full_name=user.full_name,
            email=user.email,
            is_active=user.is_active,
            is_superadmin=user.is_superadmin,
            roles=role_names,
            permissions=sorted(list(permissions_set))
        )
    )


@router.get("/me", response_model=UserSummary)
async def get_me(current_user: User = Depends(get_current_user)):
    role_names = [r.name for r in current_user.roles]
    permissions_set = set()
    for r in current_user.roles:
        for p in r.permissions:
            permissions_set.add(p.code)

    return UserSummary(
        id=current_user.id,
        login=current_user.login,
        full_name=current_user.full_name,
        email=current_user.email,
        is_active=current_user.is_active,
        is_superadmin=current_user.is_superadmin,
        roles=role_names,
        permissions=sorted(list(permissions_set))
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    response.delete_cookie(key="access_token")
    await log_audit(
        db=db,
        action="AUTH_LOGOUT",
        entity_type="User",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return {"message": "Успішний вихід із системи"}
