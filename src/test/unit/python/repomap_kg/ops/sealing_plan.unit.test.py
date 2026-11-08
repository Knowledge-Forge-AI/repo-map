"""Read-only metadata sealing plan: refusals, counts, bounds and canonical output."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.cli.ops_sealing_plan_commands as plan_commands
from common_lore_index.artifacts.sealing_governance import SealingBudget
from common_lore_index.ops.sealing_plan import (
    MAX_PLAN_BYTES, PLAN_SCHEMA, SealingPlanRefusal, build_sealing_plan, render_plan_text,
)
from repomap_test_support.sealing_governance_fixtures import (
    GRAPH_ID, binding_for, expectation_for, graph_for, record_opens, write_tree,
)

FILES = {"a.txt": b"a" * 100, "sub/b.py": b"b = 1\n", "sub/deep/c.txt": b"c" * 7, "zz-sentinel.txt": b"s"}


def _config(tmp_path: Path, **graph_changes: Any) -> tuple[SimpleNamespace, Path]:
    root = write_tree(tmp_path / "entry", FILES)
    graph = replace(graph_for(binding_for("entry", root)), **graph_changes)
    return SimpleNamespace(graphs=(graph,)), root


def test_plan_counts_equal_an_independent_metadata_walk_and_open_no_body(tmp_path: Path, monkeypatch) -> None:
    config, root = _config(tmp_path)
    expected = expectation_for(root, FILES)
    with record_opens(monkeypatch) as opened:
        plan = build_sealing_plan(config, GRAPH_ID)
    payload = plan.to_payload()
    assert opened.names == [], "metadata only: no body or descriptor open"
    assert payload["refusal"] is None and payload["instrumentation"] == "complete"
    assert (payload["bindings"], payload["inventory_files"], payload["inventory_bytes"]) == (
        1, len(FILES), expected.total,
    )
    assert payload["directory_entries"] == expected.listed_entries
    assert payload["opens"] == expected.walked_directories
    assert payload["planned_min_read_bytes"] == 6 * expected.total + 1
    assert payload["planned_min_write_bytes"] == expected.total
    assert payload["projected_directory_entries"] == 3 * expected.listed_entries
    assert payload["effective_max_directory_entries"] == 100_000
    assert payload["factors"] == {
        "full_body_reads_per_file": 6, "collision_extra_reads_per_file": 2, "stable_capture_max_attempts": 3,
    }


def test_plan_output_is_canonical_identity_free_and_bounded(tmp_path: Path) -> None:
    config, root = _config(tmp_path)
    plan = build_sealing_plan(config, GRAPH_ID)
    data = plan.canonical_json()
    assert len(data) <= MAX_PLAN_BYTES
    assert json.loads(data)["schema"] == PLAN_SCHEMA
    assert data == json.dumps(json.loads(data), sort_keys=True, separators=(",", ":")).encode()
    text = data.decode() + render_plan_text(plan)
    for forbidden in (str(root), str(tmp_path), GRAPH_ID, "a.txt", "sentinel"):
        assert forbidden not in text


@pytest.mark.parametrize(("budget", "refusal"), [
    (SealingBudget(max_directory_entries=2), "directory_entries"),
    (SealingBudget(max_opens=1), "opens"),
    (SealingBudget(max_elapsed_ms=0), "elapsed_ms"),
])
def test_explicit_governed_ceilings_refuse_with_partial_counts(tmp_path: Path, budget, refusal: str) -> None:
    config, _root = _config(tmp_path)
    plan = build_sealing_plan(config, GRAPH_ID, budget)
    payload = plan.to_payload()
    assert payload["refusal"] == refusal and payload["instrumentation"] == "incomplete"
    assert payload["inventory_files"] is None and payload["planned_min_read_bytes"] is None
    if budget.max_directory_entries is not None:
        assert payload["directory_entries"] == 2 and payload["effective_max_directory_entries"] == 2


def test_inventory_predicate_refusals_are_named_without_paths(tmp_path: Path, monkeypatch) -> None:
    import common_lore_index.ops.sealing_plan as sealing_plan
    from common_lore_index.artifacts._manifest_records import ArtifactLimits

    config, _root = _config(tmp_path)
    monkeypatch.setattr(sealing_plan, "DEFAULT_ARTIFACT_LIMITS", ArtifactLimits(max_artifacts=2))
    assert build_sealing_plan(config, GRAPH_ID).refusal == "inventory_max_artifacts"
    monkeypatch.setattr(sealing_plan, "DEFAULT_ARTIFACT_LIMITS", ArtifactLimits(max_total_bytes=10))
    assert build_sealing_plan(config, GRAPH_ID).refusal == "inventory_max_total_bytes"


def _unsupported(tmp_path: Path) -> SimpleNamespace:
    root = write_tree(tmp_path / "entry", FILES)
    return SimpleNamespace(graphs=(graph_for(replace(binding_for("entry", root), enabled=False)),))


@pytest.mark.parametrize(("build", "graph_id", "code"), [
    (lambda tmp: _config(tmp)[0], "unknown-graph", "sealing-plan-unknown-graph"),
    (lambda tmp: _config(tmp, enabled=False)[0], GRAPH_ID, "sealing-plan-graph-disabled"),
    (_unsupported, GRAPH_ID, "sealing-plan-graph-unsupported"),
])
def test_cheap_refusals_precede_any_traversal(tmp_path: Path, build, graph_id: str, code: str, monkeypatch) -> None:
    config = build(tmp_path)

    def no_walk(*args: object, **kwargs: object) -> None:
        raise AssertionError("traversal before a cheap refusal")

    monkeypatch.setattr(os, "scandir", no_walk)
    with pytest.raises(SealingPlanRefusal, match=code):
        build_sealing_plan(config, graph_id)


def test_unavailable_roots_refuse_before_traversal(tmp_path: Path) -> None:
    graph = graph_for(binding_for("entry", tmp_path / "missing"))
    with pytest.raises(SealingPlanRefusal, match="sealing-plan-root-unavailable"):
        build_sealing_plan(SimpleNamespace(graphs=(graph,)), GRAPH_ID)


def test_symlinked_and_excluded_entries_follow_discovery_selection(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "entry", {"keep.txt": b"k" * 5, "skip/x.txt": b"x" * 50})
    (root / "alias.txt").symlink_to(root / "keep.txt")
    graph = graph_for(binding_for("entry", root, exclude_paths=("skip",)))
    payload = build_sealing_plan(SimpleNamespace(graphs=(graph,)), GRAPH_ID).to_payload()
    assert (payload["inventory_files"], payload["inventory_bytes"]) == (1, 5)
    assert payload["inventory_symlinked_files"] == 1, "the alias is counted, then deduplicated onto its target"


def test_cli_dispatch_prints_json_or_text_and_refusals_exit_one(tmp_path: Path, monkeypatch, capsys) -> None:
    config, _root = _config(tmp_path)
    monkeypatch.setattr(plan_commands, "_load_config", lambda args: config)
    from common_lore_index.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(["ops", "sealing-plan", "--graph", GRAPH_ID, "--json"])
    assert plan_commands.dispatch_ops_sealing_plan_command(args, lambda *a, **k: None) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == PLAN_SCHEMA
    text_args = parser.parse_args(["ops", "sealing-plan", "--graph", GRAPH_ID, "--sealing-max-entries", "1"])
    assert plan_commands.dispatch_ops_sealing_plan_command(text_args, lambda *a, **k: None) == 1
    assert "refusal: directory_entries" in capsys.readouterr().out
    errors: list[str] = []
    missing = parser.parse_args(["ops", "sealing-plan", "--graph", "absent"])
    assert plan_commands.dispatch_ops_sealing_plan_command(missing, lambda e, **k: errors.append(str(e))) == 1
    assert errors == ["sealing-plan-unknown-graph"]
    other = parser.parse_args(["ops", "graphs"])
    assert plan_commands.dispatch_ops_sealing_plan_command(other, lambda *a, **k: None) is None
    with pytest.raises(SystemExit):
        parser.parse_args(["ops", "sealing-plan", "--graph", GRAPH_ID, "--sealing-max-read-bytes", "1"])
