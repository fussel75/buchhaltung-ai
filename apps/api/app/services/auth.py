from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import get_settings
from app.services.database import (
    count_users,
    create_session,
    create_user,
    delete_expired_sessions,
    delete_session,
    get_user_by_email,
    get_user_by_session,
    renew_session,
)

password_hasher = PasswordHasher()
_login_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def bootstrap_initial_admin() -> None:
    settings = get_settings()
    if count_users() > 0:
        return
    if not settings.initial_admin_email or not settings.initial_admin_password:
        return

    create_user(
        email=settings.initial_admin_email,
        password_hash=hash_password(settings.initial_admin_password),
        display_name="Admin",
        role="admin",
    )


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def authenticate_user(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if not user or not user["is_active"]:
        return None
    try:
        password_hasher.verify(user["password_hash"], password)
    except VerifyMismatchError:
        return None
    except Exception:
        return None
    user.pop("password_hash", None)
    return user


def create_login_session(user: dict) -> tuple[str, datetime]:
    settings = get_settings()
    session_id = token_urlsafe(48)
    expires_at = session_expiry()
    create_session(session_id=session_id, user_id=UUID(user["id"]), expires_at=expires_at)
    delete_expired_sessions()
    return session_id, expires_at


def session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=get_settings().session_days)


def get_session_user(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    return get_user_by_session(session_id)


def renew_login_session(session_id: str) -> datetime:
    expires_at = session_expiry()
    renew_session(session_id=session_id, expires_at=expires_at)
    return expires_at


def logout_session(session_id: str | None) -> None:
    if session_id:
        delete_session(session_id)


def login_rate_limited(key: str) -> bool:
    now = datetime.now(UTC)
    window_start = now - timedelta(minutes=1)
    attempts = _login_attempts[key]
    while attempts and attempts[0] < window_start:
        attempts.popleft()
    if len(attempts) >= 5:
        return True
    attempts.append(now)
    return False
