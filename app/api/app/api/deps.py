"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.container import Container
from app.core.errors import BadRequestError
from app.domain.permissions import GRANT_VALUES


def get_container(request: Request) -> Container:
    selector = request.query_params.get("site")
    manager = getattr(request.app.state, "container_manager", None)
    if manager is None:
        return request.app.state.container
    return manager.for_site(selector)


def resolve_page_size(container: Container, requested: int | None) -> int:
    limits = container.settings.api.api
    size = limits.defaultPageSize if requested is None else requested
    if size < 1 or size > limits.maxPageSize:
        raise BadRequestError(f"pageSize must be between 1 and {limits.maxPageSize}.")
    return size


def validate_granted_via(value: str | None) -> str | None:
    if value is not None and value not in GRANT_VALUES:
        raise BadRequestError(f"grantedVia must be one of {', '.join(GRANT_VALUES)}.")
    return value
