"""Governance column parsing. Reads SharePoint columns through the vocabulary's logical keys."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping

from app.core.governance import Governance

_LIST_SPLIT = re.compile(r"[;,]\s*")
_OWNER_CLAIM_PREFIX = "|"


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _lines(value: Any) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in re.split(r"[\r\n]+", str(value)) if line.strip()]


def _names(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in _LIST_SPLIT.split(str(value)) if part.strip()]


def owner_from_person(value: Any) -> dict[str, str | None]:
    """Person-field values arrive as {Title, EMail, Name}; Name is a claim such as 'i:0#.f|membership|upn'."""

    if isinstance(value, Mapping):
        name = str(value.get("Name") or "")
        email = _text(value.get("EMail"))
        upn = name.split(_OWNER_CLAIM_PREFIX)[-1].strip().lower() if _OWNER_CLAIM_PREFIX in name else None
        if not upn and email:
            upn = email.lower()
        if upn and "@" not in upn:
            upn = None
        return {"upn": upn, "email": email, "displayName": _text(value.get("Title"))}
    text = _text(value)
    if text and "@" in text:
        return {"upn": text.lower(), "email": text, "displayName": None}
    return {"upn": None, "email": None, "displayName": None}


def parse_governance(row: Mapping[str, Any], governance: Governance) -> dict[str, Any]:
    columns = governance.column_names()

    def raw(key: str) -> Any:
        return row.get(columns[key])

    return {
        "title": _text(raw("title")),
        "fileName": _text(raw("fileName")),
        "artifactId": _text(raw("artifactId")),
        "knowledgeCategory": _text(raw("knowledgeCategory")),
        "sourceSystem": _text(raw("sourceSystem")),
        "lifecycleStatus": _text(raw("lifecycleStatus")),
        "documentIteration": _text(raw("documentIteration")),
        "authoritative": _bool(raw("authoritative")),
        "reviewDate": parse_date(raw("reviewDate")),
        "expirationDate": parse_date(raw("expirationDate")),
        "effectiveDate": parse_date(raw("effectiveDate")),
        "documentType": _text(raw("documentType")),
        "productFamily": _text(raw("productFamily")),
        "processArea": _text(raw("processArea")),
        "sensitivity": _text(raw("sensitivity")),
        "businessUnit": _text(raw("businessUnit")),
        "supersedesDocument": _text(raw("supersedesDocument")),
        "aiReady": _bool(raw("aiReady")),
        "trustScore": _int(raw("trustScore")),
        "dataQualityStatus": _text(raw("dataQualityStatus")),
        "conflictStatus": _text(raw("conflictStatus")),
        "conflictWith": _names(raw("conflictWith")),
        "duplicateOf": _text(raw("duplicateOf")),
        "contentHash": _text(raw("contentHash")),
        "trustReasons": _lines(raw("trustReasons")),
        "lastValidatedDate": parse_date(raw("lastValidatedDate")),
        "ownerDisplayName": _text(raw("ownerDisplayName")),
        "knowledgeOwner": owner_from_person(raw("knowledgeOwner")),
    }


def governance_select(governance: Governance) -> tuple[list[str], list[str]]:
    """SharePoint $select and $expand fragments for the governance columns."""

    select: list[str] = []
    for key, column in governance.column_names().items():
        if key == "knowledgeOwner":
            select.extend([f"{column}/Title", f"{column}/EMail", f"{column}/Name"])
        else:
            select.append(column)
    expand = [governance.column("knowledgeOwner")]
    return sorted(set(select)), expand


def authoritative_claim(governance_fields: Mapping[str, Any], governance: Governance) -> bool:
    lifecycle_key = governance.key_for_label("lifecycleStatus", governance_fields.get("lifecycleStatus"))
    return lifecycle_key == governance.authoritative_lifecycle_key and bool(governance_fields.get("authoritative"))
