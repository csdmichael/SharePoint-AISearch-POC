"""JSON views shared by the services. Every endpoint serializes items, containers and documents through here."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.domain.identity import web_url
from app.domain.permissions import PermissionEntry, entry_json
from app.domain.snapshot import ItemRecord
from app.services.corpus import LibraryCorpus


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def item_view(corpus: LibraryCorpus, item: ItemRecord) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "libraryId": corpus.library.id,
        "libraryTitle": corpus.library.title,
        "name": item.name,
        "kind": item.kind,
        "path": item.path,
        "webUrl": corpus.web_url(item.path),
        "hasUniquePermissions": item.unique,
        "modified": iso(item.modified),
    }


def library_view(corpus: LibraryCorpus, origin: str) -> dict[str, Any]:
    return {
        "id": corpus.library.id,
        "libraryId": corpus.library.id,
        "libraryTitle": corpus.library.title,
        "name": corpus.library.title,
        "kind": "library",
        "path": corpus.library.root_path,
        "webUrl": web_url(origin, corpus.library.root_path),
        "hasUniquePermissions": corpus.library.unique,
        "modified": None,
    }


def site_view(name: str, path: str, origin: str, unique: bool) -> dict[str, Any]:
    return {
        "id": "site",
        "libraryId": None,
        "libraryTitle": None,
        "name": name,
        "kind": "site",
        "path": path,
        "webUrl": web_url(origin, path),
        "hasUniquePermissions": unique,
        "modified": None,
    }


def document_ref(corpus: LibraryCorpus, item: ItemRecord) -> dict[str, Any]:
    fields = item.fields
    owner = fields.get("knowledgeOwner") or {}
    return {
        "id": item.item_id,
        "libraryId": corpus.library.id,
        "libraryTitle": corpus.library.title,
        "name": item.name,
        "title": fields.get("title") or item.name,
        "artifactId": fields.get("artifactId"),
        "path": item.path,
        "webUrl": corpus.web_url(item.path),
        "lifecycleStatus": fields.get("lifecycleStatus"),
        "authoritative": fields.get("authoritative"),
        "knowledgeOwner": owner.get("upn"),
        "reviewDate": iso(fields.get("reviewDate")),
        "expirationDate": iso(fields.get("expirationDate")),
    }


def entry_view(entry: PermissionEntry, members: list[dict[str, Any]], account: dict[str, Any] | None) -> dict[str, Any]:
    view = entry_json(entry)
    view["expandedMembers"] = members
    view["accountEnabled"] = account["accountEnabled"] if account else None
    view["accountStatus"] = account["status"] if account else None
    return view
