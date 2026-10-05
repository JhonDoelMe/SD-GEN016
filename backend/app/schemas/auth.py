import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserSummary"


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


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
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1, max_length=150)
    email: Optional[str] = None
    role_ids: List[int] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[List[int]] = None


class UserPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6)


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
