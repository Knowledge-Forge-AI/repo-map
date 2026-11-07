"""Bounded report-only accounting projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import io
from typing import cast

from retrieval_semantic_baseline_result_frames import (
    MAX_RESULT_BYTES,
    MAX_RESULT_INPUT_BYTES,
    RESULT_LINE_PREFIX,
    emit_result_frames,
)
from retrieval_semantic_baseline_result_objects import BaselineResultV2
from retrieval_semantic_pair_artifacts import JournalArtifact, digest_bytes, refuse


def validate_result_input_lengths(lengths: Sequence[int]) -> None:
    """Apply the canonical individual V2 result-data ceiling."""

    if any(type(length) is not int or length < 0 for length in lengths):
        raise refuse("pair_result_v2_size")
    if any(length > MAX_RESULT_BYTES for length in lengths):
        raise refuse("pair_result_v2_size")


def source_provenance(
    journal: JournalArtifact,
    result: Mapping[str, object],
    result_raw: bytes,
    generation: int,
) -> dict[str, object]:
    member_digests = journal.member_digests
    member_lengths = journal.member_lengths
    return {
        "generation": generation,
        "attempt_id": journal.attempt_id,
        "journal_status": journal.terminal.get("status"),
        "legacy_report": {
            "status": journal.report.get("status"),
            "failure_code": journal.report.get("failure_code"),
        },
        "journal_members": {
            name: {"length": member_lengths[name], "sha256": member_digests[name]}
            for name in sorted(member_digests)
        },
        "result_v2": {
            "length": len(result_raw),
            "sha256": digest_bytes(result_raw),
            "status": result.get("status"),
            "failure_code": result.get("failure_code"),
        },
    }


def encoded_result_frame_size(result: BaselineResultV2) -> int:
    """Measure the canonical encoded frame using the established serializer."""

    stream = io.StringIO()
    emit_result_frames((result,), stream=stream)
    frames = [
        line.encode("ascii")
        for line in stream.getvalue().splitlines(keepends=True)
        if line.startswith(RESULT_LINE_PREFIX)
    ]
    if len(frames) != 1:
        raise refuse("pair_result_v2_frame")
    return len(frames[0])


def validate_result_frame_budget(lengths: Sequence[int]) -> None:
    """Apply the canonical aggregate encoded-frame input ceiling."""

    if any(type(length) is not int or length < 0 for length in lengths):
        raise refuse("pair_result_v2_input_size")
    if sum(lengths) > MAX_RESULT_INPUT_BYTES:
        raise refuse("pair_result_v2_input_size")


def cal07_values(pairs: Sequence[Mapping[str, object]]) -> list[int]:
    values: list[int] = []
    for pair in pairs:
        identity = pair.get("identity")
        if not isinstance(identity, Mapping) or (
            identity.get("generation"), identity.get("task_id"), identity.get("arm_id")
        ) != (1, "cal-07", "native_tools_baseline"):
            continue
        result = pair.get("result_v2")
        accounting = result.get("byte_work") if isinstance(result, Mapping) else None
        if isinstance(accounting, Mapping) and type(accounting.get("raw_process_stdout_bytes")) is int:
            values.append(cast(int, accounting["raw_process_stdout_bytes"]))
    return values


def generation_2_limitation(
    pairs: Sequence[Mapping[str, object]], summaries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    whole = None
    for summary in summaries:
        if summary.get("generation") != 2:
            continue
        denominator = summary.get("denominators")
        if isinstance(denominator, Mapping):
            whole = denominator.get("whole")
    recorded_unavailable = 0
    for pair in pairs:
        identity = pair.get("identity")
        observation = pair.get("journal_observation")
        if (
            isinstance(identity, Mapping)
            and identity.get("generation") == 2
            and isinstance(observation, Mapping)
            and observation.get("reason") == "unsupported_semantic_query_mode"
        ):
            recorded_unavailable += 1
    return {
        "document_only": {"value": None, "evidence_status": "not_recorded"},
        "component_querycount": {"value": None, "evidence_status": "not_recorded"},
        "recorded_unavailable_observations": recorded_unavailable,
        "whole_denominator": whole,
        "context": "The retained six-member/V2 evidence has no document-only or component query-count field.",
    }


__all__ = [
    "cal07_values", "encoded_result_frame_size", "generation_2_limitation",
    "source_provenance", "validate_result_frame_budget", "validate_result_input_lengths",
]
