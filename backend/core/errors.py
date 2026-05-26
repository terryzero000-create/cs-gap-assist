from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Domain error rendered through the unified API error shape."""

    def __init__(self, message: str, code: int = 400) -> None:
        """Create an API error with a user-facing message and HTTP code."""
        self.message = message
        self.code = code
        super().__init__(message)


def error_response(message: str, code: int = 400) -> JSONResponse:
    """Build the standard error response payload."""
    return JSONResponse(status_code=code, content={"error": message, "code": code})


def register_error_handlers(app: FastAPI) -> None:
    """Register application-wide exception handlers."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        """Render domain exceptions using the standard error shape."""
        return error_response(exc.message, exc.code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Render request validation failures as code 400 for API consistency."""
        return error_response(str(exc), 400)
