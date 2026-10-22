"""Agent routes: the sample prompts and the question endpoint (evidence first, Foundry when configured)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.agent.service import Caller
from app.api.deps import get_container
from app.api.schemas import AgentMessageRequest
from app.auth.validator import Principal, require_auditor
from app.container import Container

router = APIRouter(tags=["agent"], dependencies=[Depends(require_auditor)])


@router.get("/agent/prompts", summary="Provisional sample prompts for the cleanup issues")
def prompts(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.agent.prompt_catalog()


@router.post("/agent/messages", summary="Ask a governance question; answered from live evidence")
def messages(
    body: AgentMessageRequest,
    principal: Principal = Depends(require_auditor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    return container.agent.answer(
        prompt=body.prompt,
        conversation_id=body.conversationId,
        mode=body.mode,
        caller=Caller(upn=principal.upn, name=principal.name),
    )
