from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.routes.auth import set_session_cookie
from app.services.auth import get_session_user, renew_login_session


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        if not request.url.path.startswith("/api/") or _is_public_api_path(request.url.path):
            return await call_next(request)

        settings = get_settings()
        session_id = request.cookies.get(settings.session_cookie_name)
        user = get_session_user(session_id)
        if not user:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        request.state.user = user
        response = await call_next(request)
        if session_id:
            set_session_cookie(response, session_id, renew_login_session(session_id))
        return response


def _is_public_api_path(path: str) -> bool:
    return path in {"/api/auth/login", "/api/auth/logout", "/api/health", "/api/masterdata/assignment-units/sync"}
