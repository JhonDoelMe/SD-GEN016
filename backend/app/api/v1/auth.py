import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.core.security import (
    verify_password,
    verify_dummy_password,
    create_access_token,
    check_login_rate_limit,
    record_failed_login,
    reset_login_attempts,
)
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

    # Check brute-force rate limit before querying or hashing
    retry_after = check_login_rate_limit(ip, login_clean)
    if retry_after:
        await log_audit(
            db=db,
            action="AUTH_LOGIN_LOCKED",
            entity_type="User",
            entity_id=login_clean[:64],
            details={"reason": "Too many failed login attempts", "retry_after_sec": retry_after},
            ip_address=ip
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Забагато невдалих спроб входу. Спробуйте знову через {retry_after} сек.",
            headers={"Retry-After": str(retry_after)}
        )

    res = await db.execute(select(User).where(func.lower(User.login) == func.lower(login_clean)))
    user = res.scalars().first()

    if not user:
        # Constant-time dummy bcrypt check to prevent username enumeration via timing
        verify_dummy_password(login_data.password)
        record_failed_login(ip, login_clean)
        await log_audit(
            db=db,
            action="AUTH_LOGIN_FAILED",
            entity_type="User",
            entity_id=login_clean[:64],
            details={"reason": "Invalid login or password"},
            ip_address=ip
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний логін або пароль"
        )

    if not verify_password(login_data.password, user.password_hash):
        record_failed_login(ip, login_clean)
        await log_audit(
            db=db,
            action="AUTH_LOGIN_FAILED",
            entity_type="User",
            entity_id=login_clean[:64],
            user_id=user.id,
            details={"reason": "Invalid login or password"},
            ip_address=ip
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний логін або пароль"
        )

    if not user.is_active:
        record_failed_login(ip, login_clean)
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

    reset_login_attempts(ip, login_clean)

    # Gather user roles and permissions
    role_names = [r.name for r in user.roles]
    permissions_set = set()
    for r in user.roles:
        for p in r.permissions:
            permissions_set.add(p.code)

    # Configure token lifetime and cookie duration based on remember_me
    if login_data.remember_me:
        token_delta = datetime.timedelta(days=60)
        cookie_max_age = 60 * 86400  # 60 days
    else:
        token_delta = datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        cookie_max_age = None  # Session cookie

    token = create_access_token({"sub": str(user.id), "login": user.login}, expires_delta=token_delta)

    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )

    # Set secure HTTP-only cookie
    cookie_kwargs = {
        "key": "access_token",
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "secure": is_https,
        "path": "/",
    }
    if cookie_max_age is not None:
        cookie_kwargs["max_age"] = cookie_max_age

    response.set_cookie(**cookie_kwargs)

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
    response.delete_cookie(key="access_token", path="/")
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
