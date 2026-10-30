"""Adaptive Cards and request mapping for the Teams (Power Automate) flow.

The flow stays thin: it posts the selected message to /knowledge/teams/draft, shows the returned card with "Post
adaptive card and wait for a response", and sends the submitted values to /knowledge/teams/publish. The review card
lets the user edit every field; nothing is written to SharePoint until the user selects Publish.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.models import (
    ORIGIN_AI,
    ORIGIN_DEFAULT,
    ORIGIN_SOURCE,
    ORIGIN_UNKNOWN,
    KnowledgeDraft,
    PublishRequest,
    PublishResult,
)

CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
CARD_VERSION = "1.4"
ACTION_PUBLISH = "publish"
ACTION_CANCEL = "cancel"
ORIGIN_LABELS = {
    ORIGIN_SOURCE: "from the message",
    ORIGIN_AI: "AI suggested",
    ORIGIN_DEFAULT: "default, please confirm",
    ORIGIN_UNKNOWN: "not stated, please complete",
}
STAGE_LABELS = {
    "notReady": "Not AI-ready",
    "published": "Published to SharePoint",
    "indexing": "Indexing...",
    "available": "Available to AI",
    "delayed": "Indexing is delayed",
    "failed": "Indexing failed",
}


class TeamsDraftRequest(BaseModel):
    """The trigger outputs of the 'For a selected message' flow."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    messageText: str = Field(min_length=1, max_length=8000)
    senderName: str = Field(default="Unknown sender", min_length=1, max_length=120)
    senderRole: str | None = Field(default=None, max_length=120)
    messageId: str = Field(default="teams-message", min_length=1, max_length=64)
    messageLink: str | None = Field(default=None, max_length=2000)
    postedAt: str | None = Field(default=None, max_length=40)
    chatTopic: str | None = Field(default=None, max_length=300)


class TeamsSubmission(BaseModel):
    """What 'Post adaptive card and wait for a response' returns in data: the card inputs plus the hidden carry values."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    action: str = ACTION_PUBLISH
    title: str = ""
    executiveSummary: str = ""
    category: str = ""
    issueContext: str = ""
    rootCause: str = ""
    decision: str = ""
    recommendedAction: str = ""
    keyFacts: str = ""
    department: str = ""
    product: str = ""
    ownerUpn: str = ""
    ownerName: str = ""
    sourceType: str = ""
    sourceDescription: str = ""
    sensitivity: str = ""
    reviewDate: str = ""
    tags: str = ""
    confidence: str = "0"
    extractionProvider: str = "manual"
    selectedMessageCount: str = "1"
    authoritative: str = "true"
    attested: str = "false"

    def to_publish_request(self) -> PublishRequest:
        def number(text: str, cast: Any, default: Any) -> Any:
            try:
                return cast(text)
            except ValueError:
                return default

        return PublishRequest(
            title=self.title, executiveSummary=self.executiveSummary, category=self.category,
            issueContext=self.issueContext, rootCause=self.rootCause, decision=self.decision,
            recommendedAction=self.recommendedAction,
            keyFacts=[line for line in re.split(r"[\r\n]+", self.keyFacts)],
            department=self.department, product=self.product, ownerName=self.ownerName, ownerUpn=self.ownerUpn,
            sourceType=self.sourceType, sourceDescription=self.sourceDescription, sensitivity=self.sensitivity,
            reviewDate=self.reviewDate,
            tags=[tag for tag in re.split(r"[;,]", self.tags)],
            confidence=min(1.0, max(0.0, number(self.confidence, float, 0.0))),
            extractionProvider=self.extractionProvider or "manual",
            selectedMessageCount=number(self.selectedMessageCount, int, 1),
            authoritative=self.authoritative.lower() == "true",
            attested=self.attested.lower() == "true",
        )


def _text(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "TextBlock", "text": text, "wrap": True, **extra}


def _label(name: str, draft: KnowledgeDraft) -> str:
    origin = draft.origins.get(name, ORIGIN_UNKNOWN)
    return f"{name_to_label(name)} ({ORIGIN_LABELS[origin]})"


def name_to_label(name: str) -> str:
    return {
        "executiveSummary": "Executive summary", "issueContext": "Issue / context", "rootCause": "Root cause",
        "recommendedAction": "Recommended action", "keyFacts": "Key facts (one per line)", "reviewDate": "Review date",
        "sourceDescription": "Source description", "owner": "Knowledge owner (email)",
        "tags": "Tags (comma separated)",
    }.get(name, name[:1].upper() + name[1:])


def _input_text(name: str, draft: KnowledgeDraft, value: str, *, multiline: bool = False, required: bool = False) -> dict[str, Any]:
    element: dict[str, Any] = {
        "type": "Input.Text", "id": name, "label": _label("owner" if name == "ownerUpn" else name, draft),
        "value": value, "isMultiline": multiline, "maxLength": 4000 if multiline else 300,
    }
    if required:
        element["isRequired"] = True
        element["errorMessage"] = "Required"
    return element


def _choice_set(name: str, draft: KnowledgeDraft, value: str, options: list[str], *, required: bool = True) -> dict[str, Any]:
    choices = list(dict.fromkeys([*options, *([value] if value else [])]))
    element: dict[str, Any] = {
        "type": "Input.ChoiceSet", "id": name, "label": _label(name, draft), "style": "compact", "value": value,
        "choices": [{"title": option, "value": option} for option in choices],
    }
    if required:
        element["isRequired"] = True
        element["errorMessage"] = "Required"
    return element


def review_card(
    draft: KnowledgeDraft,
    *,
    categories: list[str],
    departments: list[str],
    sensitivities: list[str],
    provider_label: str,
    demo: bool,
    warnings: list[str],
    message_link: str | None,
    selected_count: int = 1,
) -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        _text("Promote to Knowledge", size="Large", weight="Bolder"),
        _text("Review and edit before publishing. Nothing is saved until you select Publish to SharePoint.", isSubtle=True),
        {
            "type": "Container", "style": "emphasis", "items": [
                _text("AI detected", weight="Bolder"),
                {"type": "FactSet", "facts": [
                    {"title": "Type", "value": draft.category or "Not determined"},
                    {"title": "Title", "value": draft.title or "Not determined"},
                    {"title": "Department", "value": draft.department or "Not stated"},
                    {"title": "Source", "value": "Teams collaboration"},
                    {"title": "Status", "value": draft.status},
                ]},
            ],
        },
    ]
    if demo:
        body.append(_text(f"Extraction: {provider_label}", isSubtle=True, color="Warning"))
    body += [_text(warning, color="Attention") for warning in warnings]
    body += [
        _input_text("title", draft, draft.title, required=True),
        _input_text("executiveSummary", draft, draft.executiveSummary, multiline=True, required=True),
        _choice_set("category", draft, draft.category, categories),
        _input_text("issueContext", draft, draft.issueContext, multiline=True),
        _input_text("rootCause", draft, draft.rootCause, multiline=True),
        _input_text("decision", draft, draft.decision, multiline=True),
        _input_text("recommendedAction", draft, draft.recommendedAction, multiline=True),
        _input_text("keyFacts", draft, "\n".join(draft.keyFacts), multiline=True),
        _choice_set("department", draft, draft.department, departments, required=False),
        _input_text("product", draft, draft.product),
        _input_text("ownerUpn", draft, draft.ownerUpn, required=True),
    ]
    if draft.ownerMention:
        body.append(_text(f"Mentioned in the message: {draft.ownerMention}", isSubtle=True, size="Small"))
    body += [
        _choice_set("sensitivity", draft, draft.sensitivity, sensitivities),
        {"type": "Input.Date", "id": "reviewDate", "label": _label("reviewDate", draft), "value": draft.reviewDate,
         "isRequired": True, "errorMessage": "Required"},
        _input_text("tags", draft, ", ".join(draft.tags)),
        {"type": "Input.Toggle", "id": "authoritative", "title": "Mark as authoritative (I am accountable for it)",
         "value": "true", "valueOn": "true", "valueOff": "false"},
        {"type": "Input.Toggle", "id": "attested",
         "title": "I reviewed this content and approve publishing it to SharePoint",
         "value": "false", "valueOn": "true", "valueOff": "false", "isRequired": True,
         "errorMessage": "Confirm before publishing"},
        _text("Only this summary is stored. The Teams conversation is not archived.", isSubtle=True, size="Small"),
    ]
    carry = {
        "confidence": str(draft.confidence), "extractionProvider": "demo" if demo else "foundry",
        "selectedMessageCount": str(selected_count), "sourceType": draft.sourceType,
        "sourceDescription": draft.sourceDescription, "ownerName": draft.ownerName,
    }
    actions: list[dict[str, Any]] = [
        {"type": "Action.Submit", "title": "Publish to SharePoint", "style": "positive",
         "data": {"action": ACTION_PUBLISH, **carry}},
        {"type": "Action.Submit", "title": "Cancel", "associatedInputs": "none", "data": {"action": ACTION_CANCEL}},
    ]
    if message_link:
        actions.append({"type": "Action.OpenUrl", "title": "Open source message", "url": message_link})
    return {"type": "AdaptiveCard", "$schema": CARD_SCHEMA, "version": CARD_VERSION, "body": body, "actions": actions}


def message_card(title: str, text: str, *, attention: bool = False) -> dict[str, Any]:
    return {
        "type": "AdaptiveCard", "$schema": CARD_SCHEMA, "version": CARD_VERSION,
        "body": [_text(title, size="Medium", weight="Bolder", color="Attention" if attention else "Default"), _text(text)],
    }


def success_card(result: PublishResult, *, web_app_url: str | None) -> dict[str, Any]:
    location = f"{result.location.siteName} / {result.location.libraryName} / {result.location.folder}"
    facts = [
        {"title": "Title", "value": result.title},
        {"title": "SharePoint location", "value": location},
        {"title": "Category", "value": result.category},
        {"title": "Owner", "value": result.ownerName},
        {"title": "Published", "value": result.publishedAt[:10]},
        {"title": "Review date", "value": result.reviewDate},
        {"title": "Lifecycle status", "value": result.lifecycleStatus},
        {"title": "AI", "value": STAGE_LABELS.get(result.indexing.stage, result.indexing.stage)},
    ]
    body: list[dict[str, Any]] = [
        _text("Knowledge preserved", size="Large", weight="Bolder", color="Good"),
        {"type": "FactSet", "facts": facts},
        _text(result.indexing.message, isSubtle=True),
    ]
    body += [_text(blocker, color="Attention") for blocker in result.aiReadyBlockers]
    body += [_text(warning, isSubtle=True, size="Small") for warning in result.warnings]
    actions: list[dict[str, Any]] = []
    if result.location.webUrl:
        actions.append({"type": "Action.OpenUrl", "title": "Open in SharePoint", "url": result.location.webUrl})
    if web_app_url:
        prompt = f'What does the knowledge document "{result.title}" recommend and why?'
        actions.append({"type": "Action.OpenUrl", "title": "Ask AI about this",
                        "url": f"{web_app_url.rstrip('/')}/agent?prompt={quote(prompt)}"})
    card: dict[str, Any] = {"type": "AdaptiveCard", "$schema": CARD_SCHEMA, "version": CARD_VERSION, "body": body}
    if actions:
        card["actions"] = actions
    return card
