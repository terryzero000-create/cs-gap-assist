from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Domain error rendered through the unified API error shape."""

    def __init__(
        self,
        message: str,
        code: int = 400,
        *,
        error_code: str = "API_ERROR",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Create an API error with a user-facing message and HTTP code."""
        self.message = message
        self.code = code
        self.error_code = error_code
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


def error_response(
    message: str,
    code: int = 400,
    *,
    error_code: str = "API_ERROR",
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the standard error response payload."""
    return JSONResponse(
        status_code=code,
        content={
            "error": message,
            "code": code,
            "error_code": error_code,
            "retryable": retryable,
            "details": details or {},
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register application-wide exception handlers."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        """Render domain exceptions using the standard error shape."""
        return error_response(
            exc.message,
            exc.code,
            error_code=exc.error_code,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Render request validation failures as code 400 for API consistency."""
        validation_errors = [
            {
                "location": [str(item) for item in error.get("loc", ())],
                "message": str(error.get("msg", "Invalid value.")),
                "type": str(error.get("type", "validation_error")),
            }
            for error in exc.errors()
        ]
        return error_response(
            "Request validation failed.",
            400,
            error_code="VALIDATION_ERROR",
            details={"validation_errors": validation_errors},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
        """Fail closed without leaking provider credentials or paper text."""
        return error_response(
            "An unexpected server error occurred.",
            500,
            error_code="INTERNAL_ERROR",
            retryable=True,
        )
