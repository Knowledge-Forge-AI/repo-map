"""Pure native adapter byte accounting with controlled process observations."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from common_lore_index.retrieval.query_contracts import MatchSurface
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT, binding_id_for_alias
from retrieval_evaluation_accounting import EvaluatorByteBreakdownV1
import retrieval_evaluation_native as native
from retrieval_evaluation_native import execute_native_baseline_task_with_breakdown
from retrieval_evaluation_schema import EvaluationTask, load_task_catalog
from retrieval_evaluation_views import MaterializedNativeView, _render_extracted_metadata_lines
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection


def _native_double_task_and_view(
    tmp_path: Path,
) -> tuple[EvaluationTask, MaterializedNativeView]:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    task = replace(
        catalog.calibration_tasks()[0],
        selected_bindings=("core",),
        source_path_prefix=None,
        requested_mode="literal_captured_text",
        intended_match_surface="captured_text",
        permitted_query_plan={"query": "token", "patterns": ["token"], "limit": 1},
    )
    rel_path = "core/pkg/pipeline.py"
    binding_id = binding_id_for_alias("core", task.graph_id)
    view = MaterializedNativeView(
        view_root=tmp_path,
        selected_relative_paths=(rel_path,),
        path_to_binding={rel_path: (binding_id, "pkg/pipeline.py")},
        path_to_surface={rel_path: MatchSurface.CAPTURED_TEXT},
        excluded_bindings={},
    )
    return task, view


def test_rendered_metadata_uses_the_portable_raw_payload_and_source_identity(tmp_path: Path) -> None:
    inputs, _policy = build_fixture_projection(spool_dir=tmp_path)
    binding = binding_id_for_alias("feeds")
    row = {
        "source_ordinal": 0, "kind": "feed.item", "source_id": "public-feed",
        "path": "feeds/items.xml", "payload_json": {"metadata": {
            "binding_id": binding, "source_relative_path": "items.xml",
            "title": "PUBLIC_METADATA_TITLE",
        }},
    }
    bundle = replace(inputs.bundle, families={**inputs.bundle.families, "raw_observations": (row,)})
    lines = _render_extracted_metadata_lines(bundle, binding, "items.xml")
    assert len(lines) == 1 and "PUBLIC_METADATA_TITLE" in lines[0]
    assert _render_extracted_metadata_lines(bundle, "other-binding", "items.xml") == []
    assert _render_extracted_metadata_lines(bundle, binding, "other.xml") == []
    invalid = {**row, "payload_json": {}, "source_binding_id": binding, "metadata": {"title": "SPOOFED_TOP_LEVEL"}}
    malformed = replace(bundle, families={**bundle.families, "raw_observations": (invalid,)})
    with pytest.raises(ValueError, match="native_metadata_observation_missing"):
        _render_extracted_metadata_lines(malformed, binding, "items.xml")


def _stdout_with_duplicate_candidates(size: int = 495_781) -> bytes:
    first = b"core/pkg/pipeline.py\x007\x00token\n"
    second_prefix = b"core/pkg/pipeline.py\x007\x00"
    filler = size - len(first) - len(second_prefix) - 1
    assert filler >= 0
    return first + second_prefix + (b"x" * filler) + b"\n"


def test_native_breakdown_observes_raw_candidates_hits_and_serialized_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, view = _native_double_task_and_view(tmp_path)
    raw = _stdout_with_duplicate_candidates()
    fake = native.GitGrepRunResult(
        "completed_match", 0, raw, "", 17, ("fake-git",),
    )
    monkeypatch.setattr(native, "run_git_grep_process", lambda *args, **kwargs: fake)

    state, envelope, elapsed, legacy, breakdown = (
        execute_native_baseline_task_with_breakdown(task, view, git_executable="fake-git")
    )

    assert state.value == "completed"
    assert elapsed == 17
    assert len(envelope.hits) == 1
    assert legacy.observed_output_payload_bytes == 495_781
    assert breakdown.raw_process_stdout_bytes == 495_781
    assert breakdown.native_process_stdout_cap_bytes == 1_048_576
    assert breakdown.decoded_candidate_count == 2
    assert breakdown.returned_hit_count == 1
    assert breakdown.serialized_envelope_bytes < 495_781


def test_native_breakdown_retains_partial_stdout_on_bounded_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, view = _native_double_task_and_view(tmp_path)
    fake = native.GitGrepRunResult(
        "failed_stdout_overflow", -2, b"x" * 1_048_576,
        "private stderr must not be copied", 23, ("fake-git",),
    )
    monkeypatch.setattr(native, "run_git_grep_process", lambda *args, **kwargs: fake)

    state, envelope, elapsed, legacy, breakdown = (
        execute_native_baseline_task_with_breakdown(task, view, git_executable="fake-git")
    )

    assert state.value == "failed"
    assert elapsed == 23
    assert legacy.observed_output_payload_bytes == 1_048_576
    assert breakdown.raw_process_stdout_bytes == 1_048_576
    assert breakdown.native_process_stdout_cap_bytes == 1_048_576
    assert breakdown.decoded_candidate_count == 0
    assert breakdown.returned_hit_count == 0
    assert breakdown.serialized_envelope_bytes is not None
    assert "private stderr" not in str(envelope.to_dict())


def test_v1_correspondence_rejects_bool_and_float_before_coercion() -> None:
    baseline = EvaluatorByteBreakdownV1()
    with pytest.raises(ValueError, match="correspondence"):
        baseline.with_correspondence(bytes_read=True, elapsed_ns=1)
    with pytest.raises(ValueError, match="correspondence"):
        # Deliberately malformed runtime input remains part of this boundary test.
        baseline.with_correspondence(bytes_read=1, elapsed_ns=cast(Any, 1.5))


def test_v1_rejects_hits_when_no_candidates_were_decoded() -> None:
    with pytest.raises(ValueError, match="returned_hits_exceed_decoded_candidates"):
        EvaluatorByteBreakdownV1(decoded_candidate_count=0, returned_hit_count=1).validate()
