"""Pure result-v2 contract tests; no model, database, or child process."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import cast

import pytest

from retrieval_evaluation_accounting import EvaluatorByteBreakdownV1
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_baseline_result_frames import (
    decode_result_frames,
    emit_result_frames,
)
from retrieval_semantic_baseline_result_objects import BaselineResultV2, ResultV2Collector
from retrieval_semantic_baseline_results import ResultRefusal
from retrieval_semantic_experiment_contracts import (
    ExperimentCell,
    ExperimentPlan,
)
from retrieval_semantic_experiment_scope import (
    BASELINE_ARM_OBSERVED_BACKENDS,
    BASELINE_ARM_TARGET_BACKENDS,
    CorrespondenceCostSample,
)


_DIGEST = "sha256:" + "a" * 64
_MEMBERS = {
    "declaration.json": b"decl\n",
    "source-manifest.json": b"manifest\n",
    "sources.zip": b"zip",
    "observations.jsonl": b"{}\n",
    "report.json": b"report\n",
    "terminal.json": b"terminal\n",
}


@dataclass(frozen=True)
class _Sidecar:
    arm_id: str
    task_id: str = "cal-01"
    schema: str = "cloe-w5-baseline-correspondence-v1"
    sqlite_pin: object = object()
    postgres_pin: object = object()

    def to_dict(
        self,
        *,
        observed_backend: str,
        target_backend: str,
        status: str,
        gap_reason: str | None = None,
        verified_pin: object | None = None,
        cost: CorrespondenceCostSample | None = None,
    ) -> dict[str, object]:
        target_pin = self.sqlite_pin if target_backend == "sqlite" else self.postgres_pin
        if status == "verified" and (verified_pin is not target_pin or cost is None):
            raise ValueError("verified sidecar context required")
        if status != "verified" and verified_pin is not None:
            raise ValueError("unverified sidecar pin forbidden")
        return {
            "schema": self.schema,
            "arm_id": self.arm_id,
            "task_id": self.task_id,
            "observed_backend": observed_backend,
            "target_backend": target_backend,
            "verification": {
                "status": status,
                "gap_reason": gap_reason,
                "verified": status == "verified",
                "cost": cost.to_dict() if cost is not None else None,
            },
        }


def _plan(attempt_id: str = "w5-semantic-g1") -> ExperimentPlan:
    return ExperimentPlan(
        attempt_id=attempt_id,
        generation=1 if attempt_id.endswith("g1") else 2,
        task_ids=("cal-01",),
        task_digests=(_DIGEST,),
        input_identity=_DIGEST,
        representation_report_identity=_DIGEST,
        publication_identity=_DIGEST,
        artifact_profile_identity=_DIGEST,
        controller_admission_sha256=_DIGEST,
        source_closure=(("tools/frozen.py", _DIGEST),),
        fixture_id="mixed-v1",
        freeze_sha256=_DIGEST,
        policy_digest=_DIGEST,
        arms=("current_graph_baseline:postgresql", "native_tools_baseline", "exact_vector"),
    ).validate()


def _complete_result() -> BaselineResultV2:
    plan = _plan()
    collector = ResultV2Collector(plan)
    for arm_id in plan.arms:
        for repetition in range(1, plan.repetitions + 1):
            collector.add_cell(
                {"arm_id": arm_id, "task_id": "cal-01", "repetition": repetition},
                ExperimentCell(
                    arm_id, "cal-01", ExecutionState.COMPLETED,
                    candidates=(), elapsed_ns=7, query_bytes=11,
                    cleanup_status="verified",
                ),
            )
    baseline_arms = tuple(
        arm_id for arm_id in plan.arms if arm_id in BASELINE_ARM_TARGET_BACKENDS
    )
    for arm_id in baseline_arms:
        observed_backend = BASELINE_ARM_OBSERVED_BACKENDS[arm_id]
        target_backend = BASELINE_ARM_TARGET_BACKENDS[arm_id]
        for repetition in range(1, plan.repetitions + 1):
            is_primary = (
                arm_id == "current_graph_baseline:postgresql" and repetition == 1
            )
            collector.add_correspondence(
                {"arm_id": arm_id, "task_id": "cal-01", "repetition": repetition},
                _Sidecar(arm_id=arm_id),
                observed_backend=observed_backend,
                target_backend=target_backend,
                status="verified",
                gap_reason=None,
                cost=CorrespondenceCostSample(
                    correspondence_verification_ns=13,
                    correspondence_verification_bytes_read=None,
                    known_artifact_bytes_read=17 if is_primary else 0,
                    known_materialized_bytes_read=23 if is_primary else 0,
                ),
            )
    for repetition in range(1, plan.repetitions + 1):
        collector.add_byte_work(
            {
                "arm_id": "native_tools_baseline",
                "task_id": "cal-01",
                "repetition": repetition,
            },
            EvaluatorByteBreakdownV1(
                raw_process_stdout_bytes=495781 + repetition - 1,
                native_process_stdout_cap_bytes=1048576,
                decoded_candidate_count=64,
                returned_hit_count=10,
                serialized_envelope_bytes=1536,
            ),
        )
    return collector.finish(status="completed", raw_journal_members=_MEMBERS)


def _encoded(result: BaselineResultV2) -> bytes:
    stream = io.StringIO()
    emit_result_frames((result,), stream=stream)
    return stream.getvalue().encode("ascii")


def test_opt_in_frame_roundtrip_keeps_six_legacy_members_byte_identical() -> None:
    before = dict(_MEMBERS)
    result = _complete_result()
    decoded = decode_result_frames(b"ordinary diagnostics\n" + _encoded(result))
    assert decoded["w5-semantic-g1"].to_mapping() == result.to_mapping()
    assert _MEMBERS == before
    mapping = result.to_mapping()
    raw_journal_value = mapping["raw_journal"]
    assert isinstance(raw_journal_value, dict)
    raw_journal = cast(dict[str, object], raw_journal_value)
    assert set(raw_journal) == set(_MEMBERS)
    correspondence_value = mapping["correspondence"]
    assert isinstance(correspondence_value, list)
    correspondence = cast(list[dict[str, object]], correspondence_value)
    cost_value = correspondence[0]["cost"]
    assert isinstance(cost_value, dict)
    cost = cast(dict[str, object], cost_value)
    assert cost["correspondence_verification_bytes_read"] is None
    assert cost["known_artifact_bytes_read"] == 17
    assert cost["known_materialized_bytes_read"] == 23


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.update(extra="refused"),
        lambda value: value.update(schema="cloe-w5-semantic-experiment-v1"),
        lambda value: value["byte_work"][0]["accounting"].update(future_bytes=1),
        lambda value: value["correspondence"][0]["cost"].update(unknown=0),
    ),
)
def test_result_mapping_rejects_version_and_unknown_fields(mutator) -> None:
    value = _complete_result().to_mapping()
    mutator(value)
    with pytest.raises(ResultRefusal):
        BaselineResultV2.from_mapping(value)


def test_unknown_measurement_is_explicitly_null_not_silently_zero() -> None:
    collector = ResultV2Collector(_plan())
    collector.add_byte_work(
        {"arm_id": "native_tools_baseline", "task_id": "cal-01", "repetition": 1},
        EvaluatorByteBreakdownV1(raw_process_stdout_bytes=None),
    )
    result = collector.finish(
        status="failed", failure_code="unknown_measurement", raw_journal_members=_MEMBERS,
    )
    mapping = result.to_mapping()
    byte_work_value = mapping["byte_work"]
    assert isinstance(byte_work_value, list)
    byte_work = cast(list[dict[str, object]], byte_work_value)
    accounting_value = byte_work[0]["accounting"]
    assert isinstance(accounting_value, dict)
    measurement = cast(dict[str, object], accounting_value)
    assert measurement["raw_process_stdout_bytes"] is None
    assert measurement["decoded_candidate_count"] == 0


def test_failed_attempt_preserves_failure_status_without_fabricating_work() -> None:
    result = ResultV2Collector(_plan()).finish(
        status="failed", failure_code="attempt_failed", raw_journal_members=_MEMBERS,
    )
    assert result.to_mapping()["status"] == "failed"
    assert result.to_mapping()["failure_code"] == "attempt_failed"
    assert result.to_mapping()["byte_work"] == []


def test_failed_attempt_may_retain_partial_work() -> None:
    collector = ResultV2Collector(_plan())
    collector.add_cell(
        {"arm_id": "exact_vector", "task_id": "cal-01", "repetition": 1},
        ExperimentCell("exact_vector", "cal-01", ExecutionState.COMPLETED),
    )
    result = collector.finish(
        status="failed", failure_code="attempt_failed", raw_journal_members=_MEMBERS,
    )
    assert result.to_mapping()["status"] == "failed"
    assert len(cast(list[object], result.to_mapping()["cells"])) == 1


def _first_correspondence_parts(
    value: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    correspondence_value = value["correspondence"]
    assert isinstance(correspondence_value, list)
    correspondence = cast(list[dict[str, object]], correspondence_value)
    record = correspondence[0]
    sidecar_value = record["sidecar"]
    assert isinstance(sidecar_value, dict)
    sidecar = cast(dict[str, object], sidecar_value)
    verification_value = sidecar["verification"]
    assert isinstance(verification_value, dict)
    verification = cast(dict[str, object], verification_value)
    nested_cost_value = verification["cost"]
    assert isinstance(nested_cost_value, dict)
    nested_cost = cast(dict[str, object], nested_cost_value)
    return record, sidecar, verification, nested_cost


def test_completed_result_rejects_cell_identity_drift() -> None:
    value = _complete_result().to_mapping()
    cells_value = value["cells"]
    assert isinstance(cells_value, list)
    cells = cast(list[dict[str, object]], cells_value)
    cell_value = cells[0]["cell"]
    assert isinstance(cell_value, dict)
    cast(dict[str, object], cell_value)["task_id"] = "cal-drift"
    with pytest.raises(ResultRefusal, match="cell_identity"):
        BaselineResultV2.from_mapping(value)


def test_completed_result_requires_every_planned_record() -> None:
    value = _complete_result().to_mapping()
    cells_value = value["cells"]
    assert isinstance(cells_value, list)
    cast(list[object], cells_value).pop()
    with pytest.raises(ResultRefusal, match="completed_cells"):
        BaselineResultV2.from_mapping(value)


def test_sidecar_schema_backend_status_and_cost_are_bound() -> None:
    value = _complete_result().to_mapping()
    _, sidecar, _, _ = _first_correspondence_parts(value)
    sidecar["schema"] = "unknown-sidecar-v1"
    with pytest.raises(ResultRefusal, match="sidecar_schema"):
        BaselineResultV2.from_mapping(value)

    value = _complete_result().to_mapping()
    _, sidecar, _, _ = _first_correspondence_parts(value)
    sidecar["target_backend"] = (
        "sqlite" if sidecar["target_backend"] == "postgresql" else "postgresql"
    )
    with pytest.raises(ResultRefusal, match="sidecar_backend"):
        BaselineResultV2.from_mapping(value)

    value = _complete_result().to_mapping()
    _, _, verification, _ = _first_correspondence_parts(value)
    verification["verified"] = False
    with pytest.raises(ResultRefusal, match="sidecar_verified"):
        BaselineResultV2.from_mapping(value)

    value = _complete_result().to_mapping()
    _, _, _, nested_cost = _first_correspondence_parts(value)
    nested_cost["correspondence_failures"] = 1
    with pytest.raises(ResultRefusal, match="sidecar_cost_mismatch"):
        BaselineResultV2.from_mapping(value)


@pytest.mark.parametrize("forged", [False, 0.0])
def test_nested_cost_type_cannot_impersonate_integer_zero(forged: object) -> None:
    value = _complete_result().to_mapping()
    _, _, _, nested_cost = _first_correspondence_parts(value)
    nested_cost["correspondence_failures"] = forged
    with pytest.raises(ResultRefusal, match="sidecar_cost_mismatch"):
        BaselineResultV2.from_mapping(value)


def test_verified_sidecar_rejects_failure_cost() -> None:
    value = _complete_result().to_mapping()
    record, _, _, nested_cost = _first_correspondence_parts(value)
    cost_value = record["cost"]
    assert isinstance(cost_value, dict)
    cost = cast(dict[str, object], cost_value)
    cost["correspondence_failures"] = 1
    nested_cost["correspondence_failures"] = 1
    with pytest.raises(ResultRefusal, match="verified_cost_failures"):
        BaselineResultV2.from_mapping(value)


def test_non_dataclass_sidecar_cannot_enter_result() -> None:
    collector = ResultV2Collector(_plan())
    with pytest.raises(ResultRefusal, match="to_dict"):
        collector.add_correspondence(
            {"arm_id": "current_graph_baseline:postgresql", "task_id": "cal-01", "repetition": 1},
            object(),
            observed_backend="postgresql",
            target_backend="postgresql",
            status="gap",
            gap_reason="unavailable",
            cost=CorrespondenceCostSample(),
        )

def test_gap_sidecar_retains_cost_without_verified_claim() -> None:
    collector = ResultV2Collector(_plan())
    collector.add_correspondence(
        {"arm_id": "current_graph_baseline:postgresql", "task_id": "cal-01", "repetition": 1},
        _Sidecar(arm_id="current_graph_baseline:postgresql"),
        observed_backend="postgresql",
        target_backend="postgresql",
        status="gap",
        gap_reason="unavailable",
        cost=CorrespondenceCostSample(correspondence_failures=1),
    )
    result = collector.finish(
        status="failed", failure_code="correspondence_gap", raw_journal_members=_MEMBERS,
    )
    mapping = result.to_mapping()
    correspondence_value = mapping["correspondence"]
    assert isinstance(correspondence_value, list)
    correspondence = cast(list[dict[str, object]], correspondence_value)
    sidecar_value = correspondence[0]["sidecar"]
    assert isinstance(sidecar_value, dict)
    sidecar = cast(dict[str, object], sidecar_value)
    verification_value = sidecar["verification"]
    assert isinstance(verification_value, dict)
    verification = cast(dict[str, object], verification_value)
    verification_cost_value = verification["cost"]
    assert isinstance(verification_cost_value, dict)
    verification_cost = cast(dict[str, object], verification_cost_value)
    assert verification["verified"] is False
    assert verification["gap_reason"] == "unavailable"
    assert verification_cost["correspondence_failures"] == 1


def test_frame_digest_tampering_is_refused() -> None:
    raw = _encoded(_complete_result())
    lines = raw.splitlines(keepends=True)
    frame_index = next(
        index for index, line in enumerate(lines)
        if line.startswith(b"REPO_MAP_W5_RESULT_V2 ")
    )
    frame = json.loads(lines[frame_index][len(b"REPO_MAP_W5_RESULT_V2 "):].decode("ascii"))
    frame["sha256"] = "sha256:" + "0" * 64
    lines[frame_index] = (
        b"REPO_MAP_W5_RESULT_V2 "
        + json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("ascii")
        + b"\n"
    )
    with pytest.raises(ResultRefusal, match="digest"):
        decode_result_frames(b"".join(lines))
