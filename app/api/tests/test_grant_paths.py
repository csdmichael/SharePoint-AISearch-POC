"""Grant-path labels from the domain layer: each mechanism yields the expected grantedVia value."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.domain.permissions import GRANT_DIRECT, GRANT_ENTRA_GROUP, GRANT_EVERYONE, GRANT_INHERITED
from app.domain.permissions import GRANT_SHAREPOINT_GROUP, SourceRef, entries_from_assignments
from app.domain.principals import PrincipalClassifier

TENANT_GUID = "11111111-2222-3333-4444-555555555555"


def classifier_for(settings: Settings) -> PrincipalClassifier:
    exposure = settings.analytics.exposure
    return PrincipalClassifier(
        settings.analytics.loginNamePatterns,
        everyone_including_external=exposure.everyoneLoginPattern,
        type_map=settings.api.sharePoint.principalTypes,
        claim_labels=exposure.everyoneLabels,
    )


def assignment(member: dict[str, Any], role: str = "Read") -> dict[str, Any]:
    return {"Member": member, "RoleDefinitionBindings": [{"Name": role}]}


ENTRA_GROUP = {"Id": 21, "LoginName": "c:0o.c|federateddirectoryclaimprovider|aaaaaaaa-0000-4000-8000-000000000001",
               "Title": "Trusted Knowledge Readers", "PrincipalType": 4}
SHAREPOINT_GROUP = {"Id": 42, "LoginName": "Knowledge Members", "Title": "Knowledge Members", "PrincipalType": 8}
USER = {"Id": 12, "LoginName": "i:0#.f|membership|bob@contoso.com", "Title": "Bob Reviewer", "PrincipalType": 1,
        "Email": "bob@contoso.com"}
EVERYONE = {"Id": 31, "LoginName": "c:0(.s|true", "Title": "Everyone", "PrincipalType": 4}
EVERYONE_EXCEPT_EXTERNAL = {"Id": 30, "LoginName": f"c:0-.f|rolemanager|spo-grid-all-users/{TENANT_GUID}",
                            "Title": "Everyone except external users", "PrincipalType": 4}
SHARING_LINK = {"Id": 40, "LoginName": "SharingLinks.6c7b1f0a.Flexible.9a1f22aa", "Title": "link", "PrincipalType": 8}


def grant_of(settings: Settings, member: dict[str, Any], inherited_from: SourceRef | None = None) -> str:
    entries = entries_from_assignments([assignment(member)], classifier_for(settings), inherited_from=inherited_from)
    assert len(entries) == 1
    return entries[0].granted_via


def test_each_direct_mechanism_has_its_own_label(settings: Settings) -> None:
    assert grant_of(settings, USER) == GRANT_DIRECT
    assert grant_of(settings, ENTRA_GROUP) == GRANT_ENTRA_GROUP
    assert grant_of(settings, SHAREPOINT_GROUP) == GRANT_SHAREPOINT_GROUP
    assert grant_of(settings, EVERYONE) == GRANT_EVERYONE


def test_an_inherited_assignment_is_labelled_inherited_whatever_its_principal(settings: Settings) -> None:
    source = SourceRef("site", "/sites/knowledge", "site")
    assert grant_of(settings, USER, inherited_from=source) == GRANT_INHERITED
    assert grant_of(settings, ENTRA_GROUP, inherited_from=source) == GRANT_INHERITED


def test_sharing_link_assignments_are_left_to_the_link_reader(settings: Settings) -> None:
    entries = entries_from_assignments([assignment(SHARING_LINK)], classifier_for(settings), inherited_from=None)
    assert entries == []


def test_everyone_except_external_users_is_labelled_from_config(settings: Settings) -> None:
    entries = entries_from_assignments([assignment(EVERYONE_EXCEPT_EXTERNAL)], classifier_for(settings),
                                       inherited_from=None)
    assert entries[0].principal.display_name == settings.analytics.exposure.everyoneLabels["exceptExternal"]
    assert entries[0].principal.claim_scope == "exceptExternal"


def test_placeholder_roles_are_dropped_when_a_real_role_exists(settings: Settings) -> None:
    rows = [{"Member": USER, "RoleDefinitionBindings": [{"Name": "Edit"}, {"Name": "Limited Access"}]}]
    entries = entries_from_assignments(rows, classifier_for(settings), inherited_from=None)
    assert entries[0].roles == ("Edit",)
    assert entries[0].role == "Edit"
