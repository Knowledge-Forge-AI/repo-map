"""Pure mixed-log framing tests for opt-in result-v2 transport."""

from __future__ import annotations

import io

import pytest

from retrieval_evaluation_grading import ExecutionState
import retrieval_semantic_baseline_result_frames as frames
from retrieval_semantic_baseline_result_frames import (
    decode_result_frames,
    emit_result_frames,
)
from retrieval_semantic_baseline_result_objects import BaselineResultV2, ResultV2Collector
from retrieval_semantic_baseline_results import ResultRefusal
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentPlan


_DIGEST = "sha256:" + "a" * 64
_MEMBERS = {
    "declaration.json": b"decl\n",
    "source-manifest.json": b"manifest\n",
    "sources.zip": b"zip",
    "observations.jsonl": b"{}\n",
    "report.json": b"report\n",
    "terminal.json": b"terminal\n",
}


def _result() -> BaselineResultV2:
    plan = ExperimentPlan(
        attempt_id="w5-semantic-g1",
        generation=1,
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
        arms=("exact_vector",),
    ).validate()
    collector = ResultV2Collector(plan)
    for repetition in range(1, plan.repetitions + 1):
        collector.add_cell(
            {"arm_id": "exact_vector", "task_id": "cal-01", "repetition": repetition},
            ExperimentCell(
                "exact_vector", "cal-01", ExecutionState.COMPLETED,
                candidates=(), elapsed_ns=1, query_bytes=1,
                cleanup_status="verified",
            ),
        )
    return collector.finish(status="completed", raw_journal_members=_MEMBERS)


def _encoded(result: BaselineResultV2) -> bytes:
    stream = io.StringIO()
    emit_result_frames((result,), stream=stream)
    return stream.getvalue().encode("ascii")


def test_v2_frame_survives_mixed_log_above_v2_cap() -> None:
    result = _result()
    inherited_log = b"legacy diagnostics\n" + b"L" * (
        frames.MAX_RESULT_INPUT_BYTES + 1
    ) + b"\n"
    decoded = decode_result_frames(inherited_log + _encoded(result))
    assert decoded["w5-semantic-g1"].to_mapping() == result.to_mapping()
    assert len(inherited_log + _encoded(result)) < frames.MAX_RESULT_LOG_BYTES


def test_v2_aggregate_frame_budget_remains_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _result()
    encoded = _encoded(result)
    monkeypatch.setattr(frames, "MAX_RESULT_INPUT_BYTES", len(encoded) - 2)
    with pytest.raises(ResultRefusal, match="input_size"):
        emit_result_frames((result,), stream=io.StringIO())


def test_decoder_rejects_v2_prefixed_lines_over_aggregate_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = _encoded(_result())
    frame = next(
        line for line in encoded.splitlines(keepends=True)
        if line.startswith(frames.RESULT_LINE_PREFIX.encode("ascii"))
    )
    monkeypatch.setattr(frames, "MAX_RESULT_INPUT_BYTES", len(frame) - 1)
    with pytest.raises(ResultRefusal, match="input_size"):
        decode_result_frames(frame)


def test_mixed_log_uses_inherited_total_log_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(frames, "MAX_RESULT_LOG_BYTES", 1024)
    with pytest.raises(ResultRefusal, match="input_size"):
        decode_result_frames(b"L" * 1025)


@pytest.mark.parametrize(
    ("raw", "reason"),
    (
        (b"legacy diagnostics\n", "missing"),
        (frames.RESULT_LINE_PREFIX.encode("ascii") + b"{}\n", "fields"),
    ),
)
def test_missing_or_invalid_v2_frames_remain_refused(raw: bytes, reason: str) -> None:
    with pytest.raises(ResultRefusal, match=reason):
        decode_result_frames(raw)
