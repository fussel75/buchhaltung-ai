from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.services.auth import hash_password
from app.services.database import create_user, get_document, list_users, update_user

router = APIRouter()


class UserCreateRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "user"
    allowed_tenant_ids: list[str] | None = None
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    allowed_tenant_ids: list[str] | None = None
    is_active: bool | None = None
    password: str | None = None


def require_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def user_can_access_tenant(user: dict, tenant_id: str) -> bool:
    allowed_tenant_ids = user.get("allowed_tenant_ids") or []
    return user.get("role") == "admin" or "*" in allowed_tenant_ids or tenant_id in allowed_tenant_ids


def require_tenant_access(request: Request, tenant_id: str) -> dict:
    user = require_user(request)
    if not user_can_access_tenant(user, tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access required")
    return user


def require_document_access(request: Request, document_id: UUID) -> dict:
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    require_tenant_access(request, document["tenant_id"])
    return document


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
        allowed_tenant_ids=payload.allowed_tenant_ids,
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
        allowed_tenant_ids=payload.allowed_tenant_ids,
        is_active=payload.is_active,
        password_hash=password_hash,
    )
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"user": user}
