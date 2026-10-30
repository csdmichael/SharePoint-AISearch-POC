#!/usr/bin/env python3
"""Computes the governance-computed columns for the libraries in governance-targets.json.

Run after Seed-RichGovernanceData.ps1 (declared values) and Upload-DuplicatePairs.ps1 (copies). For each library it
evaluates every file with the governance engine in scripts/trusted_knowledge and writes DataQualityStatus,
ConflictStatus, ConflictWith, DuplicateOf, ContentHash, TrustScore, AIReady, TrustReasons and LastValidatedDate.
Only values that differ from SharePoint are written. Every write is checked, and the run fails if any write fails.

Corpus
- A file is analysed when its extension is in analytics.json extraction.supportedExtensions (.docx, .pptx, .xlsx,
  .txt, .vtt). Its text comes from the API's extractors (app/api/app/analytics/text.py), loaded by path, so the
  API package is not imported.
- PDF and MP4 files are outside the API analytics corpus. They receive the per-document fields (data quality, trust,
  AI readiness, reasons) but no content hash, duplicate or conflict values.

Vectors
- The engine compares embedding vectors. The Azure OpenAI deployment in config/trusted-knowledge.json cannot be used
  by the signed-in account (it lacks the embeddings data action), so each library gets TF-IDF vectors with the
  analytics.json tfidf settings, fitted on the first embeddingCharacterLimit characters of the normalized text. The API's
  live duplicate analysis uses the same method. The engine's thresholds (near duplicate 0.95, conflict 0.8) apply to them.

Authentication
- Graph reads and writes use the Azure CLI user token.
- File bytes need an app-only token. SharePoint rejects the delegated CLI token on the content redirect (HTTP 401).
  The run creates a read-only app (Sites.Read.All, Files.Read.All), uses it for downloads, and deletes it on exit.

Usage
    python scripts/Sync-GovernanceFields.py              # write the computed columns
    python scripts/Sync-GovernanceFields.py --dry-run    # evaluate and report without writing
    python scripts/Sync-GovernanceFields.py --site hr    # one site from governance-targets.json
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.trusted_knowledge import governance, similarity  # noqa: E402
from scripts.trusted_knowledge.policy import Policy  # noqa: E402

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
READ_ROLES = ("Sites.Read.All", "Files.Read.All")
TARGETS_PATH = Path(__file__).resolve().parent / "governance-targets.json"
ANALYTICS_PATH = REPO_ROOT / "app" / "api" / "config" / "analytics.json"
TEXT_MODULE_PATH = REPO_ROOT / "app" / "api" / "app" / "analytics" / "text.py"
POLICY_PATH = REPO_ROOT / "config" / "governance-policy.json"
VOCABULARY_PATH = REPO_ROOT / "config" / "governance-vocabulary.json"
AZ = shutil.which("az") or "az"

# Logical keys of the declared values the engine reads. Column names come from the policy vocabulary.
DECLARED_KEYS = (
    "fileName", "artifactId", "title", "knowledgeCategory", "sourceSystem", "knowledgeOwner",
    "lifecycleStatus", "authoritative", "reviewDate", "documentType", "productFamily", "processArea",
    "sensitivity", "effectiveDate", "expirationDate", "supersedesDocument",
)
# Logical keys of the governance-computed columns this script writes.
COMPUTED_KEYS = (
    "aiReady", "trustScore", "dataQualityStatus", "conflictStatus", "conflictWith", "duplicateOf",
    "contentHash", "trustReasons", "lastValidatedDate",
)
EMPTY_CONTENT_HASH = ""


class GraphError(RuntimeError):
    """A Microsoft Graph call failed. The message carries the HTTP status and the service detail."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def cli_token(resource: str, tenant_id: str) -> str:
    result = subprocess.run(
        [AZ, "account", "get-access-token", "--tenant", tenant_id, "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Could not get a token for {resource} from Azure CLI: {result.stderr.strip()}")
    return result.stdout.strip()


def jwt_claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def client_credentials_token(tenant_id: str, client_id: str, secret: str) -> str:
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


class Graph:
    """Minimal Graph client: JSON requests with retries for throttling and transient server errors."""

    def __init__(self, token: str) -> None:
        self._token = token

    def request(self, method: str, url: str, body: Any | None = None, retries: int = 5) -> Any:
        data = None
        headers = {"Authorization": f"Bearer {self._token}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        for attempt in range(1, retries + 1):
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8")) if raw else None
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:600]
                if error.code in (429, 500, 502, 503, 504) and attempt < retries:
                    retry_after = int(error.headers.get("Retry-After") or 0)
                    time.sleep(max(retry_after, 2 ** attempt))
                    continue
                raise GraphError(f"{method} {url} failed with HTTP {error.code}: {detail}") from None
            except urllib.error.URLError as error:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise GraphError(f"{method} {url} failed: {error.reason}") from None
        raise GraphError(f"{method} {url} failed after {retries} attempts")

    def get(self, url: str) -> Any:
        return self.request("GET", url)

    def pages(self, url: str) -> Iterator[dict[str, Any]]:
        next_url: str | None = url
        while next_url:
            page = self.get(next_url)
            yield from page.get("value", [])
            next_url = page.get("@odata.nextLink")


class ReadOnlyApp:
    """Read-only app registration for file downloads. Created for one run and deleted when the run ends."""

    def __init__(self, graph: Graph, tenant_id: str) -> None:
        self._graph = graph
        self._tenant_id = tenant_id
        self._app_object_id: str | None = None

    def __enter__(self) -> str:
        graph = self._graph
        graph_filter = urllib.parse.quote(f"appId eq '{GRAPH_APP_ID}'")
        service = next(iter(graph.get(f"{GRAPH}/servicePrincipals?$filter={graph_filter}&$select=id,appId,appRoles")["value"]))
        role_ids: dict[str, str] = {}
        for role in READ_ROLES:
            matches = [r for r in service.get("appRoles", [])
                       if r.get("value") == role and "Application" in r.get("allowedMemberTypes", [])]
            if len(matches) != 1:
                raise RuntimeError(f"Microsoft Graph application role {role} was not found.")
            role_ids[role] = matches[0]["id"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        app = graph.request("POST", f"{GRAPH}/applications", {
            "displayName": f"Governance Field Reader {stamp}",
            "signInAudience": "AzureADMyOrg",
            "requiredResourceAccess": [{
                "resourceAppId": GRAPH_APP_ID,
                "resourceAccess": [{"id": role_ids[role], "type": "Role"} for role in READ_ROLES],
            }],
        })
        self._app_object_id = app["id"]
        principal = graph.request("POST", f"{GRAPH}/servicePrincipals", {"appId": app["appId"]})
        for role in READ_ROLES:
            graph.request("POST", f"{GRAPH}/servicePrincipals/{principal['id']}/appRoleAssignments", {
                "principalId": principal["id"], "resourceId": service["id"], "appRoleId": role_ids[role],
            })
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        password = graph.request("POST", f"{GRAPH}/applications/{app['id']}/addPassword", {
            "passwordCredential": {"displayName": "run", "endDateTime": expires},
        })
        return self._wait_for_roles(app["appId"], password["secretText"])

    def _wait_for_roles(self, client_id: str, secret: str) -> str:
        last_result = "no response"
        for _ in range(40):
            try:
                token = client_credentials_token(self._tenant_id, client_id, secret)
                roles = jwt_claims(token).get("roles", [])
                if all(role in roles for role in READ_ROLES):
                    return token
                last_result = f"token roles were {', '.join(roles) or 'none'}"
            except (urllib.error.URLError, KeyError, ValueError) as error:
                last_result = str(error)
            time.sleep(4)
        raise RuntimeError(f"The read-only app did not receive its Graph roles in time. Last result: {last_result}")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._app_object_id is None:
            return
        app_id, self._app_object_id = self._app_object_id, None
        try:
            self._graph.request("DELETE", f"{GRAPH}/applications/{app_id}")
        except GraphError as error:
            message = f"could not delete the temporary read-only app {app_id}: {error}"
            if exc_type is None:
                raise RuntimeError(message) from error
            print(f"WARNING: {message}", file=sys.stderr)


def download_bytes(drive_id: str, item_id: str, token: str) -> bytes:
    url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/content"
    for attempt in range(1, 4):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            # urllib keeps the Authorization header on the redirect to SharePoint, which requires it.
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except urllib.error.URLError as error:
            if attempt == 3:
                raise GraphError(f"Download of item {item_id} failed: {error}") from None
            time.sleep(2 ** attempt)
    raise GraphError(f"Download of item {item_id} failed.")


def date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value)[:10]).isoformat()


def normalise(key: str, value: Any) -> Any:
    """Comparable form of a computed value, so that the same value read from Graph and computed compare equal."""
    if value is None:
        return None
    if key == "aiReady":
        return bool(value)
    if key == "trustScore":
        return int(round(float(value)))
    if key == "lastValidatedDate":
        return date_text(value)
    text = str(value).replace("\r\n", "\n")
    return text or None


@dataclass
class LibraryItem:
    item_id: str
    name: str
    fields: dict[str, Any]
    drive_item: dict[str, Any] | None


@dataclass
class RunContext:
    graph: Graph
    policy: Policy
    as_of: date
    extensions: set[str]
    tfidf: Mapping[str, Any]
    text_module: Any
    read_token: str
    dry_run: bool
    failures: list[str]
    drive_id: str = ""


def resolve_library(graph: Graph, site_id: str, library_name: str) -> dict[str, Any]:
    lists = list(graph.pages(f"{GRAPH}/sites/{site_id}/lists?$select=id,displayName,name,list&$top=200"))
    matches = [entry for entry in lists
               if entry.get("displayName") == library_name and (entry.get("list") or {}).get("template") == "documentLibrary"]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one document library named '{library_name}' in site {site_id}; found {len(matches)}.")
    return matches[0]


def list_library_items(graph: Graph, site_id: str, list_id: str) -> list[LibraryItem]:
    base = f"{GRAPH}/sites/{site_id}/lists/{list_id}/items"
    fields_by_id = {row["id"]: row.get("fields", {}) for row in graph.pages(f"{base}?$expand=fields&$top=999")}
    drive_by_id = {row["id"]: row.get("driveItem") for row in graph.pages(f"{base}?$expand=driveItem&$top=999")}
    items = []
    for item_id, fields in fields_by_id.items():
        if fields.get("ContentType") == "Folder":
            continue
        items.append(LibraryItem(item_id=item_id, name=str(fields.get("FileLeafRef", "")), fields=fields,
                                 drive_item=drive_by_id.get(item_id)))
    return sorted(items, key=lambda item: item.name.lower())


def declared_columns(policy: Policy, item: LibraryItem) -> dict[str, Any]:
    fields = item.fields
    owner_name = fields.get("OwnerDisplayName") or None
    lookup = fields.get("KnowledgeOwnerLookupId")
    owner = owner_name or (f"user:{lookup}" if lookup not in (None, "") else None)
    values = {
        "fileName": item.name,
        "artifactId": fields.get("ArtifactId") or None,
        "title": fields.get("Title") or Path(item.name).stem,
        "knowledgeCategory": fields.get("KnowledgeCategory") or None,
        "sourceSystem": fields.get("SourceSystem") or None,
        "knowledgeOwner": owner,
        "lifecycleStatus": fields.get("LifecycleStatus") or None,
        "authoritative": bool(fields.get("Authoritative", False)),
        "reviewDate": date_text(fields.get("ReviewDate")),
        "documentType": fields.get("DocumentType") or None,
        "productFamily": fields.get("ProductFamily") or None,
        "processArea": fields.get("ProcessArea") or None,
        "sensitivity": fields.get("Sensitivity") or None,
        "effectiveDate": date_text(fields.get("EffectiveDate")),
        "expirationDate": date_text(fields.get("ExpirationDate")),
        "supersedesDocument": fields.get("SupersedesDocument") or None,
    }
    return {policy.column(key): values[key] for key in DECLARED_KEYS}


def tfidf_vectors(texts: Sequence[str], settings: Mapping[str, Any]) -> list[tuple[float, ...]]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        ngram_range=tuple(settings["ngramRange"]),
        min_df=settings["minDf"],
        max_features=settings["maxFeatures"],
        sublinear_tf=settings["sublinearTf"],
    )
    matrix = vectorizer.fit_transform(texts).toarray()
    return [tuple(row.tolist()) for row in matrix]


def evaluate_library(ctx: RunContext, items: Sequence[LibraryItem], label: str) -> tuple[governance.Evaluation, dict[str, governance.Assessment]]:
    policy = ctx.policy
    analysed = [item for item in items if Path(item.name).suffix.lower() in ctx.extensions]
    other = [item for item in items if Path(item.name).suffix.lower() not in ctx.extensions]

    texts: dict[str, str] = {}
    for item in analysed:
        if item.drive_item is None:
            raise RuntimeError(f"{label}: {item.name} has no driveItem, so its text cannot be read.")
        drive_item = item.drive_item
        content = download_bytes(ctx.drive_id, drive_item["id"], ctx.read_token)
        if len(content) != int(drive_item["size"]):
            raise RuntimeError(f"{label}: {item.name} downloaded {len(content)} bytes; Graph reports {drive_item['size']}.")
        texts[item.item_id] = ctx.text_module.extract_text(Path(item.name).suffix.lower(), content)

    normalized = {item_id: similarity.normalize_text(text, policy.whitespace_pattern()) for item_id, text in texts.items()}
    limit = policy.embedding_character_limit()
    vectors: dict[str, tuple[float, ...]] = {}
    if len(analysed) >= 2:
        ids = [item.item_id for item in analysed]
        for item_id, vector in zip(ids, tfidf_vectors([normalized[i][:limit] for i in ids], ctx.tfidf)):
            vectors[item_id] = vector
    elif analysed:
        vectors[analysed[0].item_id] = (1.0,)

    owner_by_item: dict[str, str | None] = {}
    declarations: list[governance.Declared] = []
    measurements: dict[str, governance.Measurement] = {}
    for item in analysed:
        try:
            declared_entry = {"declared": declared_columns(policy, item)}
            declarations.append(governance.Declared.from_manifest(declared_entry, policy))
            measurements[item.name] = governance.Measurement.from_manifest(
                {"body": texts[item.item_id], "vector": vectors[item.item_id]}, policy)
        except (ValueError, KeyError) as error:
            raise RuntimeError(f"{label}: {item.name}: {error}") from None
        owner_by_item[item.name] = item.fields.get("OwnerDisplayName") or None

    evaluation = governance.evaluate(declarations, measurements, policy, ctx.as_of)
    assessments = evaluation.by_key()

    for item in other:
        try:
            declaration = governance.Declared.from_manifest({"declared": declared_columns(policy, item)}, policy)
        except (ValueError, KeyError) as error:
            raise RuntimeError(f"{label}: {item.name}: {error}") from None
        single = governance.Measurement(content_hash=EMPTY_CONTENT_HASH, numeric_signature=(), vector=())
        single_evaluation = governance.evaluate([declaration], {declaration.key: single}, policy, ctx.as_of)
        assessments.update(single_evaluation.by_key())
        owner_by_item[item.name] = item.fields.get("OwnerDisplayName") or None

    return evaluation, assessments, owner_by_item, len(analysed), len(other)


def computed_changes(policy: Policy, computed: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key in COMPUTED_KEYS:
        column = policy.column(key)
        expected_raw = computed.get(column)
        if expected_raw == EMPTY_CONTENT_HASH:
            expected_raw = None
        expected = normalise(key, expected_raw)
        if expected != normalise(key, current.get(column)):
            changes[column] = expected
    return changes


def process_library(ctx: RunContext, site_id: str, site_key: str, library_name: str) -> None:
    graph = ctx.graph
    label = f"{site_key} / {library_name}"
    library = resolve_library(graph, site_id, library_name)
    list_id = library["id"]
    drive_id = graph.get(f"{GRAPH}/sites/{site_id}/lists/{list_id}/drive")["id"]
    ctx.drive_id = drive_id
    items = list_library_items(graph, site_id, list_id)
    print(f"== {label}: {len(items)} files")
    if not items:
        return
    duplicate_names = [name for name, count in Counter(item.name for item in items).items() if count > 1]
    if duplicate_names:
        raise RuntimeError(f"{label}: file names are not unique: {', '.join(duplicate_names)}")

    evaluation, assessments, owner_by_item, analysed_count, other_count = evaluate_library(ctx, items, label)
    policy = ctx.policy
    print(f"   analysed {analysed_count}, not in the analytics corpus {other_count}")

    pending: list[tuple[LibraryItem, dict[str, Any]]] = []
    for item in items:
        assessment = assessments[item.name]
        computed = governance.computed_sharepoint_fields(assessment, ctx.as_of, owner_by_item.get(item.name), policy)
        changes = computed_changes(policy, computed, item.fields)
        if changes:
            pending.append((item, changes))

    report_distribution(policy, evaluation, assessments)
    print(f"   changes: {len(pending)} items / {sum(len(c) for _, c in pending)} fields"
          f"{' (dry run, nothing written)' if ctx.dry_run else ''}")
    if ctx.dry_run:
        return

    written = 0
    for item, changes in pending:
        try:
            graph.request("PATCH", f"{GRAPH}/sites/{site_id}/lists/{list_id}/items/{item.item_id}/fields", changes)
            written += 1
        except GraphError as error:
            ctx.failures.append(f"[{label}] {item.name} (item {item.item_id}): {error}")
    print(f"   written: {written} items")

    after = {row["id"]: row.get("fields", {}) for row in graph.pages(
        f"{GRAPH}/sites/{site_id}/lists/{list_id}/items?$expand=fields&$top=999")}
    mismatches = 0
    for item in items:
        assessment = assessments[item.name]
        computed = governance.computed_sharepoint_fields(assessment, ctx.as_of, owner_by_item.get(item.name), policy)
        remaining = computed_changes(policy, computed, after.get(item.item_id, {}))
        if remaining:
            mismatches += 1
            ctx.failures.append(f"[{label}] verification: {item.name} still differs in {', '.join(remaining)}")
    print(f"   verified: {len(items) - mismatches} of {len(items)} files match the computed values")


def report_distribution(policy: Policy, evaluation: governance.Evaluation, assessments: Mapping[str, governance.Assessment]) -> None:
    quality = Counter(policy.label("dataQualityStatus", a.data_quality) for a in assessments.values())
    conflicts = Counter(policy.label("conflictStatus", a.conflict) for a in assessments.values())
    scores = [a.trust_score for a in assessments.values()]
    kinds = Counter(f.kind for f in evaluation.pair_findings)
    duplicates = Counter(a.duplicate_kind for a in assessments.values() if a.duplicate_kind)
    print("   DataQualityStatus: " + ", ".join(f"{k}={v}" for k, v in sorted(quality.items())))
    print("   ConflictStatus:    " + ", ".join(f"{k}={v}" for k, v in sorted(conflicts.items())))
    print(f"   AIReady: {sum(1 for a in assessments.values() if a.ai_ready)}; TrustScore min {min(scores)}, "
          f"avg {sum(scores) / len(scores):.1f}, max {max(scores)}")
    print(f"   pairs: exact {kinds.get('exact', 0)}, near {kinds.get('near', 0)}, conflict candidates {kinds.get('conflict', 0)}; "
          f"duplicate members exact {duplicates.get('exact', 0)}, near {duplicates.get('near', 0)}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Evaluate and report without writing.")
    parser.add_argument("--site", help="Only this siteId from governance-targets.json.")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    targets = load_json(TARGETS_PATH)
    tenant_id = targets["tenantId"]
    policy = Policy.load(POLICY_PATH, VOCABULARY_PATH)
    analytics = load_json(ANALYTICS_PATH)
    extensions = {ext.lower() for ext in analytics["extraction"]["supportedExtensions"]}
    spec = importlib.util.spec_from_file_location("api_analytics_text", TEXT_MODULE_PATH)
    text_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(text_module)
    sites = [site for site in targets["sites"] if not args.site or site["siteId"] == args.site]
    if not sites:
        raise SystemExit(f"No site with siteId '{args.site}' in {TARGETS_PATH.name}.")

    graph = Graph(cli_token("https://graph.microsoft.com", tenant_id))
    failures: list[str] = []
    with ReadOnlyApp(graph, tenant_id) as read_token:
        ctx = RunContext(graph=graph, policy=policy, as_of=datetime.now(timezone.utc).date(), extensions=extensions,
                         tfidf=analytics["tfidf"], text_module=text_module, read_token=read_token,
                         dry_run=args.dry_run, failures=failures)
        for site in sites:
            site_id = graph.get(f"{GRAPH}/sites/{site['graphPath']}")["id"]
            for library_name in site["libraries"]:
                process_library(ctx, site_id, site["siteId"], library_name)
    if failures:
        for failure in failures:
            print(f"FAILED: {failure}", file=sys.stderr)
        print(f"{len(failures)} governance field failure(s).", file=sys.stderr)
        return 1
    print("Governance fields " + ("evaluated (dry run)." if args.dry_run else "written and verified."))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
