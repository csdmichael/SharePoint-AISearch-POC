"""Keyword intent routing. Keywords and handler names come from config\\agent.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.core.config import IntentConfig


@dataclass(frozen=True)
class RoutedIntent:
    id: str
    handler: str
    score: int
    matched: tuple[str, ...]
    fallback: bool


class IntentRouter:
    def __init__(self, intents: Sequence[IntentConfig], fallback_id: str) -> None:
        self._intents = list(intents)
        self._by_id = {intent.id: intent for intent in self._intents}
        self._fallback_id = fallback_id

    def route(self, prompt: str) -> RoutedIntent:
        """The intent with the most keywords present in the prompt wins; ties go to the earlier intent in config."""

        text = prompt.lower()
        best: RoutedIntent | None = None
        for intent in self._intents:
            matched = tuple(keyword for keyword in intent.keywords if keyword.lower() in text)
            if matched and (best is None or len(matched) > best.score):
                best = RoutedIntent(intent.id, intent.handler, len(matched), matched, fallback=False)
        if best is not None:
            return best
        fallback = self._by_id[self._fallback_id]
        return RoutedIntent(fallback.id, fallback.handler, 0, (), fallback=True)
