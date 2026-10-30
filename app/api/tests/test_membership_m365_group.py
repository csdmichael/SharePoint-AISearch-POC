import re

from app.domain.principals import Principal, PrincipalKind
from app.services.membership import MembershipService

GROUP_ID = "11111111-2222-4333-8444-555555555555"
USER_PATTERN = re.compile(r"i:0#\.f\|membership\|(?P<upn>[^|]+)$", re.IGNORECASE)


class FakeSharePoint:
    def __init__(self, rows):
        self._rows = rows

    def group_users(self, group_id):
        return iter(self._rows)


class FakeGraph:
    def __init__(self):
        self.calls = []

    def group_users(self, group_id):
        self.calls.append(("members", group_id))
        return iter([{"id": "u1", "displayName": "Mia Member", "userPrincipalName": "Mia@contoso.com", "accountEnabled": True}])

    def group_owners(self, group_id):
        self.calls.append(("owners", group_id))
        return iter([{"id": "u2", "displayName": "Omar Owner", "userPrincipalName": "omar@contoso.com", "accountEnabled": True}])

    def user(self, identifier):
        return {"accountEnabled": True}


def _service(rows, graph):
    return MembershipService(
        graph=graph,
        sharepoint=FakeSharePoint(rows),
        user_pattern=USER_PATTERN,
        ttl_seconds=0,
        max_members=100,
    )


def _group() -> Principal:
    return Principal(kind=PrincipalKind.SHAREPOINT_GROUP, key="sp:7", display_name="Team Members", sp_principal_id=7)


def test_m365_group_claim_expands_to_real_members():
    graph = FakeGraph()
    rows = [{"Id": 6, "LoginName": f"c:0o.c|federateddirectoryclaimprovider|{GROUP_ID}", "Title": "Team", "Email": "team@contoso.com"}]
    members = _service(rows, graph).members(_group())
    assert [member.upn for member in members] == ["mia@contoso.com"]
    assert graph.calls == [("members", GROUP_ID)]


def test_m365_owner_claim_expands_to_owners_and_keeps_direct_users():
    graph = FakeGraph()
    rows = [
        {"Id": 6, "LoginName": f"c:0o.c|federateddirectoryclaimprovider|{GROUP_ID}_o", "Title": "Team owners", "Email": "team@contoso.com"},
        {"Id": 9, "LoginName": "i:0#.f|membership|direct@contoso.com", "Title": "Direct User"},
    ]
    members = _service(rows, graph).members(_group())
    assert sorted(member.upn for member in members) == ["direct@contoso.com", "omar@contoso.com"]
    assert graph.calls == [("owners", GROUP_ID)]
