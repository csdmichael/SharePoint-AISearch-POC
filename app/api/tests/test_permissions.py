"""Item permissions and access by user. Each entry carries its principal, role and grant path."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers.fake_tenant import FakeTenant


def permissions(client: TestClient, headers: dict[str, str], item_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/items/{item_id}/permissions", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def entry_named(body: dict[str, Any], display_name: str) -> dict[str, Any]:
    matches = [entry for entry in body["entries"] if entry["principal"]["displayName"] == display_name]
    assert len(matches) == 1, [entry["principal"]["displayName"] for entry in body["entries"]]
    return matches[0]


def test_everyone_claim_on_a_unique_folder_is_labelled_everyone(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Engineering"))
    assert body["inheritance"] == {"hasUniquePermissions": True, "source": None}
    entry = entry_named(body, "Everyone (including external users)")
    assert entry["principal"]["type"] == "claims"
    assert entry["grantedVia"] == "everyone"
    assert entry["role"] == "Read"


def test_an_item_under_a_unique_folder_inherits_only_that_folders_grants(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Engineering/Thermal Notes.xlsx"))
    assert body["inheritance"]["hasUniquePermissions"] is False
    assert body["inheritance"]["source"]["kind"] == "item"
    assert body["inheritance"]["source"]["path"].endswith("/Engineering")
    assert [entry["principal"]["displayName"] for entry in body["entries"]] == [
        "Everyone (including external users)"
    ]
    assert body["entries"][0]["grantedVia"] == "inherited"
    assert body["entries"][0]["inheritedFrom"]["path"].endswith("/Engineering")


def test_inherited_grants_name_their_source_and_expand_groups(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Archive/Old Calibration Report.docx"))
    assert body["inheritance"]["hasUniquePermissions"] is False
    assert body["inheritance"]["source"]["kind"] == "site"

    readers = entry_named(body, "Trusted Knowledge Readers")
    assert readers["grantedVia"] == "inherited"
    assert readers["principal"]["type"] == "entraGroup"
    members = {member["userPrincipalName"]: member for member in readers["expandedMembers"]}
    assert members["alice@contoso.com"]["status"] == "enabled"
    assert members["dave@contoso.com"]["status"] == "disabled"

    knowledge = entry_named(body, "Knowledge Members")
    assert knowledge["grantedVia"] == "inherited"
    assert knowledge["principal"]["type"] == "sharePointGroup"
    assert {member["userPrincipalName"] for member in knowledge["expandedMembers"]} == {
        "alice@contoso.com",
        "eve@contoso.com",
    }


def test_inherited_user_grant_points_at_the_unique_folder_it_comes_from(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Restricted/Restricted Spec.docx"))
    assert body["inheritance"]["source"]["kind"] == "item"
    bob = entry_named(body, "Bob Reviewer")
    assert bob["grantedVia"] == "inherited"
    assert bob["inheritedFrom"]["path"].endswith("/Restricted")


def test_sharing_link_entries_carry_scope_type_and_grantees(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Restricted/Restricted Spec.docx"))
    link = entry_named(body, "Specific people")
    assert link["grantedVia"] == "sharingLink"
    assert link["linkScope"] == "users"
    assert link["linkType"] == "edit"
    assert link["role"] == "Edit"
    assert [member["userPrincipalName"] for member in link["expandedMembers"]] == ["alice@contoso.com"]


def test_direct_anonymous_and_missing_account_grants_on_one_file(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.item_id("Anomalous Export.xlsx"))
    assert body["inheritance"]["hasUniquePermissions"] is True

    alice = entry_named(body, "Alice Owner")
    assert alice["grantedVia"] == "direct"
    assert alice["role"] == "Full Control"
    assert alice["accountEnabled"] is True
    assert alice["accountStatus"] == "enabled"

    carol = entry_named(body, "Carol Guest")
    assert carol["grantedVia"] == "direct"
    assert carol["principal"]["email"] == "carol@fabrikam.com"

    gone = entry_named(body, "Gone User")
    assert gone["accountStatus"] == "missing"
    assert gone["accountEnabled"] is None

    anonymous = entry_named(body, "Anyone with the link")
    assert anonymous["grantedVia"] == "sharingLink"
    assert anonymous["linkScope"] == "anonymous"
    assert anonymous["role"] == "Read"

    everyone = entry_named(body, "Everyone except external users")
    assert everyone["grantedVia"] == "everyone"


def test_library_permissions_report_the_site_they_inherit_from(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    body = permissions(client, auth_headers, tenant.library_id("Trusted Knowledge"))
    assert body["item"]["kind"] == "library"
    assert body["inheritance"]["source"]["kind"] == "site"
    assert {entry["principal"]["displayName"] for entry in body["entries"]} == {
        "Knowledge Members",
        "Trusted Knowledge Readers",
    }


def test_user_search_marks_guests_as_external(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/access/users?query=carol", headers=auth_headers).json()
    assert [user["displayName"] for user in body["users"]] == ["Carol Guest"]
    assert body["users"][0]["external"] is True
    assert body["users"][0]["email"] == "carol@fabrikam.com"


def test_a_user_reach_lists_direct_group_and_link_paths(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/access/users/alice@contoso.com/items?pageSize=200", headers=auth_headers).json()
    assert body["user"] == {"userKey": "alice@contoso.com", "external": False}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for record in body["items"]:
        by_name.setdefault(record["item"]["name"], []).append(record)
    assert any(record["grantedVia"] == "direct" for record in by_name["Anomalous Export.xlsx"])
    assert any(record["grantedVia"] == "sharingLink" for record in by_name["Restricted Spec.docx"])
    assert any("Trusted Knowledge Readers" in record["via"] for record in by_name["Old Calibration Report.docx"])


def test_an_anonymous_link_reaches_every_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/access/users/bob@contoso.com/items?pageSize=200", headers=auth_headers).json()
    anonymous = [record for record in body["items"]
                 if record["item"]["name"] == "Anomalous Export.xlsx" and record["grantedVia"] == "sharingLink"]
    assert anonymous and anonymous[0]["linkScope"] == "anonymous"
    assert any(record["item"]["name"] == "Restricted" and record["grantedVia"] == "direct"
               for record in body["items"])


def test_grant_filter_and_paging_for_a_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    base = "/api/v1/access/users/alice@contoso.com/items"
    everything = client.get(f"{base}?pageSize=200", headers=auth_headers).json()
    direct = client.get(f"{base}?grantedVia=direct&pageSize=200", headers=auth_headers).json()
    assert 0 < direct["total"] < everything["total"]
    assert {record["grantedVia"] for record in direct["items"]} == {"direct"}

    first = client.get(f"{base}?pageSize=2&page=1", headers=auth_headers).json()
    second = client.get(f"{base}?pageSize=2&page=2", headers=auth_headers).json()
    assert len(first["items"]) == 2
    assert first["items"][0] != second["items"][0]
    assert first["totalPages"] == -(-everything["total"] // 2)


def test_an_unknown_granted_via_value_is_a_bad_request(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/access/users/alice@contoso.com/items?grantedVia=magic", headers=auth_headers)
    assert response.status_code == 400
