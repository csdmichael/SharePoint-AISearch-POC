"""Unit tests for the Trusted Knowledge governance package, using the stdlib unittest module only.

Corpus data and expected values live in tests/fixtures/*.json. This module holds no expected values.
Run from the repository root: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import hashlib
import html
import inspect
import json
import re
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

TESTS_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = TESTS_DIRECTORY.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.trusted_knowledge import governance, hygiene, retrieval, similarity  # noqa: E402
from scripts.trusted_knowledge.policy import Policy  # noqa: E402


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


EXPECTED = _read_json(TESTS_DIRECTORY / "fixtures" / "apexdrive-expectations.json")
CORPUS_DOCUMENTS: list[dict[str, Any]] = _read_json(
    TESTS_DIRECTORY / "fixtures" / "apexdrive-corpus.json"
)["documents"]
AS_OF = date.fromisoformat(EXPECTED["asOf"])
GENERATED_AT = datetime.fromisoformat(EXPECTED["generatedAt"])
OWNER_DISPLAY_NAME = EXPECTED["ownerDisplayName"]


def _repository_path(key: str) -> Path:
    return REPOSITORY_ROOT / EXPECTED["repository"][key]


def _load_policy() -> Policy:
    return Policy.load(_repository_path("policy"), _repository_path("vocabulary"))


def _corpus_documents(overrides: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """A deep copy of the corpus with each override merged into the declared values of its document."""
    documents = copy.deepcopy(CORPUS_DOCUMENTS)
    by_alias = {document["alias"]: document for document in documents}
    for override in overrides:
        by_alias[override["alias"]]["declared"].update(override.get("declared", {}))
    return documents


def _mutate(document: Any, mutation: Mapping[str, Any]) -> None:
    path = list(mutation["path"])
    parent = document
    for part in path[:-1]:
        parent = parent[part]
    last = path[-1]
    if mutation["op"] == "delete":
        del parent[last]
    elif mutation["op"] == "set":
        parent[last] = mutation["value"]
    elif mutation["op"] == "deleteItem":
        match = mutation["match"]
        parent[last] = [item for item in parent[last] if not all(item.get(k) == v for k, v in match.items())]
    else:
        raise ValueError(f"Unknown mutation {mutation['op']}")


class Corpus:
    """The corpus evaluated under a policy. Documents are addressed by alias."""

    def __init__(self, policy: Policy, documents: list[dict[str, Any]]) -> None:
        self.policy = policy
        self._by_alias = {document["alias"]: document for document in documents}
        declarations = [governance.Declared.from_manifest(document, policy) for document in documents]
        measurements = {
            declared.key: governance.Measurement.from_manifest(document, policy)
            for declared, document in zip(declarations, documents)
        }
        self.evaluation = governance.evaluate(declarations, measurements, policy, AS_OF)
        self._assessments = self.evaluation.by_key()

    def aliases(self) -> list[str]:
        return list(self._by_alias)

    def file(self, alias: str) -> str:
        return self._by_alias[alias]["declared"]["FileLeafRef"]

    def files(self, aliases: Iterable[str]) -> list[str]:
        return [self.file(alias) for alias in aliases]

    def assessment(self, alias: str) -> governance.Assessment:
        return self._assessments[self.file(alias)]

    def title(self, alias: str) -> str:
        return self._by_alias[alias]["declared"]["Title"]

    def url(self, alias: str) -> str:
        return self._by_alias[alias]["documentUrl"]

    def urls(self) -> dict[str, str]:
        return {self.file(alias): self.url(alias) for alias in self._by_alias}

    def fields(self, alias: str) -> dict[str, Any]:
        """SharePoint values of a document: declared columns merged with the computed columns."""
        assessment = self.assessment(alias)
        computed = governance.computed_sharepoint_fields(assessment, AS_OF, OWNER_DISPLAY_NAME, self.policy)
        return {**assessment.declared.values, **computed}

    def record(self, alias: str) -> dict[str, Any]:
        """A search index record for a document, keyed by search index field names."""
        record = governance.project_to_search(self.fields(alias), self.policy)
        record[retrieval.SOURCE_TITLE_KEY] = self.title(alias)
        record[retrieval.SOURCE_CITATION_KEY] = self.url(alias)
        return record


class PolicyLoadingTests(unittest.TestCase):
    def test_repository_configuration_loads(self):
        self.assertIsInstance(_load_policy(), Policy)

    def test_load_takes_explicit_paths_without_defaults(self):
        parameters = inspect.signature(Policy.load).parameters
        for name in ("policy_path", "vocabulary_path"):
            with self.subTest(parameter=name):
                self.assertIs(parameters[name].default, inspect.Parameter.empty)


class PolicyAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = _load_policy()
        cls.expected = EXPECTED["policyAccessors"]

    def test_column_and_index_field_names(self) -> None:
        for key, column in self.expected["column"].items():
            with self.subTest(column=key):
                self.assertEqual(self.policy.column(key), column)
        for key, field_name in self.expected["indexField"].items():
            with self.subTest(indexField=key):
                self.assertEqual(self.policy.index_field(key), field_name)
        for key, field_name in self.expected["searchField"].items():
            with self.subTest(searchField=key):
                self.assertEqual(self.policy.search_field(key), field_name)

    def test_labels_messages_and_rendering(self) -> None:
        for group, entries in self.expected["label"].items():
            for key, text in entries.items():
                with self.subTest(label=f"{group}.{key}"):
                    self.assertEqual(self.policy.label(group, key), text)
        for group, entries in self.expected["message"].items():
            for key, text in entries.items():
                with self.subTest(message=f"{group}.{key}"):
                    self.assertEqual(self.policy.message(group, key), text)
        case = self.expected["render"]
        self.assertEqual(self.policy.render(case["template"], **case["values"]), case["expected"])

    def test_choices(self) -> None:
        for key, values in self.expected["choices"].items():
            with self.subTest(choices=key):
                self.assertEqual(list(self.policy.choices(key)), values)

    def test_trust_scoring_values(self) -> None:
        for key, points in self.expected["trustWeight"].items():
            self.assertEqual(self.policy.trust_weight(key), points)
        for key, points in self.expected["trustPenalty"].items():
            self.assertEqual(self.policy.trust_penalty(key), points)
        self.assertEqual(list(self.policy.trust_bounds()), self.expected["trustBounds"])

    def test_eligibility_and_rule_values(self) -> None:
        self.assertEqual(self.policy.required_lifecycle(), self.expected["requiredLifecycle"])
        self.assertIs(self.policy.required_authoritative(), self.expected["requiredAuthoritative"])
        self.assertEqual(list(self.policy.trusted_sensitivity()), self.expected["trustedSensitivity"])
        self.assertEqual(list(self.policy.approved_source_systems()), self.expected["approvedSourceSystems"])
        self.assertEqual(list(self.policy.stale_lifecycle_labels()), self.expected["staleLifecycleLabels"])
        self.assertEqual(self.policy.authoritative_claim_label(), self.expected["authoritativeClaimLabel"])
        self.assertEqual(list(self.policy.required_when_published()), self.expected["requiredWhenPublished"])

    def test_similarity_settings(self) -> None:
        self.assertEqual(self.policy.near_duplicate_cosine(), self.expected["nearDuplicateCosine"])
        self.assertEqual(self.policy.conflict_candidate_cosine(), self.expected["conflictCandidateCosine"])
        self.assertEqual(self.policy.embedding_character_limit(), self.expected["embeddingCharacterLimit"])
        self.assertEqual(self.policy.hash_algorithm(), self.expected["hashAlgorithm"])
        self.assertIsInstance(self.policy.number_pattern(), re.Pattern)
        self.assertEqual(self.policy.number_pattern().pattern, self.expected["numberPattern"])
        self.assertEqual(self.policy.whitespace_pattern().pattern, self.expected["whitespacePattern"])

    def test_classification_suggestion_and_hygiene_settings(self) -> None:
        for key, value in self.expected["classificationDefault"].items():
            self.assertEqual(self.policy.classification_default(key), value)
        self.assertIs(self.policy.product_family_matches_choices(), self.expected["productFamilyMatchesChoices"])
        self.assertEqual(self.policy.suggestion_defaults(), self.expected["suggestionDefaults"])
        self.assertIs(self.policy.requires_owner_review(), self.expected["suggestionDefaults"]["requiresOwnerReview"])
        self.assertEqual([metric.key for metric in self.policy.hygiene_metrics()], self.expected["hygieneMetricKeys"])
        self.assertEqual(
            [finding.id for finding in self.policy.hygiene_findings()], self.expected["hygieneFindingIds"]
        )

    def test_retrieval_block_is_read_only(self) -> None:
        with self.assertRaises(TypeError):
            self.policy.retrieval_block()["routing"] = {}


class PolicyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_policy = _read_json(_repository_path("policy"))
        self.raw_vocabulary = _read_json(_repository_path("vocabulary"))

    def test_each_invalid_configuration_is_rejected_with_its_message(self) -> None:
        for case in EXPECTED["policyValidation"]:
            with self.subTest(case=case["name"]):
                policy_document = copy.deepcopy(self.raw_policy)
                vocabulary_document = copy.deepcopy(self.raw_vocabulary)
                target = {"policy": policy_document, "vocabulary": vocabulary_document}[case["document"]]
                for mutation in case["mutations"]:
                    _mutate(target, mutation)
                with self.assertRaisesRegex(ValueError, re.escape(case["message"])):
                    Policy(policy_document, vocabulary_document)

    def test_in_memory_copy_with_one_referenced_label_removed_is_rejected(self) -> None:
        case = EXPECTED["referencedLabelRemoval"]
        vocabulary_document = copy.deepcopy(self.raw_vocabulary)
        del vocabulary_document["labels"][case["group"]][case["key"]]
        with self.assertRaisesRegex(ValueError, re.escape(case["message"])):
            Policy(self.raw_policy, vocabulary_document)


class SimilarityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = _load_policy()
        cls.expected = EXPECTED["similarity"]

    def test_normalize_text_uses_the_whitespace_pattern(self) -> None:
        case = self.expected["normalize"]
        self.assertEqual(similarity.normalize_text(case["input"], self.policy.whitespace_pattern()), case["expected"])

    def test_numeric_signature_uses_the_number_pattern(self) -> None:
        case = self.expected["numericSignature"]
        numbers = similarity.numeric_signature(case["input"], self.policy.number_pattern())
        self.assertEqual(list(numbers), case["expected"])

    def test_content_hash_uses_the_configured_algorithm(self) -> None:
        case = self.expected["hash"]
        self.assertEqual(self.policy.hash_algorithm(), case["algorithm"])
        expected = hashlib.new(case["algorithm"], case["input"].encode("utf-8")).hexdigest()
        self.assertEqual(similarity.content_hash(case["input"], case["algorithm"]), expected)

    def test_cosine_similarity(self) -> None:
        for case in self.expected["cosine"]:
            with self.subTest(left=case["left"], right=case["right"]):
                value = similarity.cosine_similarity(case["left"], case["right"])
                self.assertAlmostEqual(value, case["expected"], delta=self.expected["cosineTolerance"])

    def test_cosine_rejects_vectors_of_different_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, self.expected["dimensionMismatch"]):
            similarity.cosine_similarity([1, 0], [1, 0, 0])

    def test_pair_finding_rejects_unknown_kinds(self) -> None:
        case = self.expected["invalidPairKind"]
        with self.assertRaisesRegex(ValueError, case["message"]):
            similarity.PairFinding(case["kind"], "first.docx", "second.docx", 1.0)

    def test_lineage_link_blocks_near_duplicates_only(self) -> None:
        for name in ("lineage", "control"):
            case = self.expected[name]
            with self.subTest(case=name):
                signals = [self._signal(item) for item in case["signals"]]
                findings = similarity.classify_pairs(
                    signals, self.policy.near_duplicate_cosine(), self.policy.conflict_candidate_cosine()
                )
                self.assertEqual([finding.kind for finding in findings], case["expectedKinds"])

    def test_corpus_pair_findings_match_expectations(self) -> None:
        corpus = Corpus(self.policy, _corpus_documents())
        found = {(frozenset((f.first, f.second)), f.kind) for f in corpus.evaluation.pair_findings}
        expected = {(frozenset(corpus.files((p["first"], p["second"]))), p["kind"]) for p in EXPECTED["pairs"]}
        self.assertEqual(found, expected)

    def test_content_hashes_match_an_independent_computation(self) -> None:
        corpus = Corpus(self.policy, _corpus_documents())
        algorithm = self.policy.hash_algorithm()
        for document in CORPUS_DOCUMENTS:
            with self.subTest(document=document["alias"]):
                normalized = " ".join(document["body"].split())
                expected = hashlib.new(algorithm, normalized.encode("utf-8")).hexdigest()
                self.assertEqual(corpus.assessment(document["alias"]).measurement.content_hash, expected)

    @staticmethod
    def _signal(item: Mapping[str, Any]) -> similarity.Signal:
        return similarity.Signal(
            key=item["key"],
            content_hash=item["contentHash"],
            numeric_signature=tuple(item["numbers"]),
            scope=tuple(item["scope"]),
            authoritative_claim=item["authoritativeClaim"],
            supersedes=item["supersedes"],
            vector=tuple(item["vector"]),
        )


class GovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = _load_policy()
        cls.corpus = Corpus(cls.policy, _corpus_documents())

    def test_document_outcomes(self) -> None:
        for alias, expected in EXPECTED["documents"].items():
            with self.subTest(document=alias):
                assessment = self.corpus.assessment(alias)
                fields = self.corpus.fields(alias)
                self.assertEqual(fields["DataQualityStatus"], expected["dataQualityStatus"])
                self.assertIs(assessment.ai_ready, expected["aiReady"])
                self.assertEqual(assessment.trust_score, expected["trustScore"])
                self.assertEqual(fields["ConflictStatus"], expected["conflictStatus"])
                self.assertEqual(assessment.duplicate_of, self._file_or_none(expected["duplicateOf"]))
                self.assertEqual(assessment.duplicate_kind, expected["duplicateKind"])
                self.assertEqual(
                    sorted(assessment.conflict_with), sorted(self.corpus.files(expected["conflictWith"]))
                )

    def test_trust_reasons_explain_each_component(self) -> None:
        for alias, reasons in EXPECTED["trustReasons"].items():
            with self.subTest(document=alias):
                self.assertEqual(self.corpus.assessment(alias).trust_reasons, reasons)

    def test_ai_ready_blockers(self) -> None:
        for alias, blockers in EXPECTED["blockers"].items():
            with self.subTest(document=alias):
                self.assertEqual(self.corpus.assessment(alias).ai_ready_blockers, blockers)

    def test_duplicate_clusters_have_one_canonical_per_cluster(self) -> None:
        for scenario in EXPECTED["scenarios"]:
            with self.subTest(scenario=scenario["name"]):
                corpus = Corpus(self.policy, _corpus_documents(scenario["overrides"]))
                self.assertIsNone(corpus.assessment(scenario["canonical"]).duplicate_of)
                for alias, target in scenario["duplicateOf"].items():
                    self.assertEqual(corpus.assessment(alias).duplicate_of, corpus.file(target))
                for alias, kind in scenario["duplicateKind"].items():
                    self.assertEqual(corpus.assessment(alias).duplicate_kind, kind)

    def test_manifest_entry_requires_its_declared_columns(self) -> None:
        column = EXPECTED["manifestRequiredColumn"]
        document = copy.deepcopy(CORPUS_DOCUMENTS[0])
        del document["declared"][column]
        with self.assertRaisesRegex(ValueError, re.escape(column)):
            governance.Declared.from_manifest(document, self.policy)

    def test_computed_sharepoint_fields(self) -> None:
        for alias, expected in EXPECTED["computedFields"].items():
            with self.subTest(document=alias):
                fields = self.corpus.fields(alias)
                for name, value in expected["values"].items():
                    self.assertEqual(fields[name], value)
                for name in expected["absent"]:
                    self.assertNotIn(name, fields)
                for file_name in self.corpus.files(expected["conflictWith"]):
                    self.assertIn(file_name, fields["ConflictWith"])
                self.assertEqual(fields["TrustReasons"].splitlines()[-1], expected["lastTrustReason"])

    def test_suggest_metadata_applies_classification_rules(self) -> None:
        choices = self.policy.choices("productFamily")
        for case in EXPECTED["suggestions"]:
            with self.subTest(title=case["title"]):
                suggestion = governance.suggest_metadata(case["text"], case["title"], self.policy, choices)
                self.assertEqual(suggestion, case["expected"])

    def _file_or_none(self, alias: str | None) -> str | None:
        return None if alias is None else self.corpus.file(alias)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = _load_policy()
        cls.corpus = Corpus(cls.policy, _corpus_documents())

    def test_questions_route_to_the_expected_tool(self) -> None:
        for case in EXPECTED["routing"]:
            with self.subTest(question=case["question"]):
                self.assertEqual(retrieval.route_question(case["question"], self.policy), case["tool"])

    def test_base_filters(self) -> None:
        self.assertEqual(retrieval.trusted_base_filter(self.policy), EXPECTED["filters"]["trusted"])
        self.assertEqual(retrieval.governance_base_filter(self.policy), EXPECTED["filters"]["governance"])

    def test_trusted_predicate_selects_the_trusted_documents(self) -> None:
        trusted = [
            alias for alias in self.corpus.aliases()
            if retrieval.is_trusted(self.corpus.record(alias), self.policy)
        ]
        self.assertEqual(trusted, EXPECTED["trustedAliases"])

    def test_exclusion_reasons(self) -> None:
        for alias, reasons in EXPECTED["exclusions"].items():
            with self.subTest(document=alias):
                record = self.corpus.record(alias)
                self.assertEqual(retrieval.exclusion_reasons(record, AS_OF, self.policy), reasons)

    def test_answer_cards(self) -> None:
        for case in EXPECTED["cards"]:
            with self.subTest(card=case["name"]):
                sources = [self.corpus.record(alias) for alias in case["sources"]]
                card = retrieval.build_trusted_card(sources, AS_OF, self.policy)
                self.assertEqual(card["status"], case["status"])
                self.assertEqual(card["banner"], case["banner"])
                if case["selected"] is None:
                    self.assertIsNone(card["selected"])
                else:
                    self.assertEqual(card["selected"]["title"], self.corpus.title(case["selected"]))
                self.assertEqual(
                    [conflict["title"] for conflict in card["conflicts"]],
                    [self.corpus.title(alias) for alias in case["conflicts"]],
                )
                markdown = retrieval.render_card_markdown(card, self.policy)
                for fragment in case["markdownContains"]:
                    self.assertIn(fragment, markdown)


class ConfiguredCardKeysTests(unittest.TestCase):
    """Answer-card keys are the configured search index field names, so renaming a field renames its card key."""

    CARD_FIELDS = (
        "lifecycleStatus", "authoritative", "ownerDisplayName", "reviewDate", "trustScore", "dataQualityStatus",
    )

    def test_card_keys_follow_renamed_index_fields(self) -> None:
        base = _load_policy()
        renames = {base.search_field(key): f"{base.search_field(key)}_probe" for key in self.CARD_FIELDS}
        policy_document = _read_json(_repository_path("policy"))
        vocabulary_document = _read_json(_repository_path("vocabulary"))
        for entry in policy_document["searchIndexFields"] + policy_document["searchProjection"]:
            entry["name"] = renames.get(entry["name"], entry["name"])
        policy_document["knowledgeSourceDataFields"] = [
            renames.get(field_name, field_name) for field_name in policy_document["knowledgeSourceDataFields"]
        ]
        for key, field_name in vocabulary_document["indexFields"].items():
            vocabulary_document["indexFields"][key] = renames.get(field_name, field_name)
        policy = Policy(policy_document, vocabulary_document)
        corpus = Corpus(policy, _corpus_documents())
        card = retrieval.build_trusted_card([corpus.record(EXPECTED["trustedAliases"][0])], AS_OF, policy)
        self.assertIsNotNone(card["selected"])
        for key in self.CARD_FIELDS:
            with self.subTest(field=key):
                self.assertIn(renames[base.search_field(key)], card["selected"])
                self.assertNotIn(base.search_field(key), card["selected"])
        labels = base.retrieval_block()["cardLabels"]
        status_line = f"{labels['status']}: {base.label('lifecycleStatus', 'published')}"
        self.assertIn(status_line, retrieval.render_card_markdown(card, policy))


class HygieneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = _load_policy()
        cls.corpus = Corpus(cls.policy, _corpus_documents())
        cls.payload = cls._payload_for(cls.corpus)

    @classmethod
    def _payload_for(cls, corpus: Corpus) -> dict[str, Any]:
        return hygiene.build_payload(corpus.evaluation, cls.policy, GENERATED_AT, corpus.urls())

    def test_metrics_cover_exactly_the_configured_keys(self) -> None:
        self.assertEqual(list(self.payload["metrics"]), [metric.key for metric in self.policy.hygiene_metrics()])
    def test_metric_values(self) -> None:
        for key, value in EXPECTED["hygiene"]["metrics"].items():
            with self.subTest(metric=key):
                self.assertEqual(self.payload["metrics"][key], value)

    def test_findings_list_their_documents_with_urls(self) -> None:
        findings = {entry["id"]: entry for entry in self.payload["findings"]}
        self.assertEqual(set(findings), {finding.id for finding in self.policy.hygiene_findings()})
        for finding_id, aliases in EXPECTED["hygiene"]["findings"].items():
            with self.subTest(finding=finding_id):
                documents = findings[finding_id]["documents"]
                self.assertEqual(sorted(d["fileName"] for d in documents), sorted(self.corpus.files(aliases)))
                self.assertEqual(findings[finding_id]["count"], len(aliases))
                for document in documents:
                    self.assertEqual(document["url"], self.corpus.urls()[document["fileName"]])

    def test_json_text_round_trips_the_payload(self) -> None:
        self.assertEqual(json.loads(hygiene.json_text(self.payload)), self.payload)

    def test_dashboard_has_one_details_element_per_finding(self) -> None:
        html_text = hygiene.render_dashboard_html(self.payload, self.policy)
        self.assertEqual(html_text.count(EXPECTED["hygiene"]["detailsTag"]), len(self.policy.hygiene_findings()))
        for finding in self.policy.hygiene_findings():
            self.assertIn(html.escape(finding.title), html_text)

    def test_dashboard_escapes_document_text(self) -> None:
        case = EXPECTED["htmlScenario"]
        override = {"alias": case["alias"], "declared": {"Title": case["title"]}}
        corpus = Corpus(self.policy, _corpus_documents([override]))
        html_text = hygiene.render_dashboard_html(self._payload_for(corpus), self.policy)
        self.assertNotIn(case["title"], html_text)
        for fragment in case["contains"]:
            self.assertIn(fragment, html_text)


if __name__ == "__main__":
    unittest.main()
