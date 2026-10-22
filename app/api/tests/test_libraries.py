"""Sites, libraries and folders: every document library is listed by default, folders load lazily, and system folders
stay hidden."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import load_settings
from tests.helpers.fake_tenant import FakeTenant

UNKNOWN_LIBRARY = "00000000-0000-0000-0000-000000000000"


def test_site_overview_reports_name_and_library_count(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/v1/site", headers=auth_headers).json()
    assert body["name"] == "Knowledge Hub"
    assert body["libraryCount"] == 2


def test_every_document_library_is_listed_by_default(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/site/libraries", headers=auth_headers)
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["Field Notes", "Trusted Knowledge"]


def test_library_filter_limits_the_listing_to_the_named_libraries(
    build_app, config_path, auth_headers: dict[str, str]
) -> None:
    filtered = load_settings(config_path, env={"API_CONFIG__sharePoint__libraryDisplayNames": "Trusted Knowledge"})
    client = TestClient(build_app(filtered))
    titles = [item["title"] for item in client.get("/api/v1/site/libraries", headers=auth_headers).json()["items"]]
    assert titles == ["Trusted Knowledge"]


def test_root_listing_puts_folders_first_and_hides_system_folders(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    library_id = tenant.library_id("Trusted Knowledge")
    body = client.get(f"/api/v1/site/libraries/{library_id}/children", headers=auth_headers).json()
    kinds_and_names = [(item["kind"], item["name"]) for item in body["items"]]
    assert kinds_and_names[:3] == [("folder", "Archive"), ("folder", "Engineering"), ("folder", "Restricted")]
    assert body["folder"] is None
    assert body["truncated"] is False


def test_second_library_shows_its_own_folders_and_not_the_forms_folder(
    client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant
) -> None:
    library_id = tenant.library_id("Field Notes")
    body = client.get(f"/api/v1/site/libraries/{library_id}/children", headers=auth_headers).json()
    assert body["library"]["title"] == "Field Notes"
    assert [item["name"] for item in body["items"]] == ["Archive Notes"]


def test_folder_children_load_lazily(client: TestClient, auth_headers: dict[str, str], tenant: FakeTenant) -> None:
    library_id = tenant.library_id("Trusted Knowledge")
    folder = tenant.item_id("Engineering")
    body = client.get(f"/api/v1/site/libraries/{library_id}/children?folderId={folder}", headers=auth_headers).json()
    assert body["folder"]["name"] == "Engineering"
    assert [item["name"] for item in body["items"]] == ["Thermal Notes.xlsx"]


def test_folder_from_another_library_is_refused(client: TestClient, auth_headers: dict[str, str],
                                                tenant: FakeTenant) -> None:
    library_id = tenant.library_id("Trusted Knowledge")
    foreign_folder = tenant.item_id("Archive Notes", library="Field Notes")
    response = client.get(f"/api/v1/site/libraries/{library_id}/children?folderId={foreign_folder}",
                          headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_a_file_cannot_be_used_as_a_folder(client: TestClient, auth_headers: dict[str, str],
                                           tenant: FakeTenant) -> None:
    library_id = tenant.library_id("Trusted Knowledge")
    file_id = tenant.item_id("Engineering/Thermal Notes.xlsx")
    response = client.get(f"/api/v1/site/libraries/{library_id}/children?folderId={file_id}", headers=auth_headers)
    assert response.status_code == 400
    assert "folder, not a file" in response.text


def test_unknown_library_is_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(f"/api/v1/site/libraries/{UNKNOWN_LIBRARY}/children", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
