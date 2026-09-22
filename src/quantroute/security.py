"""HTTP security controls for the local production API.

The controls are intentionally framework-light and can be independently tested:
request-size limits, API-key authentication, request correlation IDs and conservative
security headers. TLS should be terminated by the local reverse proxy in production.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse, Response

from quantroute.config import Settings

PUBLIC_PATHS = {"/health", "/ready"}


def require_api_key(settings: Settings):
    async def dependency(request: Request) -> None:
        if not settings.auth_enabled or request.url.path in PUBLIC_PATHS:
            return
        presented = request.headers.get("X-API-Key", "")
        expected = settings.api_key or ""
        if not presented or not hmac.compare_digest(presented, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    return dependency


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
