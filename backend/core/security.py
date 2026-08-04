import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.core.config import get_settings
from backend.core.errors import error_response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Protect non-health API routes with one local Bearer token."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        public_health_paths = {
            "/health/live",
            "/health/ready",
            f"{settings.api_prefix}/health/live",
            f"{settings.api_prefix}/health/ready",
        }
        if (
            settings.app_env == "test"
            or request.url.path in public_health_paths
            or request.method == "OPTIONS"
        ):
            return await call_next(request)
        expected = settings.app_api_key
        if not expected:
            return error_response(
                "APP_API_KEY is not configured.",
                503,
                error_code="AUTH_NOT_CONFIGURED",
            )
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
            return error_response(
                "A valid Bearer API key is required.",
                401,
                error_code="AUTH_REQUIRED",
            )
        return await call_next(request)
