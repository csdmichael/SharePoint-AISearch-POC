"""Owner notification routes: drafts from templates, approval, and send (dryRun records status only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_container
from app.api.schemas import NotificationDraftRequest
from app.auth.validator import Principal, require_auditor
from app.container import Container
from app.core.errors import BadRequestError

router = APIRouter(tags=["notifications"], dependencies=[Depends(require_auditor)])
NOTIFICATION_STATUSES = (
    "draft",
    "approved",
    "dryRunRecorded",
    "sent",
    "failed",
)


@router.post("/notifications/drafts", summary="Create owner notification drafts from a template")
def create_drafts(
    body: NotificationDraftRequest,
    principal: Principal = Depends(require_auditor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.notifications.create_drafts(
        template_id=body.templateId,
        finding_id=body.findingId,
        document_ids=body.documentIds,
        caller_upn=principal.upn,
    )


@router.get("/notifications", summary="List notifications, optionally by status")
def list_notifications(
    status: str | None = Query(default=None, max_length=40),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    if status is not None and status not in NOTIFICATION_STATUSES:
        raise BadRequestError(f"status must be one of {', '.join(NOTIFICATION_STATUSES)}.")
    records = container.notifications.list(status)
    return {"items": records, "total": len(records), "mode": container.settings.notifications.mode}


@router.post("/notifications/{notificationId}/approve", summary="Approve a draft so it can be sent")
def approve(
    notification_id: str = Path(alias="notificationId", min_length=1, max_length=64),
    principal: Principal = Depends(require_auditor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.notifications.approve(notification_id, principal.upn)


@router.post("/notifications/{notificationId}/send", summary="Send an approved notification (dryRun records only)")
def send(
    notification_id: str = Path(alias="notificationId", min_length=1, max_length=64),
    principal: Principal = Depends(require_auditor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.notifications.send(notification_id, principal.upn)
