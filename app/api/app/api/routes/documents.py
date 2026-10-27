"""Governance document routes: the document list read from SharePoint governance columns, and detail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container, resolve_page_size
from app.auth.validator import require_auditor
from app.container import Container
from app.domain.identity import GUID_RE

router = APIRouter(tags=["documents"], dependencies=[Depends(require_auditor)])
ITEM_PATTERN = GUID_RE.pattern.replace("$", "") + r"(\.[0-9]{1,10})?$"


@router.get("/documents", summary="Governance list of documents, filtered and paged")
def list_documents(
    lifecycle_status: str | None = Query(default=None, alias="lifecycleStatus", max_length=50),
    data_quality_status: str | None = Query(default=None, alias="dataQualityStatus", max_length=50),
    authoritative: bool | None = Query(default=None),
    knowledge_category: str | None = Query(default=None, alias="knowledgeCategory", max_length=100),
    sort: str | None = Query(default=None, max_length=50),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, alias="pageSize", ge=1),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.documents.list(
        lifecycle=lifecycle_status,
        data_quality=data_quality_status,
        authoritative=authoritative,
        category=knowledge_category,
        sort=sort or container.settings.api.api.defaultSort,
        order=order,
        page=page,
        page_size=resolve_page_size(container, page_size),
    )


@router.get("/documents/{itemId}", summary="One document with trust reasons, conflicts and duplicate status")
def document_detail(
    item_id: str = Path(alias="itemId", pattern=ITEM_PATTERN),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.documents.detail(item_id)
