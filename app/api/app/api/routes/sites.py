"""Site routes: configured libraries, lazily loaded folder children, and item permissions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container
from app.auth.validator import require_auditor
from app.container import Container
from app.domain.identity import GUID_RE

router = APIRouter(tags=["sites"], dependencies=[Depends(require_auditor)])
GUID_PATTERN = GUID_RE.pattern
ITEM_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(\.[0-9]{1,10})?$"


@router.get("/site/libraries", summary="Configured document libraries of the site")
def libraries(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.sites.libraries()


@router.get("/site/libraries/{libraryId}/children", summary="Folders and files of one folder level (lazy tree)")
def children(
    library_id: str = Path(alias="libraryId", pattern=GUID_PATTERN),
    folder_id: str | None = Query(default=None, alias="folderId", max_length=64),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.sites.children(library_id, folder_id)


@router.get("/items/{itemId}/permissions", summary="Permission entries for a library, folder or file")
def permissions(
    item_id: str = Path(alias="itemId", pattern=ITEM_PATTERN),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.sites.permissions(item_id)
