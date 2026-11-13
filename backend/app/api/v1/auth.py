import asyncio
import datetime
import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import get_db
import secrets
import hashlib
from sqlalchemy import or_, update
from backend.app.core.timezone import now_utc
from backend.app.core.security import (
    get_password_hash,
    verify_password,
    verify_dummy_password,
    create_access_token,
)
from backend.app.services.auth_security_service import (
    revoke_access_token_db,
    check_login_rate_limit_db,
    record_failed_login_db,
    reset_login_attempts_db,
    check_password_reset_rate_limit_db,
    record_password_reset_attempt_db,
)
from backend.app.models.user import User, PasswordResetToken
from backend.app.schemas.auth import (
    LoginRequest,
    ChangePasswordRequest,
    ProfileUpdateRequest,
    TokenResponse,
    UserSummary,
    ForgotPasswordRequest,
    ResetPasswordRequest
)
from backend.app.services.avatar_service import delete_avatar_file, save_user_avatar
from backend.app.services.settings_service import get_runtime_setting
from backend.app.services.email_service import send_password_reset_email, send_password_changed_email
from backend.app.api.deps import get_current_user, get_client_ip, security_scheme
from backend.app.services.audit_service import log_audit

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["Автентифікація"])


def _build_user_summary(user: User) -> UserSummary:
    role_names = [r.name for r in user.roles]
    permissions_set = {p.code for r in user.roles for p in r.permissions}
    return UserSummary(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        email=user.email,
        facility_id=user.facility_id,
        avatar_url=user.avatar_url,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        roles=role_names,
        permissions=sorted(permissions_set),
    )


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
    retry_after = await check_login_rate_limit_db(db, ip, login_clean)
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
        await asyncio.to_thread(verify_dummy_password, login_data.password)
        await record_failed_login_db(db, ip, login_clean)
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

    is_pwd_valid = await asyncio.to_thread(verify_password, login_data.password, user.password_hash)
    if not is_pwd_valid:
        await record_failed_login_db(db, ip, login_clean)
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
        await record_failed_login_db(db, ip, login_clean)
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

    await reset_login_attempts_db(db, ip, login_clean)

    # Configure token lifetime and cookie duration based on remember_me
    if login_data.remember_me:
        token_delta = datetime.timedelta(days=60)
        cookie_max_age = 60 * 86400  # 60 days
    else:
        token_delta = datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        cookie_max_age = None  # Session cookie

    token = create_access_token(
        {"sub": str(user.id), "login": user.login},
        expires_delta=token_delta,
        password_hash=user.password_hash
    )

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
        user=_build_user_summary(user),
    )


@router.get("/me", response_model=UserSummary)
async def get_me(current_user: User = Depends(get_current_user)):
    return _build_user_summary(current_user)


@router.put("/me", response_model=UserSummary)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Оновлення власного ПІБ та email поточного користувача."""
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if "email" in payload.model_fields_set:
        current_user.email = payload.email

    await db.flush()
    await log_audit(
        db=db,
        action="PROFILE_UPDATED",
        entity_type="User",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        details={"full_name": current_user.full_name, "email": current_user.email},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return _build_user_summary(current_user)


@router.post("/me/avatar", response_model=UserSummary)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Завантаження або заміна власного аватара користувача (256x256 WebP)."""
    old_path = current_user.avatar_path
    new_path = await save_user_avatar(file, current_user.id)
    current_user.avatar_path = new_path

    await db.flush()
    await log_audit(
        db=db,
        action="AVATAR_UPDATED",
        entity_type="User",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        details={"avatar_path": new_path},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    if old_path and old_path != new_path:
        delete_avatar_file(old_path)
    return _build_user_summary(current_user)


@router.delete("/me/avatar", response_model=UserSummary)
async def delete_my_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Видалення власного аватара користувача."""
    old_path = current_user.avatar_path
    current_user.avatar_path = None

    await db.flush()
    await log_audit(
        db=db,
        action="AVATAR_DELETED",
        entity_type="User",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request),
    )
    await db.commit()
    if old_path:
        delete_avatar_file(old_path)
    return _build_user_summary(current_user)


@router.post("/change-password")
async def change_own_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Зміна власного пароля будь-яким авторизованим користувачем (включно з SuperAdmin)."""
    is_cur_valid = await asyncio.to_thread(verify_password, payload.current_password, current_user.password_hash)
    if not is_cur_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поточний пароль вказано невірно"
        )

    current_user.password_hash = await asyncio.to_thread(get_password_hash, payload.new_password)
    await db.flush()

    # Issue a fresh access token with the new password signature so current session stays valid
    new_token = create_access_token(
        {"sub": str(current_user.id), "login": current_user.login},
        password_hash=current_user.password_hash
    )

    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )
    response.set_cookie(
        key="access_token",
        value=new_token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        path="/",
    )

    await log_audit(
        db=db,
        action="USER_CHANGED_OWN_PASSWORD",
        entity_type="User",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    await db.commit()
    if current_user.email and get_runtime_setting("email_notify_password_change", True):
        try:
            await send_password_changed_email(
                to_addr=current_user.email,
                user_name=current_user.full_name,
                ip_address=get_client_ip(request),
                db=db
            )
        except Exception as mail_err:
            logger.warning(f"Failed to dispatch password changed notice to {current_user.email}: {mail_err}")
    return {
        "message": "Пароль успішно змінено",
        "access_token": new_token,
        "token_type": "bearer"
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Revoke active JWT token (from Authorization header or cookie)
    if credentials and credentials.credentials:
        await revoke_access_token_db(db, credentials.credentials)
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        await revoke_access_token_db(db, cookie_token)

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


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Ініціалізація скидання пароля через email.
    Захищено від timing attacks, перебору логінів та brute-force (max 3 спроби на 15 хв).
    """
    ip = get_client_ip(request)
    ident = payload.login_or_email.strip()

    retry_after = await check_password_reset_rate_limit_db(db, ip, ident)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Забагато запитів на відновлення пароля. Спробуйте через {retry_after} сек.",
            headers={"Retry-After": str(retry_after)}
        )

    await record_password_reset_attempt_db(db, ip, ident)
    await db.commit()

    res = await db.execute(
        select(User).where(
            or_(
                func.lower(User.login) == func.lower(ident),
                func.lower(User.email) == func.lower(ident)
            )
        )
    )
    user = res.scalars().first()

    generic_response = {
        "status": "ok",
        "message": "Якщо вказаний логін або email зареєстровано в системі та має прив'язану адресу електронної пошти, інструкції для відновлення надіслано на вашу пошту."
    }

    if not user or not user.is_active or not user.email:
        return generic_response

    # Invalidate any existing unused reset tokens for this user
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used == False)
        .values(used=True)
    )

    # Generate cryptographically secure token & SHA-256 hash
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = now_utc() + datetime.timedelta(minutes=20)

    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        used=False
    ))

    await log_audit(
        db=db,
        action="USER_PASSWORD_RESET_REQUESTED",
        entity_type="User",
        entity_id=str(user.id),
        user_id=user.id,
        details={"login": user.login, "email": user.email},
        ip_address=ip
    )
    await db.commit()

    # Dispatch email
    try:
        base_url = str(request.base_url).rstrip("/")
        if request.headers.get("x-forwarded-proto", "").lower() == "https":
            base_url = base_url.replace("http://", "https://")
        await send_password_reset_email(
            to_addr=user.email,
            user_name=user.full_name,
            reset_token=raw_token,
            base_url=base_url,
            db=db
        )
    except Exception as mail_err:
        logger.warning(f"Failed to dispatch password reset email to {user.email}: {mail_err}")

    return generic_response


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """
    Завершення відновлення пароля за одноразовим токеном.
    Перевіряє валідність токена, оновлює пароль, інвалідує старі сесії та надсилає підтвердження на email.
    """
    token_hash = hashlib.sha256(payload.token.strip().encode("utf-8")).hexdigest()
    current_time = now_utc()

    res = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > current_time
        )
    )
    reset_record = res.scalars().first()

    if not reset_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недійсне посилання або термін дії посилання для відновлення пароля (20 хв) вичерпано."
        )

    user = await db.get(User, reset_record.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Користувач не активний або заблокований адміністратором"
        )

    user.password_hash = await asyncio.to_thread(get_password_hash, payload.new_password)
    reset_record.used = True
    await db.flush()

    ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="USER_PASSWORD_RESET_COMPLETED",
        entity_type="User",
        entity_id=str(user.id),
        user_id=user.id,
        details={"login": user.login},
        ip_address=ip
    )
    await db.commit()

    if user.email and get_runtime_setting("email_notify_password_change", True):
        try:
            await send_password_changed_email(
                to_addr=user.email,
                user_name=user.full_name,
                ip_address=ip,
                db=db
            )
        except Exception as mail_err:
            logger.warning(f"Failed to dispatch password changed notice to {user.email}: {mail_err}")

    return {"message": "Пароль успішно змінено. Тепер ви можете увійти з новим паролем."}
