import re

import httpx


def safe_exception_message(exc: Exception) -> str:
    """Return diagnostic context without URLs, credentials, or source text."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    if isinstance(exc, httpx.RequestError):
        return type(exc).__name__
    message = str(exc)
    message = re.sub(r"https?://\S+", "[redacted-url]", message)
    message = re.sub(
        r"(?i)(api[_-]?key|authorization|token|secret)=\S+",
        r"\1=[redacted]",
        message,
    )
    return message[:500]
