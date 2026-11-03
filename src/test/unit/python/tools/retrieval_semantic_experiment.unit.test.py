"""Pure W5 experiment plan, transport, and refusal contracts."""

from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

import pytest

from common_lore_index.retrieval.query_contracts import (
    QueryEnvelope,
    QueryMode,
    QueryScope,
    unavailable_envelope,
)
import retrieval_semantic_experiment_bridge as bridge
from retrieval_semantic_bridge_transport import BridgeRefusal, ReadyEvent, parse_readiness_line
from retrieval_semantic_bridge_admission import encode_admission_marker
from retrieval_semantic_experiment_bridge import ADMISSION_ACK_PREFIX, ComponentExchange
from retrieval_semantic_experiment_contracts import (
    EXPERIMENT_ARMS,
    ExperimentCell,
    ExperimentPlan,
    ExperimentRefusal,
    TIMEOUT_POLICY,
    canonical_json_bytes,
    digest_bytes,
    exact_cosine_distance,
    make_plan,
    validate_calibration_tasks,
)
from retrieval_semantic_experiment_evaluator import (
    build_candidate_rows_arm,
    seal_component_response,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_schema import EvaluationTask, load_task_catalog
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from repomap_test_support.w5_experiment_support import (
    combine_scoped_cells,
    merge_candidate_rows,
    record_baseline,
    selected_public_binding_ids,
)
from repomap_test_support.w5_experiment_vector import (
    VECTOR_ARM_IDS,
    record_vector_query_starts,
)
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_provenance import VerifiedPublicationPin


def _calibration_tasks(generation: int = 1) -> tuple[EvaluationTask, ...]:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    return tuple(task for task in catalog.calibration_tasks() if task.generation == generation)


def _plan(*, arms: tuple[str, ...] = EXPERIMENT_ARMS) -> ExperimentPlan:
    digest = digest_bytes(b"x")
    return make_plan(
        attempt_id="unit-attempt",
        generation=1,
        tasks=_calibration_tasks()[:2],
        input_identity=digest,
        representation_report_identity=digest,
        publication_identity=digest,
        artifact_profile_identity=digest,
        controller_admission_sha256=digest,
        source_closure={"worker.py": digest},
        arms=arms,
    )


def test_plan_is_canonical_and_binds_all_prequery_identities() -> None:
    plan = _plan()
    mapping = plan.to_mapping()
    assert mapping["schema"] == "cloe-w5-semantic-experiment-v1"
    assert mapping["source_closure"] == {"worker.py": digest_bytes(b"x")}
    assert mapping["timeout_policy"] == dict(TIMEOUT_POLICY)
    assert canonical_json_bytes(mapping) == canonical_json_bytes(plan.to_mapping())


@pytest.mark.parametrize(
    "tasks,code",
    [(tuple([replace(_calibration_tasks()[0], split="held_out")]), "held_out_execution_forbidden"),
     ((_calibration_tasks()[0], _calibration_tasks()[0]), "duplicate_calibration_task"),
     (tuple([replace(_calibration_tasks()[0], generation=2)]), "calibration_generation_mismatch")],
)
def test_calibration_population_refuses_heldout_duplicates_and_drift(tasks, code: str) -> None:
    with pytest.raises(ExperimentRefusal, match=code):
        validate_calibration_tasks(tasks, generation=1)


def test_plan_refuses_unsupported_arm_and_unsafe_source_closure() -> None:
    with pytest.raises(ExperimentRefusal, match="unsupported_experiment_arm"):
        _plan(arms=("invented_arm",))
    digest = digest_bytes(b"x")
    with pytest.raises(ExperimentRefusal, match="unsafe_source_closure"):
        make_plan(
            attempt_id="unit-attempt", generation=1, tasks=_calibration_tasks()[:1],
            input_identity=digest, representation_report_identity=digest,
            publication_identity=digest, artifact_profile_identity=digest,
            controller_admission_sha256=digest, source_closure={"../worker.py": digest},
        )


def test_readiness_parser_rejects_traversal_and_wrong_nonce_path() -> None:
    document = {
        "schema": "cloe-w5-component-ready-v1",
        "nonce": "a" * 64,
        "attempt_id": "unit-attempt",
        "request_relative_path": "../w5-component-" + "a" * 64 + "/request.json",
        "request_sha256": digest_bytes(b"request"),
        "request_bytes": 7,
    }
    result = parse_readiness_line(
        "CLOE_W5_COMPONENT_READY "
        + json.dumps(document, sort_keys=True, separators=(",", ":"))
    )
    assert isinstance(result, BridgeRefusal)


def test_component_exchange_timeout_is_refusal_not_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    exchange = ComponentExchange(
        "unit-attempt", "a" * 64, Path("/sandbox-scratch/test-scratch/unit-attempt/w5-component-" + "a" * 64),
        b"request", b"admission", digest_bytes(b"admission"),
        ReadyEvent("a" * 64, "unit-attempt", "unit-attempt/w5-component-" + "a" * 64 + "/request.json", digest_bytes(b"request"), 7),
    )
    monkeypatch.setattr(
        "retrieval_semantic_experiment_bridge.read_response_files",
        lambda _directory, _nonce: None,
    )
    with pytest.raises(ExperimentRefusal, match="component_response_timeout"):
        exchange.await_response(timeout_seconds=0.1)


def test_controller_marker_is_nonce_request_and_length_bound() -> None:
    request_digest = digest_bytes(b"request")
    admission_digest = digest_bytes(b"admission")
    marker = canonical_json_bytes({
        "schema": "cloe-w5-controller-admission-ready-v1",
        "attempt_id": "unit-attempt",
        "nonce": "a" * 64,
        "request_sha256": request_digest,
        "admission_sha256": admission_digest,
        "admission_bytes": len(b"admission"),
    }) + b"\n"
    parsed = bridge._parse_marker(marker)
    exchange = ComponentExchange(
        "unit-attempt", "a" * 64,
        Path("/sandbox-scratch/test-scratch/unit-attempt/w5-component-" + "a" * 64),
        b"request", None, None,
        ReadyEvent("a" * 64, "unit-attempt", "unit-attempt/w5-component-" + "a" * 64 + "/request.json", request_digest, 7),
    )
    assert parsed["nonce"] == exchange.nonce
    assert parsed["request_sha256"] == exchange.ready.request_sha256
    with pytest.raises(ExperimentRefusal, match="controller_admission_marker_malformed"):
        bridge._parse_marker(marker + b"\n")
    with pytest.raises(ExperimentRefusal, match="controller_admission_marker_malformed"):
        bridge._parse_marker(marker[:-1])
    with pytest.raises(ExperimentRefusal, match="controller_admission_marker_malformed"):
        bridge._parse_marker(canonical_json_bytes(dict(parsed, nonce="not-a-nonce")) + b"\n")


def test_controller_admission_handshake_waits_for_marker_then_binds_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_fields = {
        "input_identity": digest_bytes(b"input"),
        "representation_report_identity": digest_bytes(b"representations"),
        "publication_identity": digest_bytes(b"publication"),
        "artifact_profile_identity": digest_bytes(b"artifact"),
    }
    request_raw = canonical_json_bytes(request_fields)
    admission_raw = canonical_json_bytes({
        "schema": "cloe-w5-native-generation-admission-v1",
        "phase": "unit",
        "operator_authority_sha256": digest_bytes(b"operator"),
        "gate_references": {"unit": digest_bytes(b"gate")},
        "bounded_component_execution_admitted": True,
        "request_sha256": digest_bytes(request_raw),
        **request_fields,
        "candidate_closure_digests": {"worker.py": digest_bytes(b"source")},
        "scope": "unit-test",
    })
    request_digest = digest_bytes(request_raw)
    admission_digest = digest_bytes(admission_raw)
    exchange = ComponentExchange(
        "unit-attempt", "a" * 64,
        Path("/sandbox-scratch/test-scratch/unit-attempt/w5-component-" + "a" * 64),
        request_raw, None, None,
        ReadyEvent("a" * 64, "unit-attempt", "unit-attempt/w5-component-" + "a" * 64 + "/request.json", request_digest, len(request_raw)),
        (("worker.py", digest_bytes(b"source")),),
    )
    marker = encode_admission_marker(admission_raw, nonce=exchange.nonce,
                                    attempt_id=exchange.attempt_id, request_sha256=request_digest)
    monkeypatch.setattr(bridge, "_local_worker_source_files", lambda: {"worker.py": b"source"})
    monkeypatch.setattr(bridge, "_source_digests", lambda _files: {"worker.py": digest_bytes(b"source")})
    monkeypatch.setattr(bridge, "_read_exchange_file", lambda _path, **_kwargs: marker)
    monkeypatch.setattr(bridge, "_read_admission_payload", lambda _path, expected_length: admission_raw)
    writes: dict[Path, bytes] = {}
    monkeypatch.setattr(bridge, "_write_exclusive", lambda path, raw: writes.__setitem__(path, raw))
    bound = exchange.await_controller_admission(timeout_seconds=0.1)
    assert bound.admission_raw == admission_raw
    assert bound.admission_sha256 == admission_digest
    assert writes[exchange.directory / "admission.json"] == admission_raw
    assert bound.admission_ack_line.startswith(ADMISSION_ACK_PREFIX)
    assert json.loads(bound.admission_ack_line[len(ADMISSION_ACK_PREFIX):]) == {
        "schema": "cloe-w5-component-admission-ack-v1", "attempt_id": exchange.attempt_id,
        "nonce": exchange.nonce, "request_sha256": request_digest,
        "admission_sha256": admission_digest,
    }
    wrong_request_marker = canonical_json_bytes({
        **json.loads(marker), "request_sha256": digest_bytes(b"other")
    }) + b"\n"
    monkeypatch.setattr(
        bridge, "_read_exchange_file", lambda _path, **_kwargs: wrong_request_marker
    )
    with pytest.raises(ExperimentRefusal, match="controller_admission_request_mismatch"):
        exchange.await_controller_admission(timeout_seconds=0.1)


def test_readiness_emission_starts_a_record_after_pytest_progress(capsys) -> None:
    nonce = "a" * 64
    ready = ReadyEvent(nonce, "unit-attempt", "unit-attempt/w5-component-" + nonce
                       + "/request.json", digest_bytes(b"request"), 7)
    exchange = ComponentExchange("unit-attempt", nonce, Path("/unused"), b"request", None, None, ready)
    print("pytest progress ", end="")
    exchange.emit_request_readiness()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "pytest progress "
    assert len(lines) == 2
    assert parse_readiness_line(lines[1]) == ready


def test_baseline_records_one_start_observation_and_graded_span_slot() -> None:
    task = _calibration_tasks()[0]
    envelope = unavailable_envelope(
        requested_mode=QueryMode(task.requested_mode),
        scope=QueryScope(graph_id=task.graph_id, backend="postgresql"),
        reason="unit_unavailable",
    )
    outcome = (
        ExecutionState.UNAVAILABLE,
        envelope,
        17,
        ByteLayerAccounting(observed_output_payload_bytes=9),
    )

    class Journal:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append(self, record: dict[str, object]) -> None:
            self.events.append(record)

    journal = Journal()

    def execute() -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
        return outcome

    result = record_baseline(journal, task, "current_graph_baseline:postgresql", 1, execute)

    assert result == outcome
    assert [event["event"] for event in journal.events] == [
        "query_started", "query_observed", "task_graded"
    ]
    graded = journal.events[2]
    assert graded["file_metrics_status"] == "gap"
    assert graded["file_metrics_gap"] == "verified_pin_required"
    slot = graded["slot"]
    assert isinstance(slot, dict)
    assert slot["execution_state"] == "unavailable"
    timing = slot["timing"]
    assert isinstance(timing, dict)
    assert timing["raw_samples_ns"] == [17]
    byte_accounting = slot["byte_accounting"]
    assert isinstance(byte_accounting, dict)
    assert byte_accounting["observed_output_payload_bytes"] == 9


def test_vector_start_helper_emits_one_start_per_arm() -> None:
    class Journal:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append(self, record: dict[str, object]) -> None:
            self.events.append(record)

    journal = Journal()
    record_vector_query_starts(journal, "calibration-1", 2)

    assert [event["event"] for event in journal.events] == [
        "query_started", "query_started", "query_started"
    ]
    assert [event["arm_id"] for event in journal.events] == list(VECTOR_ARM_IDS)
    assert {(event["task_id"], event["repetition"]) for event in journal.events} == {
        ("calibration-1", 2)
    }


def test_sealing_refuses_incomplete_response_before_input_access() -> None:
    inputs = object.__new__(PublicGenerationInput)
    with pytest.raises(ExperimentRefusal, match="component_response_members"):
        seal_component_response(inputs, {}, expected_admission_sha256=digest_bytes(b"a"), expected_source_closure={})


def test_candidate_rows_require_scope_and_cosine_is_not_relevance() -> None:
    pin = object.__new__(VerifiedPublicationPin)
    with pytest.raises(ExperimentRefusal, match="candidate_input_scope_required"):
        build_candidate_rows_arm(
            ({"canonical_key": "file:a", "source_binding_id": "bind1:a"},),
            arm_id="exact_vector", task=_calibration_tasks()[0], pin=pin,
        )
    assert math.isclose(exact_cosine_distance((1.0, 0.0), (0.0, 1.0)), 1.0)
    # Exact vector distance remains a retrieval ordering reference; it is not
    # a relevance grade or a claim that the task's gold target is correct.
    assert exact_cosine_distance((1.0, 0.0), (1.0, 0.0)) == 0.0


def test_execution_cells_preserve_not_run_and_cleanup_state() -> None:
    cell = ExperimentCell(
        "hnsw_vector", "cal-1", ExecutionState.NOT_RUN,
        "seqscan_not_hnsw", cleanup_status="verified",
    )
    assert cell.validate().to_dict()["execution_state"] == "not_run"
    assert cell.to_dict()["cleanup_status"] == "verified"


def test_selected_bindings_and_global_merge_preserve_full_candidate_identity() -> None:
    task = _calibration_tasks()[0]
    bindings = selected_public_binding_ids(task)
    assert bindings
    rows = {
        bindings[0]: [{
            "canonical_key": "file:z", "source_binding_id": bindings[0],
            "input_digest": digest_bytes(b"z"), "distance": 0.2,
        }],
        bindings[-1]: [{
            "canonical_key": "file:a", "source_binding_id": bindings[-1],
            "input_digest": digest_bytes(b"a"), "distance": 0.1,
        }],
    }
    merged = merge_candidate_rows(rows)
    assert [(row["source_binding_id"], row["input_digest"]) for row in merged] == [
        (bindings[-1], digest_bytes(b"a")), (bindings[0], digest_bytes(b"z"))
    ]


def test_global_merge_refuses_cross_binding_candidate_rows() -> None:
    binding = selected_public_binding_ids(_calibration_tasks()[0])[0]
    with pytest.raises(ExperimentRefusal, match="candidate_source_scope_mismatch"):
        merge_candidate_rows({binding: [{
            "canonical_key": "file:a", "source_binding_id": "bind1:other",
            "input_digest": digest_bytes(b"a"), "distance": 0.1,
        }]})


def test_scoped_ann_cell_does_not_promote_partial_binding_success() -> None:
    combined = combine_scoped_cells(
        (
            ExperimentCell("hnsw_vector", "cal-1", ExecutionState.COMPLETED, cleanup_status="verified"),
            ExperimentCell("hnsw_vector", "cal-1", ExecutionState.NOT_RUN, "seqscan_not_hnsw", cleanup_status="verified"),
        ),
        arm_id="hnsw_vector", task_id="cal-1",
    )
    assert combined.execution_state == ExecutionState.NOT_RUN
    assert combined.cleanup_status == "verified"


@pytest.mark.parametrize("exact,hybrid,hnsw,lexical,passed", [
    ("completed", "completed", "completed", "completed", True),
    ("completed", "unavailable", "not_run", "unavailable", True),
    ("unavailable", "unavailable", "not_run", "completed", False),
    ("failed", "failed", "not_run", "completed", False),
    ("completed", "unavailable", "not_run", "completed", False),
    ("completed", "completed", "failed", "completed", False),
    ("completed", "completed", "unavailable", "completed", False),
])
def test_supported_queries_cannot_become_success_from_missing_or_failed_execution(exact, hybrid, hnsw, lexical, passed):
    from retrieval_semantic_experiment_outcomes import require_admitted_vector_execution

    states = dict(exact=ExecutionState(exact), hybrid=ExecutionState(hybrid),
                  hnsw=ExecutionState(hnsw), lexical=ExecutionState(lexical))
    if passed:
        require_admitted_vector_execution(**states)
    else:
        with pytest.raises(ExperimentRefusal):
            require_admitted_vector_execution(**states)
