"""Live analytics over a library corpus: duplicates, expiry, anomalies and exposure.

Each result is computed from SharePoint metadata, role assignments and sharing links, and from the text of the
documents Graph returns. Results are memoized per corpus, so they live for the library cache TTL.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from app.analytics.anomaly import AnomalyRow, score_items
from app.analytics.duplicates import DupDoc, DuplicateResult, analyze_duplicates
from app.analytics.expiry import ExpiryDoc, ExpiryFinding, analyze_expiry
from app.analytics.text import content_digest, numeric_fingerprint
from app.core.config import Settings
from app.core.governance import Governance
from app.domain.documents import authoritative_claim
from app.domain.principals import PrincipalKind
from app.services.corpus import LibraryCorpus
from app.services.exposure import ExposureService
from app.services.views import item_view


class AnalyticsService:
    def __init__(self, *, settings: Settings, governance: Governance, exposure: ExposureService) -> None:
        self._settings = settings
        self._governance = governance
        self._exposure = exposure

    def as_of(self) -> date:
        configured = self._settings.api.hygiene.asOfDate
        return configured if configured is not None else datetime.now(timezone.utc).date()

    def _key(self, name: str) -> tuple[str, str]:
        return (name, self.as_of().isoformat())

    # ---- duplicates ----------------------------------------------------------------------------------------

    def duplicate_docs(self, corpus: LibraryCorpus) -> list[DupDoc]:
        def build() -> list[DupDoc]:
            policy = self._governance.similarity
            files = corpus.snapshot.files
            corpus.prefetch_text(files)
            docs: list[DupDoc] = []
            for item in files:
                result = corpus.text(item)
                if result.status != "ok" or not result.text:
                    continue
                fields = item.fields
                owner_scope = (
                    fields.get("productFamily") or "",
                    fields.get("processArea") or "",
                    fields.get("documentType") or "",
                )
                docs.append(
                    DupDoc(
                        key=item.item_id,
                        name=item.name,
                        title=fields.get("title") or item.name,
                        artifact_id=fields.get("artifactId") or item.item_id,
                        authoritative=authoritative_claim(fields, self._governance),
                        effective=fields.get("effectiveDate"),
                        text=result.text,
                        digest=content_digest(result.text, policy["hashAlgorithm"]),
                        fingerprint=numeric_fingerprint(result.text, policy["numberPattern"]),
                        scope=owner_scope,
                    )
                )
            return docs

        return corpus.memo(self._key("dup-docs"), build)

    def duplicates(self, corpus: LibraryCorpus) -> DuplicateResult:
        def build() -> DuplicateResult:
            analytics = self._settings.analytics
            policy = self._governance.similarity
            cosine = (
                analytics.duplicates.cosineThreshold
                if analytics.duplicates.cosineThreshold is not None
                else float(policy["nearDuplicateCosine"])
            )
            distance = (
                analytics.duplicates.distanceThreshold
                if analytics.duplicates.distanceThreshold is not None
                else round(1.0 - cosine, 6)
            )
            messages = self._governance.message_templates
            return analyze_duplicates(
                self.duplicate_docs(corpus),
                clustering=analytics.duplicates,
                tfidf=analytics.tfidf,
                cosine_threshold=cosine,
                distance_threshold=distance,
                conflict_cosine=float(policy["conflictCandidateCosine"]),
                vector_char_limit=int(policy["embeddingCharacterLimit"]),
                exact_reason=str(messages["duplicate"]["exact"]),
                near_reason=str(messages["duplicate"]["near"]),
                conflict_reason=str(messages["conflict"]["candidate"]),
            )

        return corpus.memo(self._key("duplicates"), build)

    def duplicate_roles(self, corpus: LibraryCorpus) -> dict[str, list[dict[str, Any]]]:
        """item id -> duplicate cluster memberships (kind, cluster id, canonical, whether canonical)."""

        def build() -> dict[str, list[dict[str, Any]]]:
            roles: dict[str, list[dict[str, Any]]] = defaultdict(list)
            result = self.duplicates(corpus)
            for cluster in (*result.exact, *result.near):
                for member in cluster.members:
                    roles[member].append({
                        "kind": cluster.kind,
                        "clusterId": cluster.cluster_id,
                        "canonical": cluster.canonical,
                        "isCanonical": member == cluster.canonical,
                        "similarity": {"min": cluster.similarity_min, "mean": cluster.similarity_mean},
                    })
            return dict(roles)

        return corpus.memo(self._key("duplicate-roles"), build)

    # ---- expiry --------------------------------------------------------------------------------------------

    def expiry(self, corpus: LibraryCorpus) -> dict[str, ExpiryFinding]:
        def build() -> dict[str, ExpiryFinding]:
            files = corpus.snapshot.files
            corpus.prefetch_text(files)
            docs: list[ExpiryDoc] = []
            for item in files:
                result = corpus.text(item)
                fields = item.fields
                docs.append(
                    ExpiryDoc(
                        key=item.item_id,
                        name=item.name,
                        title=fields.get("title") or item.name,
                        lifecycle=fields.get("lifecycleStatus"),
                        metadata_expiration=fields.get("expirationDate"),
                        metadata_review=fields.get("reviewDate"),
                        text=result.text if result.status == "ok" else None,
                    )
                )
            return analyze_expiry(docs, as_of=self.as_of(), config=self._settings.analytics.expiry)

        return corpus.memo(self._key("expiry"), build)

    # ---- anomalies -----------------------------------------------------------------------------------------

    def anomaly_features(self, corpus: LibraryCorpus) -> dict[str, dict[str, float]]:
        def build() -> dict[str, dict[str, float]]:
            as_of = self.as_of()
            anonymous_scopes = set(self._settings.analytics.exposure.anonymousLinkScopes)
            cluster_sizes: dict[str, int] = {}
            duplicates = self.duplicates(corpus)
            for cluster in (*duplicates.exact, *duplicates.near):
                for member in cluster.members:
                    cluster_sizes[member] = max(cluster_sizes.get(member, 1), len(cluster.members))
            files = corpus.snapshot.files
            corpus.prefetch_links(files)
            rows: dict[str, dict[str, float]] = {}
            for item in files:
                entries = corpus.snapshot.entries_for(item)
                links = corpus.links(item)
                effective = entries + links
                modified = item.modified.date() if item.modified else as_of
                rows[item.item_id] = {
                    "daysSinceModified": float(max(0, (as_of - modified).days)),
                    "principalCount": float(len({entry.principal.key for entry in effective})),
                    "directGrantCount": float(
                        sum(1 for entry in entries if entry.principal.kind is PrincipalKind.USER and not entry.inherited)
                    ),
                    "brokenInheritance": 1.0 if item.unique else 0.0,
                    "anonymousLink": 1.0 if any(link.link_scope in anonymous_scopes for link in links) else 0.0,
                    "everyoneClaim": 1.0 if any(entry.principal.kind is PrincipalKind.CLAIMS for entry in effective)
                    else 0.0,
                    "duplicateClusterSize": float(cluster_sizes.get(item.item_id, 1)),
                }
            return rows

        return corpus.memo(self._key("anomaly-features"), build)

    def anomalies(self, corpus: LibraryCorpus) -> list[dict[str, Any]]:
        def build() -> list[dict[str, Any]]:
            config = self._settings.analytics.anomaly
            rows: list[AnomalyRow] = score_items(self.anomaly_features(corpus), config=config)
            by_id = {item.item_id: item for item in corpus.snapshot.files}
            output: list[dict[str, Any]] = []
            for row in rows[: config.topN]:
                item = by_id[row.key]
                top = sorted(row.contributions.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
                output.append({
                    "item": item_view(corpus, item),
                    "title": item.fields.get("title") or item.name,
                    "rank": row.rank,
                    "score": row.score,
                    "isAnomaly": row.is_anomaly,
                    "features": row.features,
                    "topContributions": [{"feature": name, "share": share} for name, share in top],
                })
            return output

        return corpus.memo(self._key("anomalies"), build)

    def anomaly_rows(self, corpus: LibraryCorpus) -> dict[str, dict[str, Any]]:
        return {row["item"]["id"]: row for row in self.anomalies(corpus)}

    def exposure(self, corpus: LibraryCorpus) -> list[dict[str, Any]]:
        return self._exposure.findings(corpus)
