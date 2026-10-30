"""Microsoft Graph client (v1.0). Used for sharing links, drive items, file content, users, groups and sendMail."""

from __future__ import annotations

from typing import Any, Iterator, Mapping
from urllib.parse import quote, urlsplit

from app.clients.transport import TokenProvider, UpstreamHttp, check_response, upstream_detail
from app.core.errors import UpstreamError


class GraphClient:
    service = "Microsoft Graph"

    def __init__(self, base_url: str, *, http: UpstreamHttp, tokens: TokenProvider, page_size: int) -> None:
        self._base = base_url.rstrip("/")
        self._origin = urlsplit(self._base).netloc.lower()
        self._http = http
        self._tokens = tokens
        self._page_size = page_size

    def _get(self, url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        response = self._http.request("GET", url, tokens=self._tokens, params=params)
        check_response(self.service, response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise UpstreamError(self.service, "returned an unexpected payload")
        return payload

    def _pages(self, url: str, params: Mapping[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        next_params: dict[str, Any] | None = dict(params or {})
        next_params.setdefault("$top", self._page_size)
        while next_url:
            payload = self._get(next_url, next_params)
            for row in payload.get("value", []):
                if isinstance(row, dict):
                    yield row
            next_url = payload.get("@odata.nextLink")
            if next_url and urlsplit(str(next_url)).netloc.lower() != self._origin:
                raise UpstreamError(self.service, "a paging link pointed at another host and was refused")
            next_params = None

    def site(self, host: str, server_relative_path: str) -> dict[str, Any]:
        return self._get(
            f"{self._base}/sites/{quote(host, safe='')}:{quote(server_relative_path, safe='/')}",
            {"$select": "id,displayName,webUrl"},
        )

    def library_drive(self, site_id: str, list_id: str) -> dict[str, Any]:
        return self._get(f"{self._base}/sites/{quote(site_id, safe='')}/lists/{quote(list_id, safe='')}/drive",
                         {"$select": "id,name,webUrl"})

    def list_drive_items(self, site_id: str, list_id: str) -> Iterator[dict[str, Any]]:
        """Every list item with its driveItem, so list items map to drive items in bulk."""

        return self._pages(
            f"{self._base}/sites/{quote(site_id, safe='')}/lists/{quote(list_id, safe='')}/items",
            {"$expand": "driveItem"},
        )

    def drive_item_permissions(self, drive_id: str, item_id: str) -> Iterator[dict[str, Any]]:
        return self._pages(
            f"{self._base}/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/permissions"
        )

    def drive_root_permissions(self, drive_id: str) -> Iterator[dict[str, Any]]:
        return self._pages(f"{self._base}/drives/{quote(drive_id, safe='')}/root/permissions")

    def drive_item_content(self, drive_id: str, item_id: str) -> bytes:
        url = f"{self._base}/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/content"
        response = self._http.request("GET", url, tokens=self._tokens)
        check_response(self.service, response)
        return response.content

    def user(self, identifier: str) -> dict[str, Any] | None:
        """Returns None when the account does not exist (deleted or never created)."""

        url = f"{self._base}/users/{quote(identifier, safe='@')}"
        response = self._http.request(
            "GET", url, tokens=self._tokens, params={"$select": "id,displayName,userPrincipalName,accountEnabled,mail"}
        )
        if response.status_code == 404:
            return None
        check_response(self.service, response)
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def group_users(self, group_id: str) -> Iterator[dict[str, Any]]:
        return self._pages(
            f"{self._base}/groups/{quote(group_id, safe='')}/transitiveMembers/microsoft.graph.user",
            {"$select": "id,displayName,userPrincipalName,accountEnabled"},
        )

    def group_owners(self, group_id: str) -> Iterator[dict[str, Any]]:
        return self._pages(
            f"{self._base}/groups/{quote(group_id, safe='')}/owners/microsoft.graph.user",
            {"$select": "id,displayName,userPrincipalName,accountEnabled"},
        )

    def send_mail(self, sender_upn: str, message: dict[str, Any]) -> None:
        url = f"{self._base}/users/{quote(sender_upn, safe='@')}/sendMail"
        response = self._http.request(
            "POST", url, tokens=self._tokens, json_body={"message": message, "saveToSentItems": True}
        )
        if response.status_code >= 400:
            check_response(self.service, response)
            raise UpstreamError(self.service, f"sendMail failed: {upstream_detail(response)}",
                                code="upstream_bad_request", status_code=502)
