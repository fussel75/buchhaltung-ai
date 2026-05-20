from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.services.auth import hash_password
from app.services.database import create_user, list_users, update_user

router = APIRouter()


class UserCreateRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "user"
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def _validate_role(role: str) -> str:
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="role must be admin or user")
    return role


@router.get("")
def get_users(request: Request) -> dict:
    require_admin(request)
    return {"users": list_users()}


@router.post("", status_code=status.HTTP_201_CREATED)
def post_user(payload: UserCreateRequest, request: Request) -> dict:
    require_admin(request)
    if len(payload.password) < 10:
        raise HTTPException(status_code=400, detail="password must contain at least 10 characters")
    user = create_user(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=_validate_role(payload.role),
        is_active=payload.is_active,
    )
    return {"user": user}


@router.patch("/{user_id}")
def patch_user(user_id: UUID, payload: UserUpdateRequest, request: Request) -> dict:
    current_user = require_admin(request)
    role = _validate_role(payload.role) if payload.role is not None else None
    password_hash = hash_password(payload.password) if payload.password else None
    if str(user_id) == current_user["id"] and payload.is_active is False:
        raise HTTPException(status_code=400, detail="current admin cannot deactivate itself")
    user = update_user(
        user_id=user_id,
        display_name=payload.display_name,
        role=role,
        is_active=payload.is_active,
        password_hash=password_hash,
    )
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"user": user}
