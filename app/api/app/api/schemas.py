"""Request models for the POST endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templateId: str = Field(min_length=1, max_length=100)
    findingId: str | None = Field(default=None, min_length=1, max_length=100)
    documentIds: list[str] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "NotificationDraftRequest":
        has_finding = self.findingId is not None
        has_documents = bool(self.documentIds)
        if has_finding == has_documents:
            raise ValueError("provide exactly one of findingId or a non-empty documentIds list")
        return self


class AgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=2000)
    conversationId: str | None = Field(default=None, min_length=1, max_length=64)
    mode: Literal["auto", "evidence"] = "auto"
