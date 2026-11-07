"""Admission-runner result-v2 work retention without optional execution."""

from __future__ import annotations

import pytest

from common_lore_index.retrieval.query_contracts import (
    QueryMode, QueryScope, unavailable_envelope, refused_envelope,
)
from repomap_test_support.w5_semantic_support import BIND_CORE, make_w5_policy
from repomap_test_support.w5_experiment_results import ResultV2Run
from repomap_test_support.w5_semantic_support import (
    make_w5_calibration_task, make_w5_readback_adapter, make_w5_verified_pin,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_admission_w5_capture import native_precheck_breakdown
from repomap_test_support.w5_admission_native_bytework import byte_work_accounting
import retrieval_evaluation_admission_w5_runner as admission_runner
from retrieval_evaluation_admission_w5_runner import execute_w5_callback
from retrieval_semantic_experiment_contracts import make_plan
from retrieval_semantic_experiment_scope import CorrespondenceCostSample


def test_blocked_native_work_is_consumed_once_by_runner_callback() -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-runner",
        graph_id="w5-test-graph",
        selected_bindings=("bind1:" + "4" * 64,),
        grading_rule="safety_refusal",
        gold_targets=(),
        expected_refusal_code="binding_privacy_not_authorized",
        intended_match_surface="captured_text",
        comparability_stratum="body",
    )
    plan = make_plan(
        attempt_id="admission-runner-unit",
        generation=1,
        tasks=(task,),
        input_identity="sha256:" + "1" * 64,
        representation_report_identity="sha256:" + "2" * 64,
        publication_identity="sha256:" + "3" * 64,
        artifact_profile_identity="sha256:" + "4" * 64,
        controller_admission_sha256="sha256:" + "5" * 64,
        source_closure={"probe.txt": "sha256:" + "6" * 64},
        arms=("native_tools_baseline",),
    )
    run = ResultV2Run(enabled=True)
    collector = run.register(plan)
    assert collector is not None
    envelope = refused_envelope(
        requested_mode=QueryMode(task.requested_mode),
        scope=QueryScope(
            graph_id=task.graph_id,
            backend="native_filesystem",
            selected_binding_ids=task.selected_bindings,
        ),
        refusal_code="binding_privacy_not_authorized",
    )
    outcome = (
        ExecutionState.REFUSED,
        envelope,
        0,
        ByteLayerAccounting(observed_output_payload_bytes=0),
    )

    class Sidecar:
        def to_dict(self, **_kwargs):
            return {"schema": "test-sidecar-v1"}

    class Runner:
        def __init__(self):
            self.pending = None

        def take_native_precheck_work(self, _arm_id, _task, _envelope):
            pending, self.pending = self.pending, None
            return pending

        def sidecar(self, _arm_id, _task, *, envelope, projection):
            return Sidecar()

    runner = Runner()
    pin = make_w5_verified_pin()

    def metrics_reader(_task, _arm_id, _state, _envelope, _sidecar):
        return None, "refused", "binding_privacy_not_authorized", CorrespondenceCostSample()

    for repetition in (1, 2):
        callback = run.baseline_callback_for_runner(
            collector,
            repetition=repetition,
            runner=runner,
            sqlite_projection=None,
            postgres_projection=None,
            metrics_reader=metrics_reader,
            legacy_reader=lambda *_args, **_kwargs: (None, "refused", "unused"),
            pin=pin,
        )
        if repetition == 1:
            runner.pending = native_precheck_breakdown(envelope)
        callback(task, "native_tools_baseline", outcome[0], outcome[1])

    assert len(collector._byte_work) == 1
    accounting = byte_work_accounting(collector._byte_work[0])
    assert accounting["raw_process_stdout_bytes"] == 0
    assert accounting["direct_selected_text_bytes"] == 0
    assert accounting["decoded_candidate_count"] == 0
    assert accounting["returned_hit_count"] == 0


def test_admission_elapsed_is_added_once_to_an_admitted_task(monkeypatch) -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-timing",
        selected_bindings=(BIND_CORE,),
    )
    policy = make_w5_policy()
    pin = make_w5_verified_pin()
    envelope = unavailable_envelope(
        requested_mode=QueryMode(task.requested_mode),
        scope=QueryScope(
            graph_id=task.graph_id,
            backend="sqlite",
            selected_binding_ids=(BIND_CORE,),
        ),
        reason="backend_unsupported",
    )
    clock = iter((100, 125))
    monkeypatch.setattr(admission_runner, "perf_counter_ns", lambda: next(clock))
    result = execute_w5_callback(
        arm_id="current_graph_baseline:sqlite",
        task=task,
        policy=policy,
        publication_pin=pin,
        callback=lambda _pin: (
            ExecutionState.COMPLETED,
            envelope,
            7,
            ByteLayerAccounting(observed_output_payload_bytes=3),
        ),
    )
    assert result[2] == 32
    assert result[1].provenance["admission_elapsed_ns"] == 25
    assert result[1].provenance["admission_elapsed_overlapping"] is True


def test_admission_elapsed_is_retained_for_a_blocked_task(monkeypatch) -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-blocked-timing",
        selected_bindings=("bind1:" + "4" * 64,),
        grading_rule="safety_refusal",
        gold_targets=(),
        expected_refusal_code="binding_privacy_not_authorized",
        intended_match_surface="captured_text",
        comparability_stratum="body",
    )
    clock = iter((200, 230))
    monkeypatch.setattr(admission_runner, "perf_counter_ns", lambda: next(clock))

    def forbidden(_pin):
        raise AssertionError("blocked W5 callback was reached")

    result = execute_w5_callback(
        arm_id="current_graph_baseline:sqlite",
        task=task,
        policy=make_w5_policy(),
        publication_pin=make_w5_verified_pin(),
        callback=forbidden,
    )
    assert result[0] is ExecutionState.REFUSED
    assert result[2] == 30
    assert result[1].provenance["evaluator_precheck"] is True
    assert result[1].provenance["admission_elapsed_ns"] == 30
    assert result[1].provenance["admission_elapsed_overlapping"] is True


def test_admission_elapsed_is_retained_for_a_verification_error(monkeypatch) -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-error-timing", selected_bindings=(BIND_CORE,)
    )

    cell = make_w5_readback_adapter()
    unavailable = False
    def unavailable_readback():
        if unavailable:
            raise RuntimeError("readback unavailable")
        return cell()

    broken_pin = make_w5_verified_pin(readback_adapter=unavailable_readback)
    unavailable = True
    clock = iter((300, 340))
    monkeypatch.setattr(admission_runner, "perf_counter_ns", lambda: next(clock))
    result = execute_w5_callback(
        arm_id="current_graph_baseline:sqlite",
        task=task,
        policy=make_w5_policy(),
        publication_pin=broken_pin,
        callback=lambda _pin: (_ for _ in ()).throw(
            AssertionError("failed admission callback was reached")
        ),
    )
    assert result[0] is ExecutionState.FAILED
    assert result[2] == 40
    assert result[1].provenance["evaluator_precheck"] is True
    assert result[1].provenance["admission_elapsed_ns"] == 40
    assert result[1].provenance["failure_type"] == "publication_pin_revalidation_failed"
    assert result[1].provenance["admission_elapsed_overlapping"] is True


def test_nested_admission_elapsed_is_cumulative(monkeypatch) -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-nested-timing", selected_bindings=(BIND_CORE,)
    )
    envelope = unavailable_envelope(
        requested_mode=QueryMode(task.requested_mode),
        scope=QueryScope(
            graph_id=task.graph_id,
            backend="sqlite",
            selected_binding_ids=(BIND_CORE,),
        ),
        reason="backend_unsupported",
        provenance={"admission_elapsed_ns": 11},
    )
    clock = iter((500, 525))
    monkeypatch.setattr(admission_runner, "perf_counter_ns", lambda: next(clock))
    result = execute_w5_callback(
        arm_id="current_graph_baseline:sqlite",
        task=task,
        policy=make_w5_policy(),
        publication_pin=make_w5_verified_pin(),
        callback=lambda _pin: (
            ExecutionState.COMPLETED,
            envelope,
            18,
            ByteLayerAccounting(observed_output_payload_bytes=3),
        ),
    )
    assert result[2] == 43
    assert result[1].provenance["admission_elapsed_ns"] == 36
    assert result[1].provenance["admission_elapsed_outer_ns"] == 25


def test_callback_exception_retains_admission_elapsed(monkeypatch) -> None:
    task = make_w5_calibration_task(
        task_id="w5-admission-callback-error", selected_bindings=(BIND_CORE,)
    )
    clock = iter((600, 625))
    monkeypatch.setattr(admission_runner, "perf_counter_ns", lambda: next(clock))

    with pytest.raises(RuntimeError) as caught:
        execute_w5_callback(
            arm_id="current_graph_baseline:sqlite",
            task=task,
            policy=make_w5_policy(),
            publication_pin=make_w5_verified_pin(),
            callback=lambda _pin: (_ for _ in ()).throw(
                RuntimeError("callback failed")
            ),
        )
    assert getattr(caught.value, "w5_admission_elapsed_ns") == 25
