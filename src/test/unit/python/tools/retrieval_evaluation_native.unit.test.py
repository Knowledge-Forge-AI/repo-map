"""Unit tests for native git-grep argv construction, NUL-delimited framing, and exit semantics (S3)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.retrieval.query_contracts import MatchSurface, QueryScope, QueryMode
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT, binding_id_for_alias,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask, load_task_catalog
import retrieval_evaluation_native as native
from retrieval_evaluation_views import MaterializedNativeView
from retrieval_evaluation_native import (
    build_git_grep_argv,
    classify_git_grep_exit,
    parse_git_grep_z_output,
)


def test_git_grep_argv_enforces_safe_single_thread_fixed_string_flags() -> None:
    """build_git_grep_argv constructs an argv vector with -F -n -I -z --threads=1 and -e terminator."""
    argv = build_git_grep_argv(
        "--malicious-looking-pattern",
        ("core/pkg/pipeline.py", "companion/docs/architecture.md"),
        git_executable="/usr/bin/git",
    )
    assert argv == (
        "/usr/bin/git",
        "--no-pager",
        "-c",
        "core.attributesFile=/dev/null",
        "grep",
        "--no-index",
        "--threads=1",
        "-F",
        "-n",
        "-I",
        "-z",
        "--no-color",
        "--no-textconv",
        "-e",
        "--malicious-looking-pattern",
        "--",
        "core/pkg/pipeline.py",
        "companion/docs/architecture.md",
    )

    with pytest.raises(ValueError, match="non-empty"):
        build_git_grep_argv("", ("core/pkg/pipeline.py",))
    with pytest.raises(ValueError, match="selected_paths"):
        build_git_grep_argv("token", ())


def test_parse_git_grep_z_output_handles_colons_newlines_and_rejects_malformed_framing() -> None:
    """NUL-delimited git grep -z -n output parses path\\0line\\0text\\n and fails closed on bad framing."""
    raw = (
        b"core/pkg/colon:name.py\x0042\x00def key: value = 'a:b:c'\n"
        b"companion/docs/line\nbreak.md\x007\x00Heading: overview\n"
    )
    mapping = {
        "core/pkg/colon:name.py": ("bind1:core", "pkg/colon:name.py"),
        "companion/docs/line\nbreak.md": ("bind1:companion", "docs/line\nbreak.md"),
    }
    locators = parse_git_grep_z_output(raw, path_to_binding=mapping)
    assert len(locators) == 2
    assert locators[0].binding_id == "bind1:core"
    assert locators[0].source_relative_path == "pkg/colon:name.py"
    assert locators[0].start_line == 42 and locators[0].end_line == 42
    assert locators[1].binding_id == "bind1:companion"
    assert locators[1].source_relative_path == "docs/line\nbreak.md"
    assert locators[1].start_line == 7 and locators[1].end_line == 7

    for bad_raw in (
        b"no_nul_delimiter_at_all\n",
        b"core/pkg/colon:name.py\x00missing_second_nul\n",
        b"core/pkg/colon:name.py\x00not_an_int\x00text\n",
        b"unmapped/file.py\x0010\x00text\n",
    ):
        with pytest.raises(ValueError):
            parse_git_grep_z_output(bad_raw, path_to_binding=mapping)


def test_git_grep_exit_code_classification_distinguishes_no_match_from_failure() -> None:
    """Exit code 0 is match, 1 with empty stderr is no-match, and >1 or error stderr is failure."""
    assert classify_git_grep_exit(0, "") == "completed_match"
    assert classify_git_grep_exit(1, "") == "completed_no_match"
    assert classify_git_grep_exit(1, "fatal: bad flag") == "failed"
    assert classify_git_grep_exit(2, "fatal: error") == "failed"
    assert classify_git_grep_exit(128, "fatal: error") == "failed"


def _direct_task_and_view(
    tmp_path: Path, *, selected_bindings: tuple[str, ...] = ("core",),
    source_path_prefix: str | None = None,
) -> tuple[EvaluationTask, MaterializedNativeView]:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    task = next(item for item in catalog.tasks if item.task_id == "cal-24")
    task = replace(task, selected_bindings=selected_bindings, source_path_prefix=source_path_prefix).validate()
    binding_id = binding_id_for_alias("core", task.graph_id)
    rel_path = "core/pkg/pipeline.py"
    view = MaterializedNativeView(
        view_root=tmp_path, selected_relative_paths=(rel_path,),
        path_to_binding={rel_path: (binding_id, "pkg/pipeline.py")},
        path_to_surface={rel_path: MatchSurface.CAPTURED_TEXT}, excluded_bindings={},
    )
    return task, view


def _native_scope(task: EvaluationTask) -> QueryScope:
    return QueryScope(
        graph_id=task.graph_id, backend="native_filesystem",
        selected_binding_ids=tuple(sorted(binding_id_for_alias(alias, task.graph_id) for alias in task.selected_bindings)),
        source_path_prefix=task.source_path_prefix,
    ).validate()


@pytest.mark.parametrize(
    ("selected_bindings", "source_path_prefix"),
    [("companion", None), ("core", "shared/")],
)
def test_native_direct_handoff_refuses_scope_mismatch_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    selected_bindings: str, source_path_prefix: str | None,
) -> None:
    task, view = _direct_task_and_view(
        tmp_path,
        selected_bindings=(selected_bindings,),
        source_path_prefix=source_path_prefix,
    )
    calls: list[str] = []
    monkeypatch.setattr(native, "consumer_navigate", lambda **_kwargs: calls.append("navigate"))
    monkeypatch.setattr(native, "handoff_recheck", lambda *_args, **_kwargs: calls.append("recheck"))

    state, envelope, elapsed, accounting = native._execute_direct_handoff_native(
        task, view, _native_scope(task), QueryMode(task.requested_mode),
    )
    assert state is ExecutionState.REFUSED
    assert envelope.refusal_code == "direct_handoff_scope_mismatch"
    assert envelope.scope.backend == "native_filesystem"
    assert elapsed == 0 and accounting.observed_output_payload_bytes == 0
    assert calls == []


def test_native_direct_handoff_keeps_a_frozen_in_scope_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    task, view = _direct_task_and_view(tmp_path)
    calls: list[str] = []

    def navigate(**_kwargs):
        calls.append("navigate")
        return {"outcome": "verified", "graph_calls": 0}

    def recheck(*_args, **_kwargs):
        calls.append("recheck")
        return [{"source_check": True}]

    monkeypatch.setattr(native, "consumer_navigate", navigate)
    monkeypatch.setattr(native, "handoff_recheck", recheck)
    state, envelope, _elapsed, _accounting = native._execute_direct_handoff_native(
        task, view, _native_scope(task), QueryMode(task.requested_mode),
    )
    assert state is ExecutionState.COMPLETED
    assert envelope.scope.backend == "native_filesystem"
    assert [hit.locator.source_relative_path for hit in envelope.hits] == ["pkg/pipeline.py"]
    assert calls == ["navigate", "recheck"]
