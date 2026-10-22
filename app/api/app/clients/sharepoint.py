"""SharePoint REST client. Read-only: libraries, items, role assignments, site groups and site users."""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping
from urllib.parse import quote, urlsplit

from app.clients.transport import TokenProvider, UpstreamHttp, check_response
from app.core.errors import BadRequestError, UpstreamError

JSON_LIGHT = {"Accept": "application/json;odata=nometadata"}
NEXT_LINK_KEYS: tuple[str, ...] = ("odata.nextLink", "@odata.nextLink", "__next")
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DOCUMENT_LIBRARY_TEMPLATE = 101
ROLE_EXPAND = "Member,RoleDefinitionBindings"
USER_SELECT = "Id,Title,LoginName,Email,UserPrincipalName,PrincipalType"


def guid_literal(value: str) -> str:
    if not GUID_RE.match(value or ""):
        raise BadRequestError("The identifier must be a GUID.")
    return f"guid'{value.lower()}'"


def odata_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def path_literal(server_relative_path: str) -> str:
    return quote(odata_string(server_relative_path), safe="/'()")


class SharePointClient:
    service = "SharePoint"

    def __init__(self, site_url: str, *, http: UpstreamHttp, tokens: TokenProvider, page_size: int) -> None:
        self._site_url = site_url.rstrip("/")
        self._origin = urlsplit(self._site_url).netloc.lower()
        self._api = f"{self._site_url}/_api"
        self._http = http
        self._tokens = tokens
        self._page_size = page_size

    def _get(self, url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response = self._http.request("GET", url, tokens=self._tokens, headers=JSON_LIGHT, params=params)
        check_response(self.service, response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamError(self.service, "returned an unexpected payload")
        return payload

    def _next_link(self, payload: Mapping[str, Any]) -> str | None:
        for key in NEXT_LINK_KEYS:
            value = payload.get(key)
            if value:
                if urlsplit(str(value)).netloc.lower() != self._origin:
                    raise UpstreamError(self.service, "a paging link pointed at another host and was refused")
                return str(value)
        return None

    def _pages(self, url: str, params: Mapping[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        next_params: dict[str, Any] | None = dict(params or {})
        next_params.setdefault("$top", self._page_size)
        while next_url:
            payload = self._get(next_url, next_params)
            for row in payload.get("value", []):
                if isinstance(row, dict):
                    yield row
            next_url = self._next_link(payload)
            next_params = None

    @staticmethod
    def list_path(list_id: str) -> str:
        return f"web/lists({guid_literal(list_id)})"

    def web(self) -> dict[str, Any]:
        return self._get(f"{self._api}/web", {"$select": "Id,Title,Url,ServerRelativeUrl,HasUniqueRoleAssignments"})

    def libraries(self) -> Iterator[dict[str, Any]]:
        return self._pages(
            f"{self._api}/web/lists",
            {
                "$filter": f"BaseTemplate eq {DOCUMENT_LIBRARY_TEMPLATE} and Hidden eq false",
                "$select": "Id,Title,HasUniqueRoleAssignments,RootFolder/ServerRelativeUrl",
                "$expand": "RootFolder",
            },
        )

    def library(self, list_id: str) -> dict[str, Any]:
        return self._get(
            f"{self._api}/{self.list_path(list_id)}",
            {"$select": "Id,Title,HasUniqueRoleAssignments,RootFolder/ServerRelativeUrl", "$expand": "RootFolder"},
        )

    def list_items(
        self,
        list_id: str,
        *,
        select: list[str],
        expand: list[str],
        filter_text: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        params: dict[str, Any] = {"$select": ",".join(select), "$expand": ",".join(expand)}
        if filter_text:
            params["$filter"] = filter_text
        return self._pages(f"{self._api}/{self.list_path(list_id)}/items", params)

    def item(self, list_id: str, item_id: int, *, select: list[str], expand: list[str]) -> dict[str, Any]:
        params = {"$select": ",".join(select), "$expand": ",".join(expand)}
        return self._get(f"{self._api}/{self.list_path(list_id)}/items({int(item_id)})", params)

    def folder_item(self, server_relative_path: str, *, select: list[str], expand: list[str]) -> dict[str, Any]:
        url = f"{self._api}/web/GetFolderByServerRelativeUrl({path_literal(server_relative_path)})/ListItemAllFields"
        return self._get(url, {"$select": ",".join(select), "$expand": ",".join(expand)})

    def role_assignments(self, resource_path: str) -> list[dict[str, Any]]:
        """resource_path is 'web', a list path from list_path(), or a list path plus '/items(n)'."""

        return list(self._pages(f"{self._api}/{resource_path}/roleassignments", {"$expand": ROLE_EXPAND}))

    def group_users(self, group_id: int) -> Iterator[dict[str, Any]]:
        return self._pages(
            f"{self._api}/web/sitegroups/getbyid({int(group_id)})/users",
            {"$select": "Id,LoginName,Title,Email,PrincipalType,UserPrincipalName"},
        )

    def site_users(self) -> Iterator[dict[str, Any]]:
        return self._pages(f"{self._api}/web/siteusers", {"$select": USER_SELECT})
