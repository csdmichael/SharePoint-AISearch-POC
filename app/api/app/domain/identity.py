"""Identifiers and path helpers shared by the SharePoint, Graph and API layers.

An item id is '<libraryGuid>.<listItemId>' for files and folders, and the bare library GUID for a library.
Paths are SharePoint server-relative paths such as /sites/<site>/Shared Documents/<library>/<folder>/<file>.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from app.core.errors import BadRequestError

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ITEM_ID_RE = re.compile(r"^(?P<library>[0-9a-fA-F-]{36})(?:\.(?P<item>[0-9]{1,10}))?$")
SITE_ITEM_ID = "site"


def normalize_guid(value: str) -> str:
    if not GUID_RE.match(value or ""):
        raise BadRequestError("The identifier must be a GUID.")
    return value.lower()


def compose_item_id(library_id: str, list_item_id: int) -> str:
    return f"{library_id.lower()}.{int(list_item_id)}"


def split_item_id(item_id: str) -> tuple[str, int | None]:
    """Returns (libraryId, listItemId or None for a library)."""

    match = ITEM_ID_RE.match(item_id or "")
    if not match:
        raise BadRequestError(f"'{item_id}' is not a valid item identifier.")
    library = match.group("library").lower()
    if not GUID_RE.match(library):
        raise BadRequestError(f"'{item_id}' is not a valid item identifier.")
    raw_item = match.group("item")
    return library, (int(raw_item) if raw_item is not None else None)


def lower_key(path: str) -> str:
    return (path or "").rstrip("/").lower()


def parent_path(path: str) -> str:
    head, _, _ = (path or "").rstrip("/").rpartition("/")
    return head


def is_within(path: str, root: str) -> bool:
    current = lower_key(path)
    base = lower_key(root)
    return current == base or current.startswith(base + "/")


def path_depth(path: str, root: str) -> int:
    current = lower_key(path)
    base = lower_key(root)
    relative = current[len(base):].strip("/") if current.startswith(base) else current
    return 0 if not relative else relative.count("/") + 1


def is_system_path(path: str, root: str, system_names: tuple[str, ...]) -> bool:
    if not is_within(path, root):
        return False
    relative = lower_key(path)[len(lower_key(root)):].strip("/")
    first = relative.split("/", 1)[0]
    return first in {name.lower() for name in system_names}


def web_url(origin: str, server_relative_path: str) -> str:
    return f"{origin.rstrip('/')}{quote(server_relative_path, safe='/')}"


def file_extension(name: str) -> str:
    dot = (name or "").rfind(".")
    return name[dot:].lower() if dot >= 0 else ""
