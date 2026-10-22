"""Error types. Every failure leaves the API as {"error": {"code", "message"}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.headers: dict[str, str] = dict(headers or {})

    def envelope(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


class BadRequestError(ApiError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(ApiError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    code = "forbidden"


class NotFoundError(ApiError):
    status_code = 404
    code = "not_found"


class ConflictError(ApiError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(ApiError):
    status_code = 422
    code = "validation_error"


class UpstreamError(ApiError):
    """A SharePoint, Graph or Foundry call failed. The message names the service, never a token."""

    status_code = 502
    code = "upstream_error"

    def __init__(
        self,
        service: str,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{service}: {message}", code=code, status_code=status_code, headers=headers)
        self.service = service


class UpstreamNotFoundError(UpstreamError):
    """An upstream resource does not exist. Services translate it into a domain-specific 404."""

    status_code = 404
    code = "not_found"
