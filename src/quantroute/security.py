"""HTTP security and Role-Based Access Control (RBAC) for the production API (SIH26137).

Provides:
  * Role hierarchy: ``ADMIN`` > ``DISPATCHER`` > ``DRIVER`` > ``VIEWER``.
  * Multi-role key and bearer token verification.
  * Fine-grained route authorization guards (e.g. ``require_role(Role.DISPATCHER)``).
  * Request-size limits, correlation IDs, and conservative security headers.
"""

from __future__ import annotations

import hmac
import os
import secrets
from collections.abc import Awaitable, Callable
from enum import Enum

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse, Response

from quantroute.config import Settings

PUBLIC_PATHS = {"/health", "/ready", "/", "/docs", "/openapi.json", "/dashboard"}


class Role(str, Enum):
    ADMIN = "admin"
    DISPATCHER = "dispatcher"
    DRIVER = "driver"
    VIEWER = "viewer"


_ROLE_RANK = {
    Role.ADMIN: 4,
    Role.DISPATCHER: 3,
    Role.DRIVER: 2,
    Role.VIEWER: 1,
}


def get_token_role(token: str, settings: Settings) -> Role | None:
    """Determine the role associated with the presented token or API key."""
    admin_key = os.getenv("QUANTROUTE_ADMIN_KEY") or settings.api_key
    disp_key = os.getenv("QUANTROUTE_DISPATCHER_KEY")
    driver_key = os.getenv("QUANTROUTE_DRIVER_KEY")
    viewer_key = os.getenv("QUANTROUTE_VIEWER_KEY")

    if admin_key and hmac.compare_digest(token, admin_key):
        return Role.ADMIN
    if disp_key and hmac.compare_digest(token, disp_key):
        return Role.DISPATCHER
    if driver_key and hmac.compare_digest(token, driver_key):
        return Role.DRIVER
    if viewer_key and hmac.compare_digest(token, viewer_key):
        return Role.VIEWER

    # Fallback: if single api_key is configured, it grants ADMIN access
    if settings.api_key and hmac.compare_digest(token, settings.api_key):
        return Role.ADMIN

    return None


def extract_token(request: Request) -> str | None:
    """Extract credentials from X-API-Key or Authorization Bearer header."""
    key = request.headers.get("X-API-Key")
    if key:
        return key.strip()

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()

    return None


def require_role(min_role: Role = Role.VIEWER):
    """FastAPI dependency to enforce role-based access control."""

    async def dependency(request: Request) -> Role:
        settings: Settings = request.app.state.settings
        if not settings.auth_enabled or request.url.path in PUBLIC_PATHS:
            return Role.ADMIN

        token = extract_token(request)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing authentication credentials",
            )

        user_role = get_token_role(token, settings)
        if user_role is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid api key or credentials",
            )

        if _ROLE_RANK[user_role] < _ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"forbidden: requires at least '{min_role.value}' role",
            )

        request.state.role = user_role
        return user_role

    return dependency


def require_api_key(settings: Settings):
    """Backwards-compatible dependency: checks valid key with at least VIEWER permissions."""
    return require_role(Role.VIEWER)


async def security_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    settings: Settings,
) -> Response:
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > settings.max_request_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "invalid content-length"}, status_code=400)

    request_id = request.headers.get("X-Request-ID") or secrets.token_hex(12)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response
