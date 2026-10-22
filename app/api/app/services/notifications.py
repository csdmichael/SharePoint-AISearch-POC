"""Owner notification drafts. Drafts need approval before send. Sending is refused unless the mode allows delivery:
dryRun records the outcome in the outbox only; sendAsReviewer calls Graph sendMail as the configured sender.
All text (fallbacks, refusal and delivery messages) comes from notifications.json."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from app.clients.graph import GraphClient
from app.core.config import NotificationTemplate, Settings
from app.core.errors import ApiError, ConflictError, NotFoundError, UpstreamError
from app.core.governance import Governance
from app.services.documents import document_summary
from app.services.hygiene import HygieneDoc, HygieneService
from app.services.library import LibraryService
from app.services.views import iso

OUTBOX_SCHEMA = "sp-acl-outbox/v1"
PLACEHOLDER = re.compile(r"\{([A-Za-z]+)\}")
STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_DRY_RUN = "dryRunRecorded"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
MODE_DRY_RUN = "dryRun"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OutboxStore:
    """JSON outbox file. Writes are atomic (temp file, then replace) and serialized inside the process."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError(f"The notification outbox at {self._path} could not be read.", code="outbox_unreadable",
                           status_code=500) from exc
        records = payload.get("notifications") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ApiError("The notification outbox has an unexpected layout.", code="outbox_unreadable",
                           status_code=500)
        return records

    def _write(self, records: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        document = {"schemaVersion": OUTBOX_SCHEMA, "notifications": records}
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self._path)

    def read(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read()

    def update(self, mutate: Callable[[list[dict[str, Any]]], Any]) -> Any:
        with self._lock:
            records = self._read()
            result = mutate(records)
            self._write(records)
            return result


class NotificationService:
    def __init__(
        self,
        *,
        settings: Settings,
        governance: Governance,
        graph: GraphClient,
        libraries: LibraryService,
        hygiene: HygieneService,
        store: OutboxStore,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._settings = settings
        self._governance = governance
        self._graph = graph
        self._libraries = libraries
        self._hygiene = hygiene
        self._store = store
        self._clock = clock
        self._messages = settings.notifications.messages

    @property
    def mode(self) -> str:
        return self._settings.notifications.mode

    def templates(self) -> list[str]:
        return sorted(self._settings.notifications.templates)

    def create_drafts(
        self,
        *,
        template_id: str,
        finding_id: str | None,
        document_ids: Sequence[str] | None,
        caller_upn: str | None,
    ) -> dict[str, Any]:
        config = self._settings.notifications
        template = config.templates.get(template_id)
        if template is None:
            raise NotFoundError(f"Notification template '{template_id}' is not configured.")
        targets = self._targets(finding_id, document_ids)
        finding_title = self._finding_title(finding_id)
        now = self._clock()
        window_start = now - timedelta(hours=config.dedupeWindowHours)
        existing = self._store.read()
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for doc, reason in targets:
            view = doc.view
            owner_upn = view.get("knowledgeOwner")
            if not owner_upn:
                skipped.append({"documentId": view["id"], "reason": "missingOwner"})
                continue
            dedupe_key = f"{template_id}|{view['id']}|{owner_upn}"
            if self._recent(existing + created, dedupe_key, window_start):
                skipped.append({"documentId": view["id"], "reason": "withinDedupeWindow"})
                continue
            if len(created) >= config.maxPerBatch:
                skipped.append({"documentId": view["id"], "reason": "batchLimit"})
                continue
            values = self._values(doc, reason, finding_title, caller_upn, now)
            subject, body = self._render(template, values)
            created.append({
                "id": uuid.uuid4().hex,
                "status": STATUS_DRAFT,
                "mode": config.mode,
                "templateId": template_id,
                "findingId": finding_id,
                "documentId": view["id"],
                "documentTitle": view["title"],
                "documentUrl": view["webUrl"],
                "libraryTitle": view["libraryTitle"],
                "ownerUpn": owner_upn,
                "ownerName": values["ownerName"],
                "to": [owner_upn],
                "subject": subject,
                "body": body,
                "reason": reason,
                "dedupeKey": dedupe_key,
                "createdAt": now.isoformat(),
                "createdBy": caller_upn,
                "approvedAt": None,
                "approvedBy": None,
                "sentAt": None,
                "sentBy": None,
                "delivery": None,
                "error": None,
            })
        if created:
            self._store.update(lambda records: records.extend(created))
        return {
            "templateId": template_id,
            "findingId": finding_id,
            "mode": config.mode,
            "created": created,
            "skipped": skipped,
        }

    def _targets(self, finding_id: str | None, document_ids: Sequence[str] | None) -> list[tuple[HygieneDoc, str]]:
        if finding_id:
            return [(match.doc, match.reason) for match in self._hygiene.matches(finding_id)]
        targets: list[tuple[HygieneDoc, str]] = []
        for document_id in document_ids or []:
            corpus, item = self._libraries.item(document_id)
            if item.kind != "file":
                raise NotFoundError(f"{document_id} is not a document.")
            targets.append((HygieneDoc(corpus=corpus, item=item, view=document_summary(corpus, item),
                                       expiry=None, duplicate_roles=[],
                                       owner_upn=(item.fields.get("knowledgeOwner") or {}).get("upn")),
                            self._messages.selectedReason))
        return targets

    def _finding_title(self, finding_id: str | None) -> str:
        if not finding_id:
            return self._messages.selectedFindingTitle
        for definition in self._governance.findings:
            if definition["id"] == finding_id:
                return str(definition["title"])
        raise NotFoundError(f"Hygiene finding '{finding_id}' does not exist.")

    @staticmethod
    def _recent(records: list[dict[str, Any]], dedupe_key: str, window_start: datetime) -> bool:
        for record in records:
            if record.get("dedupeKey") != dedupe_key or record.get("status") == STATUS_FAILED:
                continue
            created = datetime.fromisoformat(str(record["createdAt"]))
            if created >= window_start:
                return True
        return False

    def _values(self, doc: HygieneDoc, reason: str, finding_title: str, caller_upn: str | None,
                now: datetime) -> dict[str, str]:
        view = doc.view
        messages = self._messages
        owner = view.get("knowledgeOwner") or ""
        return {
            "ownerName": str(view.get("ownerDisplayName") or owner or messages.ownerFallback),
            "documentTitle": str(view["title"]),
            "documentUrl": str(view["webUrl"]),
            "findingTitle": finding_title,
            "reviewDate": str(view.get("reviewDate") or messages.missingValue),
            "expirationDate": str(view.get("expirationDate") or messages.missingValue),
            "reviewerName": caller_upn or messages.reviewerFallback,
            "reason": reason,
            "generatedAt": iso(now) or "",
        }

    def _render(self, template: NotificationTemplate, values: dict[str, str]) -> tuple[str, str]:
        def fill(text: str) -> str:
            return PLACEHOLDER.sub(lambda match: values.get(match.group(1), self._messages.unknownValue), text)

        return fill(template.subject), fill(template.body)

    def list(self, status: str | None) -> list[dict[str, Any]]:
        records = self._store.read()
        if status:
            records = [record for record in records if record.get("status") == status]
        return sorted(records, key=lambda record: str(record.get("createdAt")), reverse=True)

    def get(self, notification_id: str) -> dict[str, Any]:
        for record in self._store.read():
            if record.get("id") == notification_id:
                return record
        raise NotFoundError(f"Notification '{notification_id}' does not exist.")

    def approve(self, notification_id: str, caller_upn: str | None) -> dict[str, Any]:
        def mutate(records: list[dict[str, Any]]) -> dict[str, Any]:
            record = self._find(records, notification_id)
            if record["status"] != STATUS_DRAFT:
                raise ConflictError(f"Only drafts can be approved; this one is {record['status']}.",
                                    code="invalid_state")
            record["status"] = STATUS_APPROVED
            record["approvedAt"] = self._clock().isoformat()
            record["approvedBy"] = caller_upn
            return dict(record)

        return self._store.update(mutate)

    def send(self, notification_id: str, caller_upn: str | None) -> dict[str, Any]:
        record = self.get(notification_id)
        if record["status"] != STATUS_APPROVED:
            raise ConflictError("Only approved notifications can be sent.", code="not_approved")
        config = self._settings.notifications
        if config.mode == MODE_DRY_RUN:
            return self._record_outcome(notification_id, STATUS_DRY_RUN, caller_upn,
                                        delivery=self._messages.sendRefused.format(mode=config.mode))
        message = {
            "subject": record["subject"],
            "body": {"contentType": "Text", "content": record["body"]},
            "toRecipients": [{"emailAddress": {"address": address}} for address in record["to"]],
        }
        try:
            self._graph.send_mail(config.sender.userPrincipalName, message)
        except UpstreamError as exc:
            self._record_outcome(notification_id, STATUS_FAILED, caller_upn, error=exc.message)
            raise
        return self._record_outcome(notification_id, STATUS_SENT, caller_upn, delivery=self._messages.sendDelivery)

    def _record_outcome(self, notification_id: str, status: str, caller_upn: str | None, *,
                        delivery: str | None = None, error: str | None = None) -> dict[str, Any]:
        def mutate(records: list[dict[str, Any]]) -> dict[str, Any]:
            record = self._find(records, notification_id)
            record["status"] = status
            record["sentAt"] = self._clock().isoformat()
            record["sentBy"] = caller_upn
            record["delivery"] = delivery
            record["error"] = error
            return dict(record)

        return self._store.update(mutate)

    @staticmethod
    def _find(records: list[dict[str, Any]], notification_id: str) -> dict[str, Any]:
        for record in records:
            if record.get("id") == notification_id:
                return record
        raise NotFoundError(f"Notification '{notification_id}' does not exist.")
