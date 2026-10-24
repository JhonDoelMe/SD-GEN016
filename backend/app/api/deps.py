import re
from typing import Callable, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.core.security import decode_access_token, compute_password_signature
from backend.app.models.user import User
from backend.app.models.generator import Generator

security_scheme = HTTPBearer(auto_error=False)
_SAFE_IP_RE = re.compile(r"^[0-9a-fA-F:.\-]+$")


def get_client_ip(request: Request) -> Optional[str]:
    """
    Safely extracts client IP:
    1. Prioritizes X-Real-IP set by our reverse proxy (Nginx).
    2. Otherwise takes the LAST valid entry in X-Forwarded-For (appended by trusted reverse proxy),
       preventing clients from spoofing the first X-Forwarded-For entry.
    3. Falls back to request.client.host.
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        candidate = real_ip.strip()
        if candidate and len(candidate) <= 45 and _SAFE_IP_RE.match(candidate):
            return candidate

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            candidate = parts[-1]
            if len(candidate) <= 45 and _SAFE_IP_RE.match(candidate):
                return candidate

    return request.client.host if request.client else None


def is_user_admin_or_super(user: User) -> bool:
    """Returns True if the user is SuperAdmin or has admin/superadmin role."""
    if user.is_superadmin:
        return True
    role_names = {r.name.lower() for r in (user.roles or [])}
    return bool(role_names.intersection({"admin", "superadmin"}))


def verify_facility_access(current_user: User, facility_id: Optional[int]) -> Optional[int]:
    """
    Enforces strict Multi-site facility isolation (Variant B):
    - SuperAdmin and Admin have access to all facilities.
    - Operators and Viewers are restricted to their assigned `current_user.facility_id`.
      If they request a different facility_id, raises 403 Forbidden.
      If facility_id is None, returns their assigned facility_id.
    """
    if is_user_admin_or_super(current_user):
        return facility_id

    user_fac_id = current_user.facility_id
    if not user_fac_id:
        return facility_id

    if facility_id is not None and int(facility_id) != int(user_fac_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ заборонено: ви можете працювати лише з об'єктом, закріпленим за вашим обліковим записом"
        )
    return user_fac_id


async def verify_generator_facility_access(
    db: AsyncSession,
    current_user: User,
    generator_id: Optional[int]
) -> None:
    """
    Verifies that the target generator exists (404 if not found) and that
    a non-admin user has access to the generator's facility (403 if mismatch).
    """
    if generator_id is None:
        return

    gen = await db.get(Generator, generator_id)
    if not gen:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Генератор не знайдено"
        )

    if not is_user_admin_or_super(current_user) and current_user.facility_id:
        if gen.facility_id and int(gen.facility_id) != int(current_user.facility_id):
            from backend.app.models.facility import Facility
            fac = await db.get(Facility, gen.facility_id)
            fac_name = fac.name if fac else f"ID {gen.facility_id}"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Ви не можете вибрати генератор '{gen.name}', він закріплений за об'єктом '{fac_name}'"
            )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # Check cookie session as fallback
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необхідна авторизація",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недійсний або прострочений токен авторизації",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Некоректний токен авторизації"
        )

    res = await db.execute(select(User).where(User.id == user_id_int))
    user = res.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Користувача не знайдено"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Користувач заблокований адміністратором"
        )

    # Validate password signature if present in token (invalidates sessions on password change/reset)
    token_pwd_sig = payload.get("pwd_sig")
    if token_pwd_sig:
        expected_sig = compute_password_signature(user.password_hash)
        if token_pwd_sig != expected_sig:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Сесія недійсна через зміну пароля. Увійдіть знову.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


async def get_current_superadmin(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ дозволено виключно головному системному адміністратору"
        )
    return current_user


async def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    if is_user_admin_or_super(current_user):
        return current_user
    user_permissions = {
        perm.code
        for role in (current_user.roles or [])
        for perm in (role.permissions or [])
    }
    if "settings:manage" in user_permissions:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Доступ дозволено виключно адміністратору системи"
    )


def require_permission(perm_code: str) -> Callable:
    async def permission_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:
        # SuperAdmin has full bypass for all permissions
        if current_user.is_superadmin:
            return current_user

        # Check permissions from assigned roles
        user_permissions = set()
        for role in current_user.roles:
            for perm in role.permissions:
                user_permissions.add(perm.code)

        if perm_code not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостатньо прав для виконання операції (потрібен дозвіл: {perm_code})"
            )
        return current_user

    return permission_checker
