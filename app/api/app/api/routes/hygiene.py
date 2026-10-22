"""Hygiene routes: governance metrics, findings, and the documents behind each finding."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_container
from app.auth.validator import require_auditor
from app.container import Container

router = APIRouter(tags=["hygiene"], dependencies=[Depends(require_auditor)])


@router.get("/hygiene", summary="Governance hygiene metrics, findings and coverage")
def hygiene(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.hygiene.summary()


@router.get("/hygiene/findings/{findingId}", summary="All documents behind one hygiene finding")
def finding(
    finding_id: str = Path(alias="findingId", min_length=1, max_length=100),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.hygiene.finding(finding_id)
