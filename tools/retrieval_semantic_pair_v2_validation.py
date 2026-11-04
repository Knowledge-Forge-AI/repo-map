"""Structural V2 report validation, separate from source-verified building."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from retrieval_semantic_pair_artifacts import refuse
from retrieval_semantic_pair_metrics import _denominators
from retrieval_semantic_pair_report import _aggregate_denominators
from retrieval_semantic_pair_comparisons import _side
from retrieval_semantic_pair_v2_rows import _comparison_side
from retrieval_semantic_pair_v2_context import Identity, validate_context
from retrieval_semantic_pair_v2_cost import validate_generation_work, validate_pair_work
from retrieval_semantic_pair_v2_disclosures import validate_generation_2_component_disclosure
from retrieval_semantic_pair_v2_projection import (
    _CLASSIFICATIONS,
    _POLICY_SOURCES,
    _alignment,
    _grade,
    _observation,
    _policy,
)
from retrieval_semantic_pair_v2_result_validation import (
    require_projection, validate_generation_projection, validate_projected_result,
)
from retrieval_semantic_pair_v2_rational import rational_projection
from retrieval_semantic_pair_v2_report_identities import (
    COMPARISON_FAMILIES,
    validate_comparison,
    validate_plan,
)


_ACCEPTANCE_FIELDS = {"accepted", "scientific", "fullW5", "heldout", "production"}
_TOP_FIELDS = {
    "schema", "base_report_schema", "acceptance", "pairing", "source_provenance", "generations",
    "pairs", "comparisons", "denominators", "disclosures", "measurement_boundaries",
    "component_counts", "pair_count",
}
_JOURNAL_MEMBERS = {
    "declaration.json", "source-manifest.json", "sources.zip", "observations.jsonl", "report.json", "terminal.json",
}
_DISCLOSURE_FIELDS = {
    "comparative_aggregate", "declared_vs_observed", "reader_live_store_authentication",
    "source_verified_builder", "structural_reader", "raw_model_bundle", "generation_2_limitation",
    "native_cal07_raw_process_stdout_bytes", "unaccepted_65536_byte_criterion", "timing",
}
_MEASUREMENT_FIELDS = {"ann_correctness", "relevance", "safety_and_absence", "database_io", "scientific_comparability"}
_COMPARISON_FIELDS = {
    "family", "left_arm", "right_arm", "identity", "declared_input_identity", "left", "right", "comparability",
}


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value

def _identity(pair: Mapping[str, object]) -> Identity:
    value = _mapping(pair.get("identity"), "pair_v2_identity")
    generation, task, arm, repetition = (
        value.get("generation"), value.get("task_id"), value.get("arm_id"), value.get("repetition")
    )
    if (
        type(generation) is not int or generation not in {1, 2}
        or type(task) is not str or not task
        or type(arm) is not str or not arm
        or type(repetition) is not int or repetition < 1
    ):
        raise refuse("pair_v2_identity")
    return generation, task, arm, repetition

def _validate_denominators(value: object, pair_count: int) -> None:
    denominator = _mapping(value, "pair_v2_denominators")
    values: dict[str, int] = {}
    for field in ("whole", "supported", "graded", "eligible"):
        count = denominator.get(field)
        if type(count) is not int or count < 0 or count > pair_count:
            raise refuse("pair_v2_denominators")
        values[field] = count
    reasons = denominator.get("reason_categories")
    if not isinstance(reasons, Mapping) or any(
        type(key) is not str or type(count) is not int or count < 0 for key, count in reasons.items()
    ):
        raise refuse("pair_v2_denominators")
    if not isinstance(denominator.get("definitions"), Mapping):
        raise refuse("pair_v2_denominators")
    reason_values = [cast(int, count) for count in reasons.values()]
    if values["whole"] != pair_count:
        raise refuse("pair_v2_denominators")
    if not values["eligible"] <= values["graded"] <= values["supported"] <= values["whole"]:
        raise refuse("pair_v2_denominators")
    if sum(reason_values) != values["whole"]:
        raise refuse("pair_v2_denominators")

def _validate_provenance(value: object, generations: Mapping[int, Mapping[str, object]]) -> None:
    provenance = _mapping(value, "pair_v2_provenance")
    if set(provenance) != {"journals", "results_v2"}:
        raise refuse("pair_v2_provenance")
    for name in ("journals", "results_v2"):
        entries = provenance.get(name)
        if type(entries) is not list or len(entries) != 2:
            raise refuse("pair_v2_provenance")
        seen: set[int] = set()
        for raw_entry in entries:
            entry = _mapping(raw_entry, "pair_v2_provenance")
            generation = entry.get("generation")
            if type(generation) is not int or generation not in {1, 2} or generation in seen:
                raise refuse("pair_v2_provenance")
            seen.add(generation)
            summary = generations[generation]
            if entry.get("attempt_id") != summary.get("attempt_id"):
                raise refuse("pair_v2_provenance")
            if name == "journals":
                if frozenset(entry) != {"generation", "attempt_id", "member_digests", "member_lengths"}:
                    raise refuse("pair_v2_provenance")
                digests = _mapping(entry.get("member_digests"), "pair_v2_provenance")
                lengths = _mapping(entry.get("member_lengths"), "pair_v2_provenance")
                if set(digests) != _JOURNAL_MEMBERS or set(digests) != set(lengths):
                    raise refuse("pair_v2_provenance")
                for member, digest in digests.items():
                    if (
                        type(digest) is not str
                        or len(digest) != 71
                        or not digest.startswith("sha256:")
                        or any(char not in "0123456789abcdef" for char in digest[7:])
                    ):
                        raise refuse("pair_v2_provenance")
                    member_length = lengths.get(member)
                    if type(member_length) is not int or member_length < 0:
                        raise refuse("pair_v2_provenance")
                work = _mapping(summary.get("recorded_work"), "pair_v2_provenance")
                source = _mapping(work.get("source"), "pair_v2_provenance")
                counts = _mapping(work.get("component_counts"), "pair_v2_provenance")
                count_source = _mapping(counts.get("source"), "pair_v2_provenance")
                if digests["report.json"] != source.get("sha256") or digests["report.json"] != count_source.get("report_sha256"):
                    raise refuse("pair_v2_provenance")
            else:
                if frozenset(entry) != {"generation", "attempt_id", "length", "sha256"}:
                    raise refuse("pair_v2_provenance")
                digest = entry.get("sha256")
                length = entry.get("length")
                if (
                    type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
                    or any(char not in "0123456789abcdef" for char in digest[7:])
                ):
                    raise refuse("pair_v2_provenance")
                if type(length) is not int or length < 0:
                    raise refuse("pair_v2_provenance")
                plan = _mapping(summary.get("plan"), "pair_v2_provenance")
                if digest != plan.get("result_v2_sha256"):
                    raise refuse("pair_v2_provenance")


def _validate_disclosures(value: object) -> None:
    disclosures = _mapping(value, "pair_v2_disclosures")
    if frozenset(disclosures) != _DISCLOSURE_FIELDS:
        raise refuse("pair_v2_disclosures")
    expected_strings = {
        "comparative_aggregate": "not_emitted",
        "declared_vs_observed": "differences_disclosed; conflicting_observed_claims_refused",
        "reader_live_store_authentication": "not_performed",
        "source_verified_builder": "journal_and_result_v2_hashes_validated_before_projection",
        "structural_reader": "does_not_reauthenticate_source_files_or_live_stores",
        "raw_model_bundle": "deferred; missing_component_counts_are_not_recorded",
        "timing": "named_layers_are_independent_and_may_overlap; no_additive_total",
    }
    if any(disclosures.get(key) != expected for key, expected in expected_strings.items()):
        raise refuse("pair_v2_disclosures")
    cal07 = _mapping(
        disclosures.get("native_cal07_raw_process_stdout_bytes"), "pair_v2_disclosures"
    )
    if frozenset(cal07) != {"current_observed_values", "historical_reference", "status"}:
        raise refuse("pair_v2_disclosures")
    values = cal07.get("current_observed_values")
    if type(values) is not list or any(type(value) is not int or value < 0 for value in values):
        raise refuse("pair_v2_disclosures")
    reference = cal07.get("historical_reference")
    if type(reference) is not int or reference < 0:
        raise refuse("pair_v2_disclosures")
    if cal07.get("status") != "historical_reference_only":
        raise refuse("pair_v2_disclosures")
    criterion = _mapping(disclosures.get("unaccepted_65536_byte_criterion"), "pair_v2_disclosures")
    if criterion != {"value": 65536, "status": "unaccepted"}:
        raise refuse("pair_v2_disclosures")
    limitation = _mapping(disclosures.get("generation_2_limitation"), "pair_v2_disclosures")
    if frozenset(limitation) != {
        "document_only", "component_querycount", "recorded_unavailable_observations", "whole_denominator", "context",
    }:
        raise refuse("pair_v2_disclosures")
    for field in ("document_only", "component_querycount"):
        item = _mapping(limitation.get(field), "pair_v2_disclosures")
        if frozenset(item) != {"value", "evidence_status"}:
            raise refuse("pair_v2_disclosures")
        evidence_status = item.get("evidence_status")
        if evidence_status not in {"not_recorded", "unknown", "recorded_sealed_response"}:
            raise refuse("pair_v2_disclosures")
        if field == "document_only":
            if evidence_status == "recorded_sealed_response":
                if type(item.get("value")) is not bool:
                    raise refuse("pair_v2_disclosures")
            elif item.get("value") is not None:
                raise refuse("pair_v2_disclosures")
        if field == "component_querycount":
            value = item.get("value")
            if evidence_status == "recorded_sealed_response":
                if type(value) is not int or value < 0:
                    raise refuse("pair_v2_disclosures")
            elif value is not None:
                raise refuse("pair_v2_disclosures")
    for field in ("recorded_unavailable_observations", "whole_denominator"):
        count = limitation.get(field)
        if count is not None and (type(count) is not int or count < 0):
            raise refuse("pair_v2_disclosures")
    if type(limitation.get("context")) is not str:
        raise refuse("pair_v2_disclosures")


def _validate_measurements(value: object) -> None:
    measurements = _mapping(value, "pair_v2_measurements")
    if frozenset(measurements) != _MEASUREMENT_FIELDS:
        raise refuse("pair_v2_measurements")
    expected = {
        "ann_correctness": "stored exact_reference_recall only; distinct from relevance",
        "relevance": "stored_task_grade_values_only",
        "safety_and_absence": "not_quality_metrics",
        "database_io": "unknown_values_remain_null",
        "scientific_comparability": "not_emitted",
    }
    if measurements != expected:
        raise refuse("pair_v2_measurements")


def _validate_pairing(value: object) -> None:
    pairing = _mapping(value, "pair_v2_pairing")
    if pairing != {
        "identity_key": ["generation", "task_id", "arm_id", "repetition"],
        "join_mode": "recorded_identity",
        "array_position_join": False,
    }:
        raise refuse("pair_v2_pairing")


def validate_report(report: Mapping[str, object], schema: str) -> None:
    if frozenset(report) != _TOP_FIELDS or report.get("schema") != schema:
        raise refuse("pair_v2_report_fields")
    if report.get("base_report_schema") != "cloe-w5-semantic-paired-report-v1":
        raise refuse("pair_v2_base_schema")
    _validate_pairing(report.get("pairing"))
    _validate_disclosures(report.get("disclosures"))
    _validate_measurements(report.get("measurement_boundaries"))
    acceptance = _mapping(report.get("acceptance"), "pair_v2_acceptance")
    if frozenset(acceptance) != _ACCEPTANCE_FIELDS or any(value is not False for value in acceptance.values()):
        raise refuse("pair_v2_acceptance")
    pairs = report.get("pairs")
    if type(pairs) is not list or report.get("pair_count") != len(pairs):
        raise refuse("pair_v2_pairs")
    seen: set[Identity] = set()
    pair_map: dict[Identity, Mapping[str, object]] = {}
    generation_counts: dict[int, int] = {1: 0, 2: 0}
    for raw in pairs:
        pair = _mapping(raw, "pair_v2_pair")
        if frozenset(pair) != {
            "identity", "classification", "alignment", "journal_observation", "journal_grade",
            "result_v2", "file_grading_policy_version", "file_grading_policy_version_source",
            "rational_fusion", "context", "recorded_work",
        }:
            raise refuse("pair_v2_pair_fields")
        identity = _identity(pair)
        if identity in seen:
            raise refuse("pair_v2_duplicate_identity")
        seen.add(identity)
        pair_map[identity] = pair
        generation_counts[identity[0]] += 1
        classification = pair.get("classification")
        if type(classification) is not str or classification not in _CLASSIFICATIONS:
            raise refuse("pair_v2_classification")
        _alignment(pair.get("alignment"))
        require_projection(pair.get("journal_observation"), _observation(pair.get("journal_observation")), "pair_v2_observation_fields")
        require_projection(pair.get("journal_grade"), _grade(pair.get("journal_grade")), "pair_v2_grade_fields")
        validate_projected_result(pair.get("result_v2"))
        _policy(pair.get("file_grading_policy_version"))
        rational_projection(pair.get("rational_fusion"))
        policy_source = pair.get("file_grading_policy_version_source")
        if type(policy_source) is not str or policy_source not in _POLICY_SOURCES:
            raise refuse("pair_v2_policy_source")
        validate_context(pair.get("context"), identity)
        validate_pair_work(pair.get("recorded_work"))
    generations = report.get("generations")
    if type(generations) is not list or len(generations) != 2:
        raise refuse("pair_v2_generations")
    generation_map: dict[int, Mapping[str, object]] = {}
    generation_plans: dict[int, tuple[tuple[str, ...], tuple[str, ...], int]] = {}
    for raw in generations:
        generation_record = _mapping(raw, "pair_v2_generation")
        validate_generation_projection(generation_record)
        number = generation_record.get("generation")
        if type(number) is not int or number not in {1, 2} or number in generation_map:
            raise refuse("pair_v2_generation")
        generation_number = number
        generation_map[generation_number] = generation_record
        if generation_record.get("pair_count") != generation_counts[generation_number]:
            raise refuse("pair_v2_generation_count")
        generation_plans[generation_number] = validate_plan(generation_record.get("plan"))
        _validate_denominators(
            generation_record.get("denominators"), generation_counts[generation_number]
        )
        generation_pairs = [
            _mapping(pair, "pair_v2_pair") for pair in pairs
            if _identity(_mapping(pair, "pair_v2_pair"))[0] == generation_number
        ]
        if generation_record.get("denominators") != _denominators(generation_pairs):
            raise refuse("pair_v2_denominators")
        validate_generation_work(generation_record.get("recorded_work"))
    validate_generation_2_component_disclosure(
        report.get("disclosures"), generation_map[2].get("recorded_work")
    )
    for generation, (tasks, arms, repetitions) in generation_plans.items():
        expected = {
            (generation, task, arm, repetition)
            for task in tasks for arm in arms for repetition in range(1, repetitions + 1)
        }
        if {identity for identity in seen if identity[0] == generation} != expected:
            raise refuse("pair_v2_identity_set")
    _validate_denominators(report.get("denominators"), len(pairs))
    if report.get("denominators") != _aggregate_denominators([
        _mapping(generation, "pair_v2_generation") for generation in generations
    ]):
        raise refuse("pair_v2_denominators")
    comparisons = report.get("comparisons")
    if type(comparisons) is not list:
        raise refuse("pair_v2_comparisons")
    seen_comparisons: set[tuple[str, int, str, int]] = set()
    for raw in comparisons:
        validate_comparison(raw)
        comparison = _mapping(raw, "pair_v2_comparison")
        comparison_identity = _mapping(comparison["identity"], "pair_v2_comparison_identity")
        generation_record = generation_map[cast(int, comparison_identity["generation"])]
        generation_plan = _mapping(generation_record.get("plan"), "pair_v2_plan")
        if comparison["declared_input_identity"] != generation_plan["input_identity"]:
            raise refuse("pair_v2_comparison_input_identity")
        for field, arm_field in (("left", "left_arm"), ("right", "right_arm")):
            paired = pair_map.get((
                cast(int, comparison_identity["generation"]), cast(str, comparison_identity["task_id"]),
                cast(str, comparison[arm_field]), cast(int, comparison_identity["repetition"]),
            ))
            if paired is None:
                raise refuse("pair_v2_comparison_identity_set")
            context = _mapping(paired.get("context"), "pair_v2_context")
            if comparison.get(field) != _comparison_side(_side(paired), context.get("observed_operation")):
                raise refuse("pair_v2_comparison_pair_binding")
        key = (
            cast(str, comparison["family"]),
            cast(int, comparison_identity["generation"]),
            cast(str, comparison_identity["task_id"]),
            cast(int, comparison_identity["repetition"]),
        )
        if key in seen_comparisons:
            raise refuse("pair_v2_comparison_duplicate_identity")
        seen_comparisons.add(key)
    expected_comparisons = {
        (family, generation, task, repetition)
        for left_arm, right_arm in COMPARISON_FAMILIES
        for family in (left_arm + "_vs_" + right_arm,)
        for generation, (tasks, _arms, repetitions) in generation_plans.items()
        for task in tasks
        for repetition in range(1, repetitions + 1)
    }
    if seen_comparisons != expected_comparisons:
        raise refuse("pair_v2_comparison_identity_set")
    counts = report.get("component_counts")
    if type(counts) is not list or len(counts) != 2:
        raise refuse("pair_v2_component_counts")
    count_generations: set[int] = set()
    for raw_count in counts:
        count = _mapping(raw_count, "pair_v2_component_counts")
        if frozenset(count) != {"generation", "status", "values", "source", "independently_revalidated"}:
            raise refuse("pair_v2_component_counts")
        count_generation = count.get("generation")
        if (
            type(count_generation) is not int
            or count_generation not in {1, 2}
            or count_generation in count_generations
        ):
            raise refuse("pair_v2_component_counts")
        generation_number = count_generation
        count_generations.add(generation_number)
        expected_work = _mapping(
            generation_map[generation_number]["recorded_work"], "pair_v2_generation_work"
        )
        expected_counts = _mapping(expected_work["component_counts"], "pair_v2_component_counts")
        for field in ("status", "values", "source", "independently_revalidated"):
            if count.get(field) != expected_counts.get(field):
                raise refuse("pair_v2_component_counts")
    _validate_provenance(report.get("source_provenance"), generation_map)


__all__ = ["validate_report"]
