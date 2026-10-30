"""Where the reviewed artifact is written. GraphPublisher writes to the configured SharePoint library with the API's
managed identity; DemoPublisher keeps the same artifact in a local folder so the workflow runs without write access.

Both implement SharePointPublisher, so the service never knows which one it talks to. The demo implementation is
labelled as such in every response and is never selected unless knowledge-capture.json says publish.mode = demo.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.clients.graph import GraphClient
from app.clients.sharepoint import SharePointClient
from app.core.config import KnowledgePublishConfig, SiteSettings
from app.core.errors import ApiError, NotFoundError, UpstreamError, ValidationFailedError
from app.core.governance import Governance
from app.knowledge.models import ARTIFACT_ID_PATTERN

OWNER_LOOKUP_FIELD = "KnowledgeOwnerLookupId"
NAME_CONFLICT = "name_conflict"
FORBIDDEN = "upstream_forbidden"
# Logical column keys a library must have before governed knowledge can be published into it.
REQUIRED_COLUMN_KEYS: tuple[str, ...] = (
    "artifactId", "lifecycleStatus", "authoritative", "reviewDate", "sensitivity", "aiReady", "knowledgeOwner",
    "documentIteration",
)


@dataclass(frozen=True)
class ArtifactPackage:
    artifact_id: str
    file_name: str
    docx: bytes
    markdown: str
    fields: Mapping[str, Any]
    owner_upn: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class PublishedDocument:
    mode: str
    file_name: str
    web_url: str | None
    site_name: str
    library_name: str
    folder: str
    applied_fields: dict[str, Any]
    skipped_fields: list[str]
    warnings: list[str]


class SharePointPublisher(Protocol):
    mode: str

    def publish(self, package: ArtifactPackage) -> PublishedDocument: ...


class DemoStore:
    """Local, file-based stand-in for the SharePoint library (demo mode only)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _folder(self, artifact_id: str) -> Path:
        if not ARTIFACT_ID_PATTERN.match(artifact_id):
            raise NotFoundError("The knowledge artifact was not found.")
        return self._root / artifact_id

    def save(self, package: ArtifactPackage) -> None:
        folder = self._folder(package.artifact_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / package.file_name).write_bytes(package.docx)
        (folder / "document.md").write_text(package.markdown, encoding="utf-8")
        record = {**package.metadata, "fileName": package.file_name, "fields": dict(package.fields)}
        (folder / "metadata.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    def metadata(self, artifact_id: str) -> dict[str, Any]:
        path = self._folder(artifact_id) / "metadata.json"
        if not path.is_file():
            raise NotFoundError("The knowledge artifact was not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def document(self, artifact_id: str) -> tuple[str, bytes]:
        record = self.metadata(artifact_id)
        return str(record["fileName"]), (self._folder(artifact_id) / str(record["fileName"])).read_bytes()

    def all_metadata(self) -> list[dict[str, Any]]:
        if not self._root.is_dir():
            return []
        records = []
        for path in sorted(self._root.glob("*/metadata.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return records

    def remove(self, artifact_id: str) -> None:
        shutil.rmtree(self._folder(artifact_id), ignore_errors=True)


class DemoPublisher:
    mode = "demo"

    def __init__(self, store: DemoStore, config: KnowledgePublishConfig, site: SiteSettings) -> None:
        self._store = store
        self._config = config
        self._site = site

    def publish(self, package: ArtifactPackage) -> PublishedDocument:
        self._store.save(package)
        return PublishedDocument(
            mode=self.mode,
            file_name=package.file_name,
            web_url=None,
            site_name=self._site.display_name,
            library_name=self._config.libraryName,
            folder=self._config.folder,
            applied_fields={name: value for name, value in package.fields.items()},
            skipped_fields=[],
            warnings=["Demo mode: the document was saved locally and nothing was written to SharePoint."],
        )


class GraphPublisher:
    mode = "graph"

    def __init__(
        self,
        *,
        config: KnowledgePublishConfig,
        governance: Governance,
        site: SiteSettings,
        graph: GraphClient,
        sharepoint: SharePointClient,
    ) -> None:
        self._config = config
        self._governance = governance
        self._site = site
        self._graph = graph
        self._sharepoint = sharepoint

    def publish(self, package: ArtifactPackage) -> PublishedDocument:
        if len(package.docx) > self._config.maxDocumentBytes:
            raise ValidationFailedError(
                "The generated document is larger than the configured limit. Shorten the content and try again.",
                code="document_too_large",
            )
        site_id, drive_id, list_id = self._resolve_library()
        column_names = self._sharepoint.field_names(list_id)
        self._require_governance_columns(column_names)

        fields = dict(package.fields)
        warnings: list[str] = []
        try:
            fields[OWNER_LOOKUP_FIELD] = self._sharepoint.ensure_user_id(package.owner_upn)
        except ApiError as exc:
            raise self._translate(exc, "resolve the knowledge owner in SharePoint") from None
        writable = {name: value for name, value in fields.items() if name in column_names or name == OWNER_LOOKUP_FIELD}
        skipped = sorted(name for name in fields if name not in writable)
        if skipped:
            warnings.append("These columns do not exist on the library and were not written: " + ", ".join(skipped))

        uploaded = self._upload(drive_id, package)
        item_id = str(uploaded["id"])
        try:
            self._graph.update_item_fields(drive_id, item_id, writable)
        except ApiError as exc:
            removed = self._rollback(drive_id, item_id)
            detail = "The document was removed again." if removed else "The uploaded document could not be removed; delete it from the library."
            raise UpstreamError(
                "SharePoint",
                f"the document was uploaded but its governance metadata could not be written, so publishing was "
                f"cancelled. {detail} ({exc.message})",
                code="sharepoint_metadata_failed",
                status_code=502,
            ) from None
        return PublishedDocument(
            mode=self.mode,
            file_name=str(uploaded.get("name") or package.file_name),
            web_url=uploaded.get("webUrl"),
            site_name=self._site.display_name,
            library_name=self._config.libraryName,
            folder=self._config.folder,
            applied_fields=writable,
            skipped_fields=skipped,
            warnings=warnings,
        )

    def _resolve_library(self) -> tuple[str, str, str]:
        try:
            site = self._graph.site(self._site.host, self._site.server_relative_path)
            site_id = str(site["id"])
            wanted = self._config.libraryName.lower()
            library = next(
                (row for row in self._graph.site_lists(site_id) if str(row.get("displayName", "")).lower() == wanted),
                None,
            )
            if library is None:
                raise ValidationFailedError(
                    f"The library '{self._config.libraryName}' was not found on {self._site.display_name}. "
                    "Check publish.libraryName in knowledge-capture.json.",
                    code="library_not_found",
                )
            list_id = str(library["id"])
            drive = self._graph.library_drive(site_id, list_id)
            return site_id, str(drive["id"]), list_id
        except ApiError as exc:
            if isinstance(exc, ValidationFailedError):
                raise
            raise self._translate(exc, "open the target library") from None

    def _require_governance_columns(self, column_names: set[str]) -> None:
        missing = [
            self._governance.column(key) for key in REQUIRED_COLUMN_KEYS if self._governance.column(key) not in column_names
        ]
        if missing:
            raise ValidationFailedError(
                f"The library '{self._config.libraryName}' is missing the governance columns {', '.join(missing)}. "
                "Add them with scripts\\Add-GovernanceColumnsToLibrary.ps1 before publishing knowledge.",
                code="library_not_governed",
            )

    def _upload(self, drive_id: str, package: ArtifactPackage) -> dict[str, Any]:
        folder = self._config.folder.strip("/")
        stem, _, extension = package.file_name.rpartition(".")
        names = [package.file_name, f"{stem} ({package.artifact_id}).{extension}"]
        for index, name in enumerate(names):
            try:
                return self._graph.upload_file(drive_id, f"{folder}/{name}", package.docx)
            except ApiError as exc:
                if exc.code == NAME_CONFLICT and index == 0:
                    continue
                if exc.code == NAME_CONFLICT:
                    raise ValidationFailedError(
                        "A knowledge document with this title already exists. Change the title and publish again.",
                        code="document_exists",
                    ) from None
                raise self._translate(exc, "upload the knowledge document") from None
        raise UpstreamError("SharePoint", "the document could not be uploaded", code="sharepoint_write_failed")

    def _rollback(self, drive_id: str, item_id: str) -> bool:
        try:
            self._graph.delete_drive_item(drive_id, item_id)
            return True
        except ApiError:
            return False

    def _translate(self, error: ApiError, action: str) -> ApiError:
        if error.code == FORBIDDEN:
            return UpstreamError(
                "SharePoint",
                f"write access was denied while trying to {action}. The API's managed identity needs the "
                f"Sites.Selected 'write' role on {self._site.display_name} (see Save to Knowledge Demo in the README).",
                code="sharepoint_write_denied",
                status_code=502,
            )
        if isinstance(error, UpstreamError) and error.code != "sharepoint_write_failed":
            return UpstreamError(
                "SharePoint", f"could not {action}. {error.message.split(': ', 1)[-1]}",
                code="sharepoint_write_failed", status_code=error.status_code,
            )
        return error
