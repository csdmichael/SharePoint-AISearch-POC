"""Save to Knowledge routes. Same bearer-token authentication and Auditor role as every other route.

The service is always the one of the configured publish site, so one API host can serve every hub while knowledge is
written to a single configured library.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.agent.service import Caller
from app.auth.validator import Principal, require_auditor
from app.knowledge.models import ExtractRequest, ExtractResponse, IndexingStatus, KnowledgeDraft, PublishRequest, PublishResult
from app.knowledge.service import KnowledgeService
from app.knowledge.teams import (
    ACTION_CANCEL,
    TeamsDraftRequest,
    TeamsSubmission,
    message_card,
    review_card,
    success_card,
)
from app.knowledge.models import ChatMessageIn

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(require_auditor)])


def get_knowledge(request: Request) -> KnowledgeService:
    manager = request.app.state.container_manager
    site_id = manager.default_container.settings.knowledge.publish.siteId
    return manager.for_site(site_id).knowledge


def caller_of(principal: Principal) -> Caller:
    return Caller(upn=principal.upn, name=principal.name)


@router.get("/config", summary="Taxonomy, demo conversation and how this deployment publishes")
def config(principal: Principal = Depends(require_auditor), service: KnowledgeService = Depends(get_knowledge)) -> dict[str, Any]:
    return service.public_config(caller_of(principal))


@router.post("/extract", summary="Turn the selected messages into an editable knowledge draft", response_model=ExtractResponse)
def extract(
    body: ExtractRequest,
    principal: Principal = Depends(require_auditor),
    service: KnowledgeService = Depends(get_knowledge),
) -> ExtractResponse:
    return service.extract(body, caller_of(principal))


@router.get("/draft/blank", summary="An empty draft for manual entry when AI extraction is unavailable", response_model=KnowledgeDraft)
def blank_draft(principal: Principal = Depends(require_auditor), service: KnowledgeService = Depends(get_knowledge)) -> KnowledgeDraft:
    service.ensure_enabled()
    return service.blank_draft(caller_of(principal))


@router.post("/publish", summary="Publish the reviewed draft to SharePoint", response_model=PublishResult)
def publish(
    body: PublishRequest,
    principal: Principal = Depends(require_auditor),
    service: KnowledgeService = Depends(get_knowledge),
) -> PublishResult:
    return service.publish(body, caller_of(principal))


@router.get("/artifacts/{artifact_id}/indexing", summary="Published, indexing or available to AI", response_model=IndexingStatus)
def indexing_status(
    artifact_id: str,
    publishedAt: str | None = Query(default=None, max_length=40),
    aiReady: bool | None = None,
    service: KnowledgeService = Depends(get_knowledge),
) -> IndexingStatus:
    return service.indexing_status(artifact_id, publishedAt, aiReady)


@router.post("/artifacts/{artifact_id}/indexing", summary="Start the SharePoint indexer now", response_model=IndexingStatus)
def trigger_indexing(
    artifact_id: str,
    publishedAt: str | None = Query(default=None, max_length=40),
    aiReady: bool | None = None,
    service: KnowledgeService = Depends(get_knowledge),
) -> IndexingStatus:
    return service.trigger_indexing(artifact_id, publishedAt, aiReady)


@router.get("/artifacts/{artifact_id}/document", summary="Download the generated document (demo publishing only)")
def demo_document(artifact_id: str, service: KnowledgeService = Depends(get_knowledge)) -> Response:
    name, content = service.demo_document(artifact_id)
    return Response(content=content, media_type=DOCX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{name.encode("ascii", "ignore").decode() or "knowledge.docx"}"'})


@router.post("/teams/draft", summary="Teams flow: draft from the selected message, with the review Adaptive Card")
def teams_draft(
    body: TeamsDraftRequest,
    principal: Principal = Depends(require_auditor),
    service: KnowledgeService = Depends(get_knowledge),
) -> dict[str, Any]:
    description = f"Teams chat message from {body.senderName}" + (f" in '{body.chatTopic}'" if body.chatTopic else "")
    extracted = service.extract(
        ExtractRequest(
            sourceDescription=description,
            messages=[ChatMessageIn(id=body.messageId, author=body.senderName, role=body.senderRole,
                                    text=body.messageText, postedAt=body.postedAt)],
        ),
        caller_of(principal),
    )
    taxonomy = service.config.taxonomy
    card = review_card(
        extracted.draft, categories=taxonomy.categories, departments=taxonomy.departments,
        sensitivities=service.sensitivities, provider_label=extracted.providerLabel, demo=extracted.demo,
        warnings=extracted.warnings, message_link=body.messageLink,
    )
    return {"card": card, "draft": extracted.draft.model_dump(), "provider": extracted.provider,
            "providerLabel": extracted.providerLabel, "demo": extracted.demo, "warnings": extracted.warnings}


@router.post("/teams/publish", summary="Teams flow: publish the values submitted from the review Adaptive Card")
def teams_publish(
    body: TeamsSubmission,
    principal: Principal = Depends(require_auditor),
    service: KnowledgeService = Depends(get_knowledge),
) -> dict[str, Any]:
    service.ensure_enabled()
    if body.action == ACTION_CANCEL:
        return {"status": "cancelled", "summary": "Save to Knowledge was cancelled. Nothing was saved.",
                "card": message_card("Cancelled", "Nothing was saved to SharePoint.")}
    result = service.publish(body.to_publish_request(), caller_of(principal))
    web_app_url = service.config.teams.webAppUrl
    return {
        "status": "published",
        "summary": f"Knowledge preserved: {result.title} ({result.artifactId}). {result.indexing.message}",
        "result": result.model_dump(),
        "card": success_card(result, web_app_url=web_app_url),
    }
