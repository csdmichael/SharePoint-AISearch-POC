"""Agent orchestration: route the question, collect live evidence, then answer from the evidence or from Foundry."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from app.agent.foundry import FoundryClient
from app.agent.handlers import HANDLERS, HandlerContext
from app.agent.router import IntentRouter
from app.core.config import AgentConfig, PromptCatalog
from app.core.errors import UpstreamError

logger = logging.getLogger("sp_acl_api")
MODE_EVIDENCE = "evidence"
MODE_FOUNDRY = "foundry"
FOUNDRY_USED = "used"
FOUNDRY_NOT_CONFIGURED = "notConfigured"
FOUNDRY_UNAVAILABLE = "unavailable"
FOUNDRY_NOT_REQUESTED = "notRequested"
USER_PLACEHOLDER = "{userUpn}"


@dataclass(frozen=True)
class Caller:
    upn: str | None
    name: str | None


class AgentService:
    def __init__(
        self,
        *,
        agent: AgentConfig,
        prompts: PromptCatalog,
        router: IntentRouter,
        context_for: Callable[[Caller], HandlerContext],
        foundry: FoundryClient | None,
        demo_answer: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self._agent = agent
        self._limits = agent.limits
        self._prompts = prompts
        self._router = router
        self._context_for = context_for
        self._foundry = foundry
        self._demo_answer = demo_answer
        self._conversations: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def foundry_configured(self) -> bool:
        return self._foundry is not None

    def prompt_catalog(self) -> dict[str, Any]:
        """The prompts file as published: schemaVersion, provisional, note, placeholders and prompts."""

        return {
            "schemaVersion": self._prompts.schemaVersion,
            "provisional": self._prompts.provisional,
            "note": self._prompts.note,
            "placeholders": self._prompts.placeholders,
            "prompts": [prompt.model_dump() for prompt in self._prompts.prompts],
        }

    def answer(self, *, prompt: str, conversation_id: str | None, mode: str, caller: Caller) -> dict[str, Any]:
        messages = self._agent.messages
        question = prompt.replace(USER_PLACEHOLDER, caller.upn or messages.signedInUser)
        routed = self._router.route(question)
        context = self._context_for(caller)
        evidence_body = HANDLERS[routed.handler](context, question)
        evidence = {
            "intent": routed.id,
            "handler": routed.handler,
            "matchedKeywords": list(routed.matched),
            "fallback": routed.fallback,
            "asOfDate": context.analytics.as_of().isoformat(),
            "lines": evidence_body["lines"],
            "facts": evidence_body["facts"],
            "items": evidence_body["items"],
        }
        citations = evidence_body["citations"]
        answer_text = "\n".join(evidence_body["lines"])
        answer_mode = MODE_EVIDENCE
        warnings: list[str] = []
        if mode != "auto":
            foundry = {"status": FOUNDRY_NOT_REQUESTED, "message": messages.foundryNotRequested}
        elif self._foundry is None:
            foundry = {"status": FOUNDRY_NOT_CONFIGURED, "message": messages.foundryNotConfigured}
        else:
            try:
                answer_text = self._foundry.respond(self._grounded_input(question, evidence))
                answer_mode = MODE_FOUNDRY
                foundry = {"status": FOUNDRY_USED, "message": None}
            except UpstreamError as exc:
                message = messages.foundryUnavailable.format(reason=exc.message)
                warnings.append(message)
                foundry = {"status": FOUNDRY_UNAVAILABLE, "message": message}
            except Exception:  # Foundry is an optional enrichment: no failure here may turn the answer into a 500
                logger.exception("Microsoft Foundry call failed unexpectedly")
                warnings.append(messages.foundryUnexpected)
                foundry = {"status": FOUNDRY_UNAVAILABLE, "message": messages.foundryUnexpected}
        if routed.fallback and self._demo_answer is not None:
            demo = self._demo_answer(question)
            if demo is not None:
                answer_text, citations, answer_mode = demo["answer"], demo["citations"], MODE_EVIDENCE
                warnings.append(demo["notice"])
        conversation = conversation_id or uuid.uuid4().hex
        self._remember(conversation, question, routed.id, answer_mode)
        return {
            "conversationId": conversation,
            "answer": answer_text,
            "mode": answer_mode,
            "intent": routed.id,
            "foundry": {"configured": self._foundry is not None, **foundry},
            "evidence": evidence,
            "citations": citations,
            "warnings": warnings,
        }

    def _grounded_input(self, question: str, evidence: dict[str, Any]) -> str:
        if evidence["fallback"]:
            return f"{self._agent.instructions}\n\n{self._agent.contentQuestionInstruction}\n\nQuestion: {question}"
        body = json.dumps(evidence, default=str, ensure_ascii=False)
        if len(body) > self._limits.maxEvidenceChars:
            body = body[: self._limits.maxEvidenceChars] + " ...(evidence truncated)"
        knowledge = f"{self._agent.knowledgeBaseInstruction}\n" if evidence["intent"] in self._agent.knowledgeBaseIntents else ""
        return (
            f"{self._agent.instructions}\n\n"
            f"Question: {question}\n"
            f"Intent: {evidence['intent']}\n"
            f"{knowledge}\n"
            f"Live evidence (JSON, read from SharePoint and Microsoft Graph):\n{body}"
        )

    def _remember(self, conversation: str, question: str, intent: str, mode: str) -> None:
        with self._lock:
            turns = self._conversations.pop(conversation, [])
            turns.append({"question": question, "intent": intent, "mode": mode})
            self._conversations[conversation] = turns[-self._limits.maxTurnsPerConversation:]
            while len(self._conversations) > self._limits.maxConversations:
                self._conversations.popitem(last=False)
