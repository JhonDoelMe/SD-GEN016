import datetime
import re
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

LOGIN_REGEX = re.compile(r"^[a-zA-Z0-9_.\-]+$")


def validate_password_complexity(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Пароль містить недопустимі символи")
    if len(value) < 8 or len(value) > 128:
        raise ValueError("Пароль повинен містити від 8 до 128 символів")
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        raise ValueError("Пароль повинен містити щонайменше одну літеру та одну цифру")
    return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserSummary"


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    remember_me: bool = True

    @field_validator("login")
    @classmethod
    def sanitize_login_input(cls, v: str) -> str:
        v = v.strip()
        if not v or "\x00" in v or any(ord(c) < 32 for c in v):
            raise ValueError("Некоректний формат логіна")
        return v

    @field_validator("password")
    @classmethod
    def sanitize_password_input(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("Некоректний формат пароля")
        return v


class UserSummary(BaseModel):
    id: int
    login: str
    full_name: str
    email: Optional[str] = None
    is_active: bool
    is_superadmin: bool
    roles: List[str] = []
    permissions: List[str] = []

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    login: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=150)
    email: Optional[str] = Field(None, max_length=150)
    role_ids: List[int] = []

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 50 or not LOGIN_REGEX.match(v):
            raise ValueError(
                "Логін повинен містити від 3 до 50 символів (латинські літери, цифри, '_', '.', '-')"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_complexity(v)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = v.strip()
        if not v or "<" in v or ">" in v or "\x00" in v:
            raise ValueError("ПІБ містить недопустимі символи")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if "<" in v or ">" in v or "\x00" in v or " " in v:
            raise ValueError("Некоректний формат email")
        return v


class UserUpdate(BaseModel):
    login: Optional[str] = Field(None, min_length=3, max_length=50)
    full_name: Optional[str] = Field(None, max_length=150)
    email: Optional[str] = Field(None, max_length=150)
    is_active: Optional[bool] = None
    role_ids: Optional[List[int]] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if len(v) < 3 or len(v) > 50 or not LOGIN_REGEX.match(v):
            raise ValueError("Логін повинен містити 3–50 символів (латинські літери, цифри, '_', '.', '-')")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v or "<" in v or ">" in v or "\x00" in v:
            raise ValueError("ПІБ містить недопустимі символи")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if "<" in v or ">" in v or "\x00" in v or " " in v or "@" not in v:
            raise ValueError("Некоректний формат email")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return validate_password_complexity(v)


class UserPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return validate_password_complexity(v)


class UserOut(BaseModel):
    id: int
    login: str
    full_name: str
    email: Optional[str] = None
    is_active: bool
    is_superadmin: bool
    created_at: datetime.datetime
    roles: List["RoleOut"] = []

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: int
    code: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    permissions: List[PermissionOut] = []

    model_config = {"from_attributes": True}


TokenResponse.model_rebuild()
