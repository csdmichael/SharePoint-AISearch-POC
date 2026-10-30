"""Demo-mode answer for the agent, used only when Microsoft Foundry is not configured and publishing is in demo mode.

It reads the artifacts the demo publisher saved locally and answers a question that clearly matches one of them. It is
a labelled stand-in so the Select -> Review -> Publish -> Ask AI story runs without Azure AI Search. It is not a search
system: with live publishing and indexing the existing Foundry IQ agent answers from the SharePoint index instead.
"""

from __future__ import annotations

import re
from typing import Any

from app.knowledge.publisher import DemoStore

TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-]{2,}")
STOP_WORDS = frozenset(
    "the and for with what which that this from why how are was were has have had can could should would "
    "does did not but you your our their about into than then also when where who whom".split()
)
MIN_MATCHES = 3
MIN_SHARE = 0.4
DEMO_NOTICE = "Demo mode: answered from the locally saved demo knowledge, not from Azure AI Search."


def _tokens(text: str) -> set[str]:
    return {token.strip(".-") for token in TOKEN.findall(text.lower())} - STOP_WORDS


def _artifact_text(record: dict[str, Any]) -> str:
    parts = [record.get("title", ""), " ".join(record.get("tags", [])), record.get("summary", ""),
             record.get("context", ""), record.get("rootCause", ""), record.get("decision", ""),
             record.get("recommendedAction", ""), " ".join(record.get("keyFacts", []))]
    return " ".join(str(part) for part in parts)


class DemoKnowledgeAnswerer:
    def __init__(self, store: DemoStore) -> None:
        self._store = store

    def __call__(self, question: str) -> dict[str, Any] | None:
        wanted = _tokens(question)
        if not wanted:
            return None
        best: tuple[int, dict[str, Any]] | None = None
        for record in self._store.all_metadata():
            if not record.get("aiReady"):
                continue
            matches = len(wanted & _tokens(_artifact_text(record)))
            if matches >= MIN_MATCHES and matches / len(wanted) >= MIN_SHARE and (best is None or matches > best[0]):
                best = (matches, record)
        if best is None:
            return None
        record = best[1]
        headline = record.get("recommendedAction") or record.get("decision") or record.get("summary") or ""
        lines = [f"**{headline}**", ""]
        why = " ".join(part for part in (record.get("rootCause"), record.get("context")) if part)
        if why:
            lines += ["### Why", why, ""]
        if record.get("keyFacts"):
            lines += ["### Key facts", *[f"- {fact}" for fact in record["keyFacts"]], ""]
        lines += [f"Source: {record['title']} (knowledge artifact {record['artifactId']}, saved in demo mode).", "", f"_{DEMO_NOTICE}_"]
        return {
            "answer": "\n".join(lines),
            "citations": [{"title": record["title"], "url": None, "path": record.get("fileName"),
                           "itemId": record["artifactId"], "library": "Knowledge Capture (demo)"}],
            "notice": DEMO_NOTICE,
        }
