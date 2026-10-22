"""Access routes: site-user search and the by-user index of reachable items."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container, resolve_page_size, validate_granted_via
from app.auth.validator import require_auditor
from app.container import Container

router = APIRouter(tags=["access"], dependencies=[Depends(require_auditor)])


@router.get("/access/users", summary="Search site users by name, UPN, email or login")
def search_users(
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=25, ge=1, le=200),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.access.search_users(query, limit)


@router.get("/access/users/{userKey}/items", summary="Every item a user can reach, with role and grant path")
def user_items(
    user_key: str = Path(alias="userKey", min_length=3, max_length=320),
    role: str | None = Query(default=None, max_length=100),
    granted_via: str | None = Query(default=None, alias="grantedVia", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, alias="pageSize", ge=1),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.access.user_items(
        user_key,
        role=role,
        granted_via=validate_granted_via(granted_via),
        page=page,
        page_size=resolve_page_size(container, page_size),
    )
