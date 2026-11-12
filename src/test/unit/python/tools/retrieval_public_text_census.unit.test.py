"""The public-text census is calibration-only, digest-bound and blind to question/gold values."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any

import pytest

from repomap_test_support.w5_semantic_support import (
    BIND_CORE, BIND_REDACTED, make_w5_calibration_task, make_w5_policy, make_w5_readback_adapter, make_w5_verified_pin,
)
from retrieval_evaluation_admission_w5 import admit_w5_task
from retrieval_evaluation_schema import GoldTarget
from retrieval_public_text_contracts import (
    CENSUS_SCOPE_REFUSED, PUBLICATION_REVALIDATION_FAILED, SPAN_INVALID, TASK_DIGEST_MISMATCH, PairExclusion,
    PrivateMarkerScope, PublicTextRefusal,
)
from retrieval_public_text_census import build_public_text_census, retained_task_sha256, task_sha256
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_semantic_generator_inputs import _query_decision
from common_lore_index.retrieval.query_contracts import EvaluationLocator
from common_lore_index.storage.semantic_candidates import digest_json


def _digest(task: Any) -> str:
    data = json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _tasks() -> tuple[Any, ...]:
    return (
        make_w5_calibration_task(task_id="cal-ranked"),
        make_w5_calibration_task(task_id="cal-redacted", selected_bindings=(BIND_CORE, BIND_REDACTED)),
        make_w5_calibration_task(task_id="cal-body", comparability_stratum="body", intended_match_surface="captured_text"),
    )


def _census(tasks: tuple[Any, ...], pin: Any = None, **kwargs: Any):
    pin = pin or make_w5_verified_pin()
    digests = kwargs.pop("digests", {task.task_id: _digest(task) for task in tasks})
    return build_public_text_census(
        tasks, retained_task_digests=digests, policy=make_w5_policy(), publication_pin=pin,
        observed_backend="sqlite", **kwargs,
    )


def test_census_repeats_unchanged_v1_decisions_and_exposes_closed_public_states() -> None:
    pin, tasks = make_w5_verified_pin(), _tasks()
    census = _census(tasks, pin)
    rows = {record.task_id: record for record in census.tasks}
    assert {k: (v.public_text_state, v.public_text_reason) for k, v in rows.items()} == {
        "cal-ranked": ("admitted", None),
        "cal-redacted": ("refused", "retention_not_authorized"),
        "cal-body": ("unavailable", "metadata_representation_not_comparable"),
    }
    assert rows["cal-redacted"].public_text_layer == "public_text_body_precheck"
    for task in tasks:
        direct = admit_w5_task(task, policy=make_w5_policy(), publication_pin=pin, observed_backend="sqlite")
        assert json.dumps(dict(rows[task.task_id].v1_evaluator), sort_keys=True) == json.dumps(direct.to_dict(), sort_keys=True)
        learned = _query_decision(task, pin)
        assert (rows[task.task_id].v1_learned_state, rows[task.task_id].v1_learned_reason) == (learned.state, learned.reason)
        assert rows[task.task_id].task_sha256 == learned.task_sha256 == _digest(task) == task_sha256(task)
    public = census.to_dict()
    assert public["status"] == "preparation_absent" and public["ranked_public_text_queries"] == 1
    assert public["public_text_state_counts"] == {"admitted": 1, "refused": 1, "unavailable": 1}
    text = json.dumps(public, sort_keys=True)
    for task in tasks:
        assert task.question not in text and "primary class definition" not in text
    assert public["census_identity"] == digest_json({k: v for k, v in public.items() if k != "census_identity"})


def test_question_and_gold_values_never_change_applicability() -> None:
    base = make_w5_calibration_task(task_id="cal-ranked")
    other_gold = (GoldTarget(locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/other.py",
                                                        start_line=1, end_line=2), relevance_grade=2, rationale="other",
                             canonical_key="sym:other"),)
    changed = replace(base, question="Find a completely different thing", gold_targets=other_gold).validate()
    first = _census((base,)).tasks[0]
    second = _census((changed,)).tasks[0]
    assert first.task_sha256 != second.task_sha256
    strip = ("task_sha256", "retained_task_sha256")
    assert {k: v for k, v in first.to_dict().items() if k not in strip} == {
        k: v for k, v in second.to_dict().items() if k not in strip
    }


@pytest.mark.parametrize("change,code", [
    ("digest", TASK_DIGEST_MISMATCH), ("missing", TASK_DIGEST_MISMATCH), ("extra", TASK_DIGEST_MISMATCH),
    ("held_out", CENSUS_SCOPE_REFUSED), ("generation", CENSUS_SCOPE_REFUSED), ("duplicate", CENSUS_SCOPE_REFUSED),
    ("empty", CENSUS_SCOPE_REFUSED),
])
def test_census_refuses_scope_and_digest_drift(change: str, code: str) -> None:
    tasks = _tasks()
    digests = {task.task_id: _digest(task) for task in tasks}
    if change == "digest":
        digests["cal-ranked"] = "sha256:" + "0" * 64
    elif change == "missing":
        digests.pop("cal-body")
    elif change == "extra":
        digests["cal-unknown"] = "sha256:" + "0" * 64
    elif change == "held_out":
        tasks = (replace(tasks[0], split="held_out"),)
        digests = {tasks[0].task_id: _digest(tasks[0])}
    elif change == "generation":
        tasks = (make_w5_calibration_task(task_id="cal-g2", generation=2),)
        digests = {"cal-g2": _digest(tasks[0])}
    elif change == "duplicate":
        tasks = (tasks[0], tasks[0])
    else:
        tasks, digests = (), {}
    with pytest.raises(PublicTextRefusal) as error:
        _census(tasks, digests=digests)
    assert error.value.code == code


def _preparation(pin: Any, *, identity: str | None = None, generation: int | None = None) -> PublicTextPreparation:
    scope = PrivateMarkerScope.create(("CANARY-PRIVATE-HOME-7731",))
    exclusion = PairExclusion("sym:core/pkg/pipeline.py::run_step", BIND_CORE, SPAN_INVALID)
    return PublicTextPreparation(
        pin.graph_id, pin.backend, pin.run_id, generation or pin.generation, scope.scope_id,
        identity or str(digest_json(pin.to_dict())), {}, (), (exclusion,), 3, False, {"projection": None}, scope,
    )


def test_census_binds_preparation_to_the_same_publication_without_raw_payload() -> None:
    pin, tasks = make_w5_verified_pin(), _tasks()
    census = _census(tasks, pin, preparation=_preparation(pin)).to_dict()
    assert census["status"] == "no_documents" and census["document_count"] == 0
    assert census["v1_verified_pair_count"] == 3 and census["exclusion_counts"] == {SPAN_INVALID: 1}
    assert census["privacy_scope_id"].startswith("ptscope1:")
    assert "CANARY-PRIVATE-HOME-7731" not in json.dumps(census)
    for bad in (_preparation(pin, identity="sha256:" + "f" * 64), _preparation(pin, generation=2)):
        with pytest.raises(PublicTextRefusal) as error:
            _census(tasks, pin, preparation=bad)
        assert error.value.code == CENSUS_SCOPE_REFUSED


class _CountingCell:
    """A live readback cell that advances the publication on one exact later call."""

    def __init__(self) -> None:
        self.cell, self.calls = make_w5_readback_adapter(), 0
        self.advance_on: int | None = None

    def __call__(self) -> Any:
        self.calls += 1
        if self.advance_on is not None and self.calls == self.advance_on:
            self.cell.advance()
        return self.cell()


def _counted_census(advance_after: int | None) -> tuple[_CountingCell, Any]:
    counting = _CountingCell()
    pin = make_w5_verified_pin(readback_adapter=counting)
    counting.calls = 0
    if advance_after is not None:
        counting.advance_on = advance_after
    tasks = _tasks()
    try:
        return counting, _census(tasks, pin, preparation=_preparation(pin))
    except PublicTextRefusal as error:
        return counting, error


def test_census_revalidates_the_pin_at_entry_and_before_return() -> None:
    counting, census = _counted_census(None)
    assert not isinstance(census, PublicTextRefusal) and census.status == "no_documents"
    total = counting.calls
    assert total >= 2
    for call in (1, total):
        _counting, refused = _counted_census(call)
        assert isinstance(refused, PublicTextRefusal) and refused.code == PUBLICATION_REVALIDATION_FAILED


def test_stale_pin_after_a_newer_generation_refuses_before_any_task_decision() -> None:
    counting = _CountingCell()
    pin = make_w5_verified_pin(readback_adapter=counting)
    counting.cell.advance()
    with pytest.raises(PublicTextRefusal) as error:
        _census(_tasks(), pin)
    assert error.value.code == PUBLICATION_REVALIDATION_FAILED


@pytest.mark.parametrize("case", ["task_type", "backend", "policy_graph", "task_graph"])
def test_known_malformed_admission_and_provenance_inputs_have_closed_refusals(case: str) -> None:
    pin = make_w5_verified_pin()
    task = make_w5_calibration_task()
    tasks: tuple[Any, ...] = (task,)
    policy, backend = make_w5_policy(), "sqlite"
    digests = {task.task_id: _digest(task)}
    if case == "task_type":
        tasks, digests = ({},), {}
    elif case == "backend":
        backend = "postgresql"
    elif case == "policy_graph":
        policy = make_w5_policy(graph_id="other-public-graph")
    else:
        task = replace(task, graph_id="other-public-graph")
        tasks, digests = (task,), {task.task_id: _digest(task)}
    with pytest.raises(PublicTextRefusal) as error:
        build_public_text_census(tasks, retained_task_digests=digests, policy=policy,
                                 publication_pin=pin, observed_backend=backend)
    assert error.value.code == CENSUS_SCOPE_REFUSED


def test_unicode_task_census_keeps_both_identities_and_original_v1_decision() -> None:
    pin = make_w5_verified_pin()
    task = replace(make_w5_calibration_task(task_id="cal-unicode"), question="Find café").validate()
    retained, semantic = retained_task_sha256(task), task_sha256(task)
    assert retained != semantic
    census = _census((task,), pin, digests={task.task_id: retained})
    row = census.tasks[0]
    original = _query_decision(task, pin)
    assert (row.retained_task_sha256, row.task_sha256) == (retained, original.task_sha256)
    assert (row.v1_learned_state, row.v1_learned_reason) == (original.state, original.reason)
    with pytest.raises(PublicTextRefusal) as error:
        _census((task,), pin, digests={task.task_id: semantic})
    assert error.value.code == TASK_DIGEST_MISMATCH
