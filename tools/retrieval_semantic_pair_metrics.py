"""Identity joins and descriptive summaries for the W5 paired report."""
from __future__ import annotations
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import cast
from retrieval_semantic_pair_artifacts import JournalArtifact, refuse
from retrieval_semantic_pair_projection import cell_rational_records, choose_grade, observed_summary
from retrieval_semantic_pair_values import metric_mapping
Identity = tuple[str, str, int]
_NUMERIC_GRADING = {"correct", "partial", "incorrect"}
_UNSUPPORTED_REASONS = {
    "captured_text_surface_unsupported_by_metadata_graph",
    "hnsw_index_not_selected",
    "metadata_representation_not_comparable",
    "native_filesystem_has_no_typed_graph_relationships",
    "node_not_found",
    "non_body_feed_or_mailbox_excluded_from_lexical_index",
    "non_body_feed_or_mailbox_excluded_from_text_projection",
    "postgres_native_fts_supports_captured_text_bodies_only",
    "projection_reference_supports_captured_text_bodies_only",
    "unsupported_semantic_query_mode",
}
def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value
def _identity(value: object, code: str) -> Identity:
    mapping = _mapping(value, code)
    if frozenset(mapping) != {"arm_id", "task_id", "repetition"}:
        raise refuse(code)
    arm_id, task_id, repetition = mapping["arm_id"], mapping["task_id"], mapping["repetition"]
    if type(arm_id) is not str or not arm_id or type(task_id) is not str or not task_id:
        raise refuse(code)
    if type(repetition) is not int or repetition < 1:
        raise refuse(code)
    return task_id, arm_id, repetition
def _event_identity(event: Mapping[str, object], *, code: str) -> Identity:
    return _identity(
        {
            "arm_id": event.get("arm_id"),
            "task_id": event.get("task_id"),
            "repetition": event.get("repetition"),
        },
        code,
    )
def _index_events(
    journal: JournalArtifact, event_name: str, planned: set[Identity],
) -> dict[Identity, Mapping[str, object]]:
    indexed: dict[Identity, Mapping[str, object]] = {}
    for event in journal.observations:
        if event.get("event") != event_name:
            continue
        identity = _event_identity(event, code="pair_event_identity")
        if identity not in planned:
            raise refuse("pair_event_identity_unbound")
        if identity in indexed:
            raise refuse("pair_duplicate_journal_identity")
        indexed[identity] = event
    return indexed
def _index_result_records(
    value: object, *, kind: str, planned: set[Identity], required: bool = True,
) -> dict[Identity, Mapping[str, object]]:
    if value is None and not required:
        return {}
    if type(value) is not list:
        raise refuse("pair_result_" + kind + "_list")
    indexed: dict[Identity, Mapping[str, object]] = {}
    for raw in value:
        record = _mapping(raw, "pair_result_" + kind + "_record")
        identity = _identity(record.get("identity"), "pair_result_" + kind + "_identity")
        if identity not in planned:
            raise refuse("pair_result_identity_unbound")
        if identity in indexed:
            raise refuse("pair_duplicate_result_identity")
        indexed[identity] = record
    return indexed
def _validate_result_binding(
    journal: JournalArtifact, result: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...], int, Mapping[str, object]]:
    plan = _mapping(result.get("plan"), "pair_result_plan")
    declaration = journal.declaration
    if (
        plan.get("attempt_id") != journal.attempt_id
        or plan.get("generation") != journal.generation
        or plan.get("schema") != "cloe-w5-semantic-experiment-v1"
    ):
        raise refuse("pair_result_plan_identity")
    arms = tuple(_validate_string_list(plan.get("arms"), "pair_result_plan_arms"))
    tasks = tuple(_validate_string_list(plan.get("task_ids"), "pair_result_plan_tasks"))
    repetitions = plan.get("repetitions")
    if type(repetitions) is not int or repetitions != declaration.get("repetitions"):
        raise refuse("pair_result_plan_repetitions")
    declared_arms = tuple(_validate_string_list(declaration.get("arms"), "pair_declaration_arms"))
    declared_tasks = tuple(_validate_string_list(declaration.get("task_ids"), "pair_declaration_tasks"))
    if arms != declared_arms or tasks != declared_tasks:
        raise refuse("pair_result_plan_population")
    for field in (
        "input_identity", "freeze_sha256", "policy_digest", "publication_identity", "fixture_id",
    ):
        if field in declaration and plan.get(field) != declaration[field]:
            raise refuse("pair_result_plan_" + field)
    raw_journal = _mapping(result.get("raw_journal"), "pair_result_raw_journal")
    for member, digest in journal.member_digests.items():
        ref = _mapping(raw_journal.get(member), "pair_result_raw_journal_ref")
        if frozenset(ref) != {"length", "sha256"}:
            raise refuse("pair_result_raw_journal_ref")
        if ref["length"] != journal.member_lengths[member] or ref["sha256"] != digest:
            raise refuse("pair_result_raw_journal_mismatch")
    return arms, tasks, repetitions, plan
def _validate_string_list(value: object, code: str) -> list[str]:
    if type(value) is not list or not value or any(type(item) is not str or not item for item in value):
        raise refuse(code)
    values = cast(list[str], value)
    if len(set(values)) != len(values):
        raise refuse(code)
    return values
def _optional_policy_version(*values: tuple[str, object]) -> tuple[str | None, str]:
    found: list[tuple[str, str]] = []
    for source, value in values:
        if not isinstance(value, Mapping) or "file_grading_policy_version" not in value:
            continue
        version = value["file_grading_policy_version"]
        if type(version) is not str or not version.strip():
            raise refuse("pair_file_grading_policy_version")
        found.append((source, version))
    if not found:
        return None, "not_recorded"
    versions = {version for _source, version in found}
    if len(versions) != 1:
        raise refuse("pair_file_grading_policy_version_mismatch")
    return found[0][1], "+".join(source for source, _version in found)
def _grade_summary(
    event: Mapping[str, object], source: str,
) -> dict[str, object]:
    slot = event.get("slot")
    slot_map = slot if isinstance(slot, Mapping) else {}
    policy, policy_source = _optional_policy_version((source, event), (source + ".slot", slot_map))
    rule = slot_map.get("grading_rule")
    quality_credit = "not_applicable" if rule in {"safety_refusal", "absent_answer"} else "stored_only"
    metrics, file_metrics, span_metrics = (
        metric_mapping(slot_map.get("metrics"), "pair_grade_metrics"),
        metric_mapping(event.get("file_metrics"), "pair_file_metrics"),
        metric_mapping(event.get("span_metrics"), "pair_span_metrics"),
    )
    if (slot_map.get("safety_refusal_correct") is not None and type(slot_map.get("safety_refusal_correct")) is not bool) or (slot_map.get("absent_answer_correct") is not None and type(slot_map.get("absent_answer_correct")) is not bool):
        raise refuse("pair_safety_value")
    return {
        "family": slot_map.get("family"),
        "comparability_stratum": slot_map.get("comparability_stratum"),
        "comparator_exposure": slot_map.get("comparator_exposure"),
        "requested_mode": slot_map.get("requested_mode"),
        "effective_mode": slot_map.get("effective_mode"),
        "fallback": slot_map.get("fallback"),
        "match_surface": slot_map.get("match_surface"),
        "query_style": slot_map.get("query_style"),
        "grading_rule": rule,
        "grading_state": slot_map.get("grading_state"),
        "capability_state": slot_map.get("capability_state"),
        "execution_state": slot_map.get("execution_state"),
        "safety_refusal_correct": slot_map.get("safety_refusal_correct"),
        "absent_answer_correct": slot_map.get("absent_answer_correct"),
        "metrics": metrics,
        "file_metrics": file_metrics,
        "file_metrics_status": event.get("file_metrics_status"),
        "span_metrics": span_metrics,
        "timing": slot_map.get("timing"),
        "byte_accounting": slot_map.get("byte_accounting"),
        "file_grading_policy_version": policy,
        "file_grading_policy_version_source": policy_source,
        "quality_credit": quality_credit,
        "grade_source": source,
        "timing_source": "slot.timing" if "timing" in slot_map else "not_recorded",
        "byte_accounting_source": (
            "slot.byte_accounting" if "byte_accounting" in slot_map else "not_recorded"
        ),
    }
def _result_summary(
    cell: Mapping[str, object] | None,
    correspondence: Mapping[str, object] | None,
    byte_work: Mapping[str, object] | None,
) -> dict[str, object]:
    sidecar = correspondence.get("sidecar") if correspondence is not None else None
    sidecar_summary = None
    if isinstance(sidecar, Mapping):
        sidecar_summary = {
            key: sidecar[key]
            for key in ("schema", "arm_id", "task_id", "observed_backend", "target_backend", "verification")
            if key in sidecar
        }
    return {
        "cell": cell.get("cell") if cell is not None else None,
        "correspondence": (
            {
                "sidecar": sidecar_summary,
                "cost": correspondence.get("cost"),
            }
            if correspondence is not None
            else None
        ),
        "byte_work": byte_work.get("accounting") if byte_work is not None else None,
    }
def _classify(
    cell: Mapping[str, object] | None,
    observed: Mapping[str, object] | None,
    grade: Mapping[str, object] | None,
) -> str:
    if cell is None and observed is None:
        return "missing"
    if cell is None:
        return "missing_result_v2"
    cell_value = _mapping(cell.get("cell"), "pair_result_cell")
    state = cell_value.get("execution_state")
    rule = grade.get("grading_rule") if grade is not None else None
    if state == "failed":
        return "failed"
    if rule == "safety_refusal":
        safety = grade.get("safety_refusal_correct") if grade else None
        return "safety_correct" if safety is True else "safety_incorrect" if safety is False else "safety_not_recorded"
    if rule == "absent_answer":
        absent = grade.get("absent_answer_correct") if grade else None
        return "absence_correct" if absent is True else "absence_incorrect" if absent is False else "absence_not_recorded"
    if rule == "direct_handoff" or (grade is not None and grade.get("grading_state") == "not_applicable"):
        return "inapplicable"
    if state == "refused":
        return "refused"
    reason = cell_value.get("reason")
    if state == "not_run":
        return "unsupported"
    if state == "unavailable":
        return "unsupported" if reason in _UNSUPPORTED_REASONS else "unavailable"
    if grade is not None and grade.get("grading_state") in _NUMERIC_GRADING:
        return "graded"
    if state == "completed" and observed is not None and observed.get("available_empty") is True:
        return "available_empty"
    return "not_recorded"
def _alignment_reasons(
    *, started: Mapping[str, object] | None, observed: Mapping[str, object] | None,
    cell: Mapping[str, object] | None, grade: Mapping[str, object] | None,
) -> list[str]:
    reasons: list[str] = []
    if started is None:
        reasons.append("journal_query_started_missing")
    if observed is None:
        reasons.append("journal_query_observed_missing")
    if cell is None:
        reasons.append("result_cell_missing")
    if grade is None:
        reasons.append("journal_task_grade_not_recorded")
    if observed is not None and cell is not None:
        observed_state = observed.get("execution_state")
        cell_value = _mapping(cell.get("cell"), "pair_result_cell")
        if observed_state != cell_value.get("execution_state"):
            raise refuse("pair_execution_state_mismatch")
        observed_reason = observed.get("reason")
        cell_reason = cell_value.get("reason")
        if observed_reason != cell_reason and observed_reason is not None and cell_reason is not None:
            raise refuse("pair_execution_reason_mismatch")
    if grade is not None and cell is not None:
        slot_state = grade.get("execution_state")
        cell_value = _mapping(cell.get("cell"), "pair_result_cell")
        if slot_state is not None and slot_state != cell_value.get("execution_state"):
            raise refuse("pair_grade_state_mismatch")
    return reasons


def _denominators(pairs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    reasons: Counter[str] = Counter()
    whole = len(pairs)
    supported = 0
    graded = 0
    eligible = 0
    for pair in pairs:
        result = _mapping(pair.get("result_v2"), "pair_result_summary")
        cell = result.get("cell")
        state = _mapping(cell, "pair_result_cell").get("execution_state") if cell is not None else None
        reasons["not_run" if state == "not_run" else str(pair["classification"])] += 1
        if state not in {None, "unavailable", "not_run"}:
            supported += 1
        grade_value = pair.get("journal_grade")
        grade = grade_value if isinstance(grade_value, Mapping) else None
        if grade is not None and grade.get("grading_state") in _NUMERIC_GRADING:
            graded += 1
            if grade.get("grading_rule") == "ranked_positive":
                eligible += 1
    return {
        "whole": whole,
        "supported": supported,
        "graded": graded,
        "eligible": eligible,
        "reason_categories": dict(sorted(reasons.items())),
        "definitions": {
            "whole": "all declared arm/task/repetition identities",
            "supported": "whole cells with a recorded result state other than unavailable, not_run, or missing",
            "graded": "stored task grades whose grading_state is correct, partial, or incorrect",
            "eligible": "graded cells with ranked_positive grading_rule",
        },
    }
def build_generation_pairs(
    journal: JournalArtifact, result: Mapping[str, object], result_digest: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Join one journal/result pair by recorded identities, never by array order."""
    arms, tasks, repetitions, plan = _validate_result_binding(journal, result)
    planned_order = [
        (task, arm, repetition)
        for task in tasks
        for arm in arms
        for repetition in range(1, repetitions + 1)
    ]
    planned = set(planned_order)
    started = _index_events(journal, "query_started", planned)
    observed = _index_events(journal, "query_observed", planned)
    graded = _index_events(journal, "task_graded", planned)
    cells = _index_result_records(result.get("cells"), kind="cells", planned=planned)
    correspondence = _index_result_records(result.get("correspondence"), kind="correspondence", planned=planned)
    byte_work = _index_result_records(result.get("byte_work"), kind="byte_work", planned=planned)
    pairs: list[dict[str, object]] = []
    all_rational_records: list[dict[str, object]] = []
    for identity in planned_order:
        task_id, arm_id, repetition = identity
        event = observed.get(identity)
        grade_event = graded.get(identity)
        cell = cells.get(identity)
        grade_summary = choose_grade(event, grade_event, _grade_summary)
        observed_value = observed_summary(event)
        policy, policy_source = _optional_policy_version(
            ("query_observed", event or {}),
            ("query_observed.envelope", event.get("envelope", {}) if event else {}),
            ("query_observed.slot", event.get("slot", {}) if event else {}),
            ("task_graded", grade_event or {}),
        )
        if grade_summary is not None:
            grade_policy = grade_summary.get("file_grading_policy_version")
            if grade_policy is not None and policy is not None and grade_policy != policy:
                raise refuse("pair_file_grading_policy_version_mismatch")
            if policy is None:
                policy = cast(str | None, grade_policy)
                policy_source = cast(str, grade_summary.get("file_grading_policy_version_source", "not_recorded"))
        rational = cell_rational_records(event, cell, identity)
        all_rational_records.extend(rational)
        reasons = _alignment_reasons(
            started=started.get(identity), observed=event, cell=cell, grade=grade_summary,
        )
        pair: dict[str, object] = {
            "identity": {
                "generation": journal.generation,
                "task_id": task_id,
                "arm_id": arm_id,
                "repetition": repetition,
            },
            "classification": _classify(cell, observed_value, grade_summary),
            "alignment": {"status": "matched" if not reasons else "gapped", "reasons": reasons},
            "journal_observation": observed_value,
            "journal_grade": grade_summary,
            "result_v2": _result_summary(cell, correspondence.get(identity), byte_work.get(identity)),
            "file_grading_policy_version": policy,
            "file_grading_policy_version_source": policy_source,
            "rational_fusion": rational,
        }
        pairs.append(pair)
    event_counts = Counter(str(event.get("event")) for event in journal.observations)
    summary = {
        "generation": journal.generation,
        "attempt_id": journal.attempt_id,
        "terminal_status": journal.terminal.get("status"),
        "legacy_report": {
            "status": journal.report.get("status"),
            "failure_code": journal.report.get("failure_code"),
        },
        "result_v2_status": result.get("status"),
        "result_v2_failure_code": result.get("failure_code"),
        "plan": {
            "schema": plan.get("schema"),
            "fixture_id": plan.get("fixture_id"),
            "task_ids": list(tasks),
            "arms": list(arms),
            "repetitions": repetitions,
            "freeze_sha256": plan.get("freeze_sha256"),
            "policy_digest": plan.get("policy_digest"),
            "publication_identity": plan.get("publication_identity"),
            "input_identity": plan.get("input_identity"),
            "result_v2_sha256": result_digest,
        },
        "event_counts": dict(sorted(event_counts.items())),
        "denominators": _denominators(pairs),
        "rational_fusion": {
            "status": "present" if all_rational_records else "not_recorded",
            "records": all_rational_records,
            "reason": None if all_rational_records else "no stored numerator/denominator contribution fields",
        },
        "pair_count": len(pairs),
    }
    return pairs, summary
__all__ = ["build_generation_pairs"]
