from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.services.auth import (
    authenticate_user,
    create_login_session,
    login_rate_limited,
    logout_session,
)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


def set_session_cookie(response: Response, session_id: str, expires_at: datetime) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        expires=expires_at,
        max_age=settings.session_days * 24 * 60 * 60,
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    if login_rate_limited(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    session_id, expires_at = create_login_session(user)
    set_session_cookie(response, session_id, expires_at)
    return {"user": public_user(user)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    settings = get_settings()
    logout_session(request.cookies.get(settings.session_cookie_name))
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me")
def me(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {"user": public_user(user)}
