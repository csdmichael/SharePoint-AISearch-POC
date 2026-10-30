"""Test-only stand-in for SharePoint REST, Microsoft Graph, the Entra JWKS endpoint and Microsoft Foundry.

It serves the fixture tenant (tests/fixtures/tenant/tenant.json) through httpx.MockTransport, so the real clients,
retries and services run unchanged. Only the test suite imports this module; the application never does.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from tests.helpers.office import build_document

FIXTURE_TENANT = Path(__file__).resolve().parents[1] / "fixtures" / "tenant" / "tenant.json"
SHAREPOINT_HOST = "contoso.sharepoint.com"
GRAPH_HOST = "graph.microsoft.com"
LOGIN_HOST = "login.microsoftonline.com"
FOUNDRY_SUFFIX = ".services.ai.azure.com"
OWNER_DOMAIN = "contoso.com"
DEFAULT_LIBRARY_TITLE = "Trusted Knowledge"


def load_tenant() -> dict[str, Any]:
    return json.loads(FIXTURE_TENANT.read_text(encoding="utf-8"))


@dataclass
class Rule:
    contains: str
    status: int
    times: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None


@dataclass
class FakeTenant:
    data: dict[str, Any]
    calls: list[tuple[str, str]] = field(default_factory=list)
    sent_mail: list[dict[str, Any]] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    jwks: dict[str, Any] = field(default_factory=lambda: {"keys": []})
    foundry_status: int = 200
    foundry_body: dict[str, Any] = field(default_factory=lambda: {
        "output": [{"type": "message", "content": [{"type": "output_text",
                                                    "text": "Grounded answer from the Foundry agent."}]}]
    })
    foundry_calls: list[dict[str, Any]] = field(default_factory=list)
    scopes_seen: list[str] = field(default_factory=list)
    content_versions: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # key -> (library, item, list item id). List item ids are per library, starting at 1, in fixture order.
        self._located: dict[str, tuple[dict[str, Any], dict[str, Any], int]] = {}
        for library in self.data["libraries"]:
            for position, item in enumerate(library["items"], start=1):
                self._located[item["key"]] = (library, item, position)

    # ---- fixture helpers ------------------------------------------------------------------------------------

    @property
    def libraries(self) -> list[dict[str, Any]]:
        return list(self.data["libraries"])

    @property
    def site_path(self) -> str:
        return self.data["site"]["path"]

    def library_by_title(self, title: str = DEFAULT_LIBRARY_TITLE) -> dict[str, Any]:
        for library in self.libraries:
            if library["title"] == title:
                return library
        raise KeyError(title)

    def library_by_id(self, library_id: str) -> dict[str, Any] | None:
        for library in self.libraries:
            if library["id"].lower() == library_id.lower():
                return library
        return None

    def library_id(self, title: str = DEFAULT_LIBRARY_TITLE) -> str:
        return self.library_by_title(title)["id"]

    def item_id(self, path: str, *, library: str = DEFAULT_LIBRARY_TITLE) -> str:
        """The composite item id the API uses: <library guid>.<list item id>."""

        target = self.library_by_title(library)
        for position, item in enumerate(target["items"], start=1):
            if item["path"] == path:
                return f"{target['id']}.{position}"
        raise KeyError(path)

    def item_by_path(self, relative: str, *, library: str = DEFAULT_LIBRARY_TITLE) -> dict[str, Any]:
        for item in self.library_by_title(library)["items"]:
            if item["path"] == relative:
                return item
        raise KeyError(relative)

    def full_path(self, library: dict[str, Any], item: dict[str, Any]) -> str:
        return f"{library['rootPath']}/{item['path']}"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def add_rule(self, contains: str, status: int, *, times: int = 1, headers: dict[str, str] | None = None,
                 body: Any = None) -> None:
        self.rules.append(Rule(contains=contains, status=status, times=times, headers=headers or {}, body=body))

    def bump_content(self, key: str) -> None:
        """Edits one file: its content tag changes, as it does in SharePoint after a save."""

        self.content_versions[key] = self.content_versions.get(key, 0) + 1

    # ---- routing --------------------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, str(request.url)))
        authorization = request.headers.get("authorization", "")
        if request.url.host != LOGIN_HOST and authorization:
            self.scopes_seen.append(authorization)
        for rule in self.rules:
            if rule.times > 0 and rule.contains in str(request.url):
                rule.times -= 1
                return httpx.Response(rule.status, headers=rule.headers,
                                      json=rule.body if rule.body is not None else {"error": {"code": "injected"}})
        host = request.url.host
        if host == SHAREPOINT_HOST:
            return self._sharepoint(request)
        if host == GRAPH_HOST:
            return self._graph(request)
        if host == LOGIN_HOST:
            return httpx.Response(200, json=self.jwks)
        if host.endswith(FOUNDRY_SUFFIX):
            return self._foundry(request)
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": "unknown host"}})

    @staticmethod
    def _page(rows: list[Any], request: httpx.Request) -> httpx.Response:
        top = int(request.url.params.get("$top", len(rows) or 1))
        skip = int(request.url.params.get("$skiptoken", "0"))
        window = rows[skip:skip + top]
        payload: dict[str, Any] = {"value": window}
        if skip + top < len(rows):
            payload["odata.nextLink"] = str(request.url.copy_merge_params({"$skiptoken": str(skip + top)}))
        return httpx.Response(200, json=payload)

    # ---- SharePoint REST ------------------------------------------------------------------------------------

    def _sharepoint(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        api = f"{self.site_path}/_api"
        if not path.startswith(api):
            return httpx.Response(404, json={"error": {"message": {"value": "not found"}}})
        rest = path[len(api):]
        if rest == "/web":
            return httpx.Response(200, json={
                "Id": "site-web-id", "Title": self.data["site"]["title"],
                "Url": f"https://{SHAREPOINT_HOST}{self.site_path}",
                "ServerRelativeUrl": self.site_path,
                "HasUniqueRoleAssignments": self.data["site"]["uniqueRoleAssignments"],
            })
        if rest == "/web/lists":
            return self._page([self._library_row(library) for library in self.libraries], request)
        if rest == "/web/roleassignments":
            return self._page(self._role_rows(self.data["site"]["roleAssignments"]), request)
        match = re.fullmatch(r"/web/sitegroups/getbyid\((\d+)\)/users", rest)
        if match:
            group = self.data["siteGroups"].get(match.group(1))
            if group is None:
                return httpx.Response(404, json={"error": {"message": {"value": "group not found"}}})
            return self._page(group["users"], request)
        if rest == "/web/siteusers":
            return self._page(self.data["siteUsers"], request)
        match = re.fullmatch(r"/web/GetFolderByServerRelativeUrl\('(.*)'\)/ListItemAllFields", rest)
        if match:
            wanted = match.group(1).replace("''", "'").lower()
            for library in self.libraries:
                for item in library["items"]:
                    if self.full_path(library, item).lower() == wanted:
                        return httpx.Response(200, json=self._item_row(library, item))
            return httpx.Response(404, json={"error": {"message": {"value": "Folder does not exist"}}})
        match = re.fullmatch(r"/web/lists\(guid'([0-9a-fA-F-]{36})'\)(.*)", rest)
        if match:
            return self._list_route(match.group(1), match.group(2), request)
        return httpx.Response(404, json={"error": {"message": {"value": f"unhandled {rest}"}}})

    def _list_route(self, library_id: str, tail: str, request: httpx.Request) -> httpx.Response:
        library = self.library_by_id(library_id)
        if library is None:
            return httpx.Response(404, json={"error": {"message": {"value": "List does not exist"}}})
        if tail == "":
            return httpx.Response(200, json=self._library_row(library))
        if tail == "/items":
            rows = [self._item_row(library, item) for item in library["items"]]
            filter_text = request.url.params.get("$filter")
            if filter_text:
                match = re.fullmatch(r"FileDirRef eq '(.*)'", filter_text)
                if match:
                    wanted = match.group(1).replace("''", "'")
                    rows = [row for row in rows if row["FileDirRef"] == wanted]
            return self._page(rows, request)
        if tail == "/fields":
            if "fields" not in library:
                return httpx.Response(404, json={"error": {"message": {"value": "fields are not modelled"}}})
            return self._page([{"InternalName": name} for name in library["fields"]], request)
        if tail == "/roleassignments":
            return self._page(self._role_rows(library.get("roleAssignments", [])), request)
        match = re.fullmatch(r"/items\((\d+)\)(/roleassignments)?", tail)
        if match:
            item = self._item_at(library, int(match.group(1)))
            if item is None:
                return httpx.Response(404, json={"error": {"message": {"value": "Item does not exist"}}})
            if match.group(2):
                return self._page(self._role_rows(item.get("roleAssignments", [])), request)
            return httpx.Response(200, json=self._item_row(library, item))
        return httpx.Response(404, json={"error": {"message": {"value": f"unhandled {tail}"}}})

    @staticmethod
    def _item_at(library: dict[str, Any], list_item_id: int) -> dict[str, Any] | None:
        for position, item in enumerate(library["items"], start=1):
            if position == list_item_id:
                return item
        return None

    def _library_row(self, library: dict[str, Any]) -> dict[str, Any]:
        return {
            "Id": library["id"],
            "Title": library["title"],
            "HasUniqueRoleAssignments": library["uniqueRoleAssignments"],
            "RootFolder": {"ServerRelativeUrl": library["rootPath"]},
        }

    def _owner(self, owner: str | None) -> dict[str, Any] | None:
        if not owner:
            return None
        upn = f"{owner}@{OWNER_DOMAIN}"
        directory = self.data["directory"][upn]
        return {"Title": directory["displayName"], "EMail": upn, "Name": f"i:0#.f|membership|{upn}"}

    def _item_row(self, library: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        position = next(pos for pos, candidate in enumerate(library["items"], start=1) if candidate is item)
        full = self.full_path(library, item)
        is_folder = item["kind"] == "folder"
        children = [child for child in library["items"]
                    if child["path"].startswith(item["path"] + "/") and "/" not in child["path"][len(item["path"]) + 1:]]
        row: dict[str, Any] = {
            "Id": position,
            "UniqueId": f"00000000-0000-0000-0000-{position:012d}",
            "FileSystemObjectType": 1 if is_folder else 0,
            "FileRef": full,
            "FileDirRef": full.rsplit("/", 1)[0],
            "FileLeafRef": full.rsplit("/", 1)[1],
            "Title": item["path"].rsplit("/", 1)[-1],
            "Modified": item["modified"],
            "Created": item["modified"],
            "HasUniqueRoleAssignments": item["unique"],
            "File": None if is_folder else {"Length": item.get("size", 0)},
            "Folder": {"ItemCount": len(children)} if is_folder else None,
            "KnowledgeOwner": self._owner(item.get("owner")),
        }
        row.update(item.get("gov", {}))
        return row

    def _role_rows(self, assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "PrincipalId": assignment["member"].get("Id"),
                "Member": assignment["member"],
                "RoleDefinitionBindings": [{"Name": name} for name in assignment["roles"]],
            }
            for assignment in assignments
        ]

    # ---- Microsoft Graph ------------------------------------------------------------------------------------

    def _graph(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        match = re.fullmatch(r"/v1\.0/sites/([^/:]+):(/.*)", path)
        if match and method == "GET":
            if match.group(1) != SHAREPOINT_HOST or match.group(2) != self.site_path:
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            return httpx.Response(200, json={"id": self.data["site"]["graphSiteId"],
                                             "displayName": self.data["site"]["title"]})
        match = re.fullmatch(r"/v1\.0/sites/([^/]+)/lists/([^/]+)/drive", path)
        if match:
            library = self.library_by_id(match.group(2))
            if library is None:
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            return httpx.Response(200, json={"id": library["driveId"], "name": "Documents"})
        match = re.fullmatch(r"/v1\.0/sites/([^/]+)/lists/([^/]+)/items", path)
        if match:
            library = self.library_by_id(match.group(2))
            if library is None:
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            rows = []
            for position, item in enumerate(library["items"], start=1):
                rows.append({
                    "id": str(position),
                    "driveItem": {
                        "id": f"drv-{item['key']}",
                        "name": item["path"].rsplit("/", 1)[-1],
                        "cTag": f"c:{item['key']}:{self.content_versions.get(item['key'], 0)}",
                        "parentReference": {"driveId": library["driveId"]},
                        "folder": {} if item["kind"] == "folder" else None,
                        "file": {} if item["kind"] == "file" else None,
                    },
                })
            return self._page(rows, request)
        match = re.fullmatch(r"/v1\.0/drives/([^/]+)/items/([^/]+)/permissions", path)
        if match:
            item = self._drive_item(match.group(2))
            return self._page(item.get("links", []) if item else [], request)
        match = re.fullmatch(r"/v1\.0/drives/([^/]+)/root/permissions", path)
        if match:
            return self._page([], request)
        match = re.fullmatch(r"/v1\.0/drives/([^/]+)/items/([^/]+)/content", path)
        if match:
            item = self._drive_item(match.group(2))
            if item is None or "content" not in item:
                return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
            return httpx.Response(200, content=build_document(item["content"]))
        match = re.fullmatch(r"/v1\.0/groups/([^/]+)/transitiveMembers/microsoft\.graph\.user", path)
        if match:
            group = self.data["entraGroups"].get(match.group(1))
            if group is None:
                return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
            return self._page(group["members"], request)
        match = re.fullmatch(r"/v1\.0/users/([^/]+)/sendMail", path)
        if match and method == "POST":
            self.sent_mail.append({"sender": match.group(1), "body": json.loads(request.content.decode("utf-8"))})
            return httpx.Response(202)
        match = re.fullmatch(r"/v1\.0/users/([^/]+)", path)
        if match and method == "GET":
            account = self._directory_lookup(match.group(1))
            if account is None:
                return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
            return httpx.Response(200, json=account)
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": path}})

    def _drive_item(self, drive_item_id: str) -> dict[str, Any] | None:
        for library in self.libraries:
            for item in library["items"]:
                if f"drv-{item['key']}" == drive_item_id:
                    return item
        return None

    def _directory_lookup(self, identifier: str) -> dict[str, Any] | None:
        for upn, account in self.data["directory"].items():
            if upn.lower() == identifier.lower() or account["id"] == identifier:
                return {"id": account["id"], "displayName": account["displayName"],
                        "userPrincipalName": upn, "accountEnabled": account["accountEnabled"]}
        return None

    # ---- Foundry ------------------------------------------------------------------------------------------

    def _foundry(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/openai/v1/responses"):
            self.foundry_calls.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(self.foundry_status, json=self.foundry_body)
        return httpx.Response(404, json={"error": {"message": "unknown Foundry route"}})
