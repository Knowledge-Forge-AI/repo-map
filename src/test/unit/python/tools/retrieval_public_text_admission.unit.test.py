"""Public-text admission keeps both v1 decisions byte-identical and adds real body-policy refusals."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_semantic_support import (
    BIND_COMP, BIND_CORE, BIND_PRIVATE, BIND_REDACTED, make_w5_calibration_task, make_w5_policy, make_w5_verified_pin,
)
from retrieval_evaluation_admission_w5 import admit_w5_task
from retrieval_public_text_admission import (
    AdmittedPair, admit_document_pair, admit_public_text_query, dependent_fusion_state, incumbent_fusion_state,
    supplemental_body_reason,
)
from retrieval_public_text_contracts import (
    ARTIFACT_NOT_IN_MANIFEST, BINDING_POLICY_MISSING, BODY_PRECHECK_LAYER, METADATA_PRIVACY_REFUSED,
    SELECTED_EVIDENCE_MISSING, SPAN_INVALID, SPAN_REVERSED, PairExclusion, SpanRow,
)
from retrieval_semantic_generator_inputs import _query_decision
from retrieval_semantic_primitives import VerifiedNodeRepresentation

KEY = "python.function:pkg.alpha:boundary_fn"
CANARY = "CANARY-PRIVATE-HOME-7731"


def _decide(task: Any, pin: Any, policy: Any):
    kwargs = {"policy": policy, "publication_pin": pin, "observed_backend": "sqlite"}
    return admit_public_text_query(task, **kwargs), admit_w5_task(task, **kwargs)


def _bytes(decision: Any) -> bytes:
    return json.dumps(decision.to_dict(), sort_keys=True).encode("utf-8")


def test_admitted_metadata_task_keeps_both_v1_decisions_byte_identical() -> None:
    pin, policy = make_w5_verified_pin(), make_w5_policy()
    task = make_w5_calibration_task()
    public, v1 = _decide(task, pin, policy)
    assert _bytes(public.v1_decision) == _bytes(v1)
    assert public.state == "admitted" and public.refusal_code is None
    learned = _query_decision(task, pin)
    assert (learned.state, learned.reason, learned.record_id) == ("admitted", None, "query:" + task.task_id)
    assert _query_decision(task, pin) == learned
    assert incumbent_fusion_state(public) == ("admitted", None)


def test_supplemental_body_policy_refuses_only_the_public_text_arm() -> None:
    pin, policy = make_w5_verified_pin(), make_w5_policy()
    task = make_w5_calibration_task(selected_bindings=(BIND_CORE, BIND_REDACTED))
    public, v1 = _decide(task, pin, policy)
    assert v1.state.value == "admitted" and _bytes(public.v1_decision) == _bytes(v1)
    assert _query_decision(task, pin).state == "admitted"
    assert (public.state, public.refusal_code, public.policy_enforcement_layer) == (
        "refused", "retention_not_authorized", BODY_PRECHECK_LAYER,
    )
    assert dependent_fusion_state(public) == ("refused", "retention_not_authorized")
    assert incumbent_fusion_state(public) == ("admitted", None)


def test_global_v1_denial_and_unavailability_are_inherited_unchanged() -> None:
    pin, policy = make_w5_verified_pin(), make_w5_policy()
    denied = make_w5_calibration_task(selected_bindings=(BIND_CORE, BIND_PRIVATE), grading_rule="safety_refusal")
    public, v1 = _decide(denied, pin, policy)
    assert (public.state, public.refusal_code, public.policy_enforcement_layer) == (
        "refused", v1.refusal_code, "evaluator_precheck",
    )
    assert _query_decision(denied, pin).state == "refused"
    undeclared = make_w5_calibration_task(selected_bindings=(BIND_CORE, "bind1:" + "9" * 64))
    public, v1 = _decide(undeclared, pin, policy)
    assert v1.state.value == "unavailable"
    assert (public.state, public.reason_category, public.refusal_code) == ("unavailable", "undeclared", None)


@pytest.mark.parametrize("change,reason", [
    ({"comparability_stratum": "body", "intended_match_surface": "captured_text"}, "metadata_representation_not_comparable"),
    ({"comparability_stratum": "graph_topology"}, "metadata_representation_not_comparable"),
    ({"requested_mode": "current_literal_enumeration"}, "unsupported_semantic_query_mode"),
    ({"grading_rule": "safety_refusal"}, "unsupported_semantic_task_rule"),
    ({"comparability_stratum": "graph_topology", "requested_mode": "current_literal_enumeration"},
     "metadata_representation_not_comparable"),
])
def test_applicability_uses_the_complete_v1_predicate_in_v1_order(change: dict[str, Any], reason: str) -> None:
    pin, policy = make_w5_verified_pin(), make_w5_policy()
    task = replace(make_w5_calibration_task(), **change)
    public, v1 = _decide(task, pin, policy)
    assert _bytes(public.v1_decision) == _bytes(v1)
    assert (public.state, public.reason_category) == ("unavailable", reason)
    learned = _query_decision(task, pin)
    assert (learned.state, learned.reason) == ("unavailable", reason)


def test_missing_policy_binding_is_not_authority() -> None:
    policy = make_w5_policy()
    assert supplemental_body_reason(policy, "bind1:" + "9" * 64) == BINDING_POLICY_MISSING
    assert supplemental_body_reason(policy, BIND_COMP) is None
    assert supplemental_body_reason(policy, BIND_REDACTED) == "retention_not_authorized"


def _manifest(tmp_path: Path):
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    bindings = {binding.binding_id: binding for binding in inputs.manifest.bindings}
    entries = {(entry.binding_id, entry.source_relative_path): entry for entry in inputs.manifest.entries}
    return inputs, policy, bindings, entries


def _rep(binding_id: str, *, keys: tuple[str, ...] = ("ev1:alpha80",), display: str = "boundary_fn"):
    return VerifiedNodeRepresentation(KEY, "Function", display, binding_id, "snap1:" + "a" * 64, 1, ("pkg/alpha.py",), keys, 10, "sha256:" + "0" * 64)


def _row(binding_id: str, *, path: str = "pkg/alpha.py", key: str = "ev1:alpha80", start: Any = 80, end: Any = 81,
         link: str = "defined_by", run_id: int = 1) -> SpanRow:
    return SpanRow(KEY, key, run_id, 1, "core/" + path, {"binding_id": binding_id, "source_relative_path": path}, link, start, end)


def _admit(policy: Any, bindings: Any, entries: Any, rep: Any, rows: tuple[SpanRow, ...], markers: tuple[str, ...] = ()):
    return admit_document_pair(rep, policy=policy, bindings_by_id=bindings, entries_by_key=entries, rows=rows,
                               run_id=1, private_markers=markers)


def test_document_pair_gates_admit_only_metadata_checked_pairs(tmp_path: Path) -> None:
    _inputs, policy, bindings, entries = _manifest(tmp_path)
    core, mail = sorted(bindings)
    admitted = _admit(policy, bindings, entries, _rep(core), (_row(core),))
    assert isinstance(admitted, AdmittedPair) and admitted.source_relative_path == "pkg/alpha.py"

    def reason(rep: Any, rows: tuple[SpanRow, ...], markers: tuple[str, ...] = (), pol: Any = policy) -> str:
        outcome = _admit(pol, bindings, entries, rep, rows, markers)
        assert isinstance(outcome, PairExclusion)
        return outcome.reason

    unknown = "bind1:" + "9" * 64
    assert reason(_rep(unknown), (_row(unknown),)) == BINDING_POLICY_MISSING
    assert reason(_rep(mail), (_row(mail),)) == "public_text_body_policy_denied:binding_privacy_not_authorized"
    unselected = replace(policy, selected_binding_ids=frozenset()).validate()
    assert reason(_rep(core), (_row(core),), pol=unselected) == "public_text_binding_excluded:binding_not_selected"
    assert reason(_rep(core), ()) == SELECTED_EVIDENCE_MISSING
    assert reason(_rep(core), (_row(core, link="inferred"),)) == SELECTED_EVIDENCE_MISSING
    assert reason(_rep(core), (_row(mail),)) == SELECTED_EVIDENCE_MISSING
    assert reason(_rep(core), (_row(core, run_id=2),)) == SELECTED_EVIDENCE_MISSING
    assert reason(_rep(core), (_row(core, start=None),)) == SPAN_INVALID
    assert reason(_rep(core), (_row(core, start=True, end=True),)) == SPAN_INVALID
    assert reason(_rep(core), (_row(core, start=81, end=80),)) == SPAN_REVERSED
    assert reason(_rep(core, display=CANARY), (_row(core),), (CANARY,)) == METADATA_PRIVACY_REFUSED
    assert reason(_rep(core), (_row(core, path="../alpha.py"),)) == METADATA_PRIVACY_REFUSED
    assert reason(_rep(core), (_row(core, path="pkg/gamma.py"),)) == ARTIFACT_NOT_IN_MANIFEST
    small = replace(policy, max_input_artifact_bytes=64, max_aggregate_input_bytes=64).validate()
    assert reason(_rep(core), (_row(core),), pol=small) == "public_text_pre_open_excluded:artifact_oversized"


def test_selection_is_total_and_never_falls_through_to_a_favorable_span(tmp_path: Path) -> None:
    _inputs, policy, bindings, entries = _manifest(tmp_path)
    core = sorted(bindings)[0]
    rep = _rep(core, keys=("ev1:a", "ev1:b"))
    rows = (_row(core, key="ev1:b"), _row(core, key="ev1:a", start=None, end=None))
    outcome = _admit(policy, bindings, entries, rep, rows)
    assert isinstance(outcome, PairExclusion) and outcome.reason == SPAN_INVALID
    mixed = (_row(core, key="ev1:a", link="observed"), _row(core, key="ev1:a", start=None, end=81))
    chosen = _admit(policy, bindings, entries, rep, mixed)
    assert isinstance(chosen, PairExclusion) and chosen.reason == SPAN_INVALID
    ordered = (_row(core, key="ev1:a", start=90, end=91), _row(core, key="ev1:a", link="observed"))
    first = _admit(policy, bindings, entries, rep, ordered)
    assert isinstance(first, AdmittedPair) and (first.row.start_line, first.row.end_line) == (80, 81)


@pytest.mark.parametrize("evidence_key", [
    CANARY, "ev1:" + "-----BEGIN PRIVATE KEY-----", "https" + "://u:" + "PUBLIC_TEST_VALUE" + "@host.invalid", "ev1:a\u0085",
])
def test_g6_selected_evidence_key_privacy_precedes_manifest_and_body_gates(tmp_path: Path, evidence_key: str) -> None:
    _inputs, policy, bindings, entries = _manifest(tmp_path)
    core = sorted(bindings)[0]
    rep = _rep(core, keys=(evidence_key,))
    for path in ("pkg/alpha.py", "pkg/none.py"):
        outcome = _admit(policy, bindings, entries, rep, (_row(core, key=evidence_key, path=path),), (CANARY,))
        assert isinstance(outcome, PairExclusion) and outcome.reason == METADATA_PRIVACY_REFUSED
    span_first = _admit(policy, bindings, entries, rep, (_row(core, key=evidence_key, start=0),), (CANARY,))
    assert isinstance(span_first, PairExclusion) and span_first.reason == SPAN_INVALID


def test_structured_colon_evidence_keys_are_admitted(tmp_path: Path) -> None:
    _inputs, policy, bindings, entries = _manifest(tmp_path)
    core = sorted(bindings)[0]
    key = "ev1:token:sync"
    outcome = _admit(policy, bindings, entries, _rep(core, keys=(key,)), (_row(core, key=key),), (CANARY,))
    assert isinstance(outcome, AdmittedPair) and outcome.row.evidence_key == key


def test_first_failing_gate_owns_the_reason(tmp_path: Path) -> None:
    _inputs, policy, bindings, entries = _manifest(tmp_path)
    core = sorted(bindings)[0]
    bad = _row(core, path="../outside.txt", start=0)
    outcome = _admit(policy, bindings, entries, _rep(core, display=CANARY), (bad,), (CANARY,))
    assert isinstance(outcome, PairExclusion) and outcome.reason == SPAN_INVALID
    outcome = _admit(policy, bindings, entries, _rep(core, display=CANARY), (_row(core, path="pkg/none.py"),), (CANARY,))
    assert isinstance(outcome, PairExclusion) and outcome.reason == METADATA_PRIVACY_REFUSED
