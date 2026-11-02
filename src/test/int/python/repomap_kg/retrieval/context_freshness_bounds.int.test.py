"""Storage-to-packet freshness checks retain root and output-budget authority."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.context_fixture import (
    BINDING_CORE, CTX_GRAPH_ID, SNAP_CORE, build_sqlite_context_fixture,
)


def _subjects() -> list[dict[str, object]]:
    return [
        {
            "canonical_key": f"py:anchor.{name}", "kind": "python.function",
            "display_name": f"Anchor{name}", "raw_kind": "python.function",
            "binding_id": BINDING_CORE, "snapshot_id": SNAP_CORE,
            "path": f"src/{name}.py", "start_line": 1, "end_line": 2,
        }
        for name in ("a", "b")
    ]


def test_assembly_anchors_root_across_locations_and_reselects_on_next_request(
    tmp_path: Path,
) -> None:
    _db, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        tmp_path / "fixture", extra_subjects=_subjects(),
    )
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    for name in ("a", "b"):
        (selected / "src" / f"{name}.py").write_text("first\nsecond\n")
    moved = tmp_path / "original"
    swapped = False

    def swap(part: str) -> None:
        nonlocal swapped
        if part == "a.py" and not swapped:
            swapped = True
            selected.rename(moved)
            (selected / "src").mkdir(parents=True)
            for name in ("a", "b"):
                (selected / "src" / f"{name}.py").write_text("")

    request = ContextRequest(
        graph_id=CTX_GRAPH_ID, query="Anchor", freshness="check",
        source_roots={BINDING_CORE: selected}, budget_bytes=16384,
    )
    with adapter:
        packet = build_compact_context(request, adapter, freshness_step_hook=swap)
    assert swapped
    locations = [loc for item in packet["items"] for loc in item["locations"]]
    assert len(locations) == 2
    assert {loc["freshness"]["state"] for loc in locations} == {"no_change_observed_with_limits"}
    assert packet["freshness"]["files_checked"] == 2
    assert packet["freshness"]["bytes_read"] == 26
    with adapter:
        next_packet = build_compact_context(request, adapter)
    assert next_packet["freshness"]["counts"]["changed_observed"] == 2
    assert next_packet["freshness"]["bytes_read"] == 0


@pytest.mark.parametrize("budget", (4096, 16384, 65536))
def test_only_finally_admitted_locations_are_opened_at_each_budget_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int,
) -> None:
    _db, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        tmp_path / "fixture", extra_subjects=_subjects(),
    )
    selected = tmp_path / "selected"
    (selected / "src").mkdir(parents=True)
    for name in ("a", "b"):
        (selected / "src" / f"{name}.py").write_text("one\ntwo\n")
    opened: list[str] = []
    real_open = os.open

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None and str(path) in {"a.py", "b.py"}:
            opened.append(str(path))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {tracking_open})
    with adapter:
        packet = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID, query="Anchor", freshness="check",
                source_roots={BINDING_CORE: selected}, budget_bytes=budget,
            ), adapter,
        )
    assert packet["status"] in {"complete", "partial"}
    raw = serialize_compact_json(packet)
    assert packet["work_ledger"]["actual_bytes"] == len(raw) <= budget
    admitted = [
        Path(loc["source_relative_path"]).name
        for item in (*packet["items"], *packet["neighbors"])
        for loc in item["locations"]
    ]
    assert sorted(opened) == sorted(admitted)
    assert len(opened) == packet["freshness"]["files_checked"]


def test_sqlite_expansion_keeps_relation_to_admitted_nonexpanded_seed(tmp_path: Path) -> None:
    subjects = _subjects()
    _db, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        tmp_path / "fixture", extra_subjects=subjects,
        extra_edges=[("calls", "py:anchor.a", "py:anchor.b")],
    )
    request = ContextRequest(
        graph_id=CTX_GRAPH_ID, mode="ranked_discovery", query="Anchor",
        kinds=("python.function",),
        bindings=(BINDING_CORE,), path_prefixes={BINDING_CORE: ("src",)},
        max_items=2, expand_depth=1, expand_seeds=1, freshness="none", budget_bytes=16384,
    )
    with adapter:
        packet = build_compact_context(request, adapter)
    assert_valid_context_packet(packet)
    assert packet["omission_counts"]["unlocatable_kind_pattern_excluded"] == 0
    assert packet["status"] == "complete", (packet["scope"], packet["omission_counts"], packet["expansion"])
    assert len(packet["items"]) == 2
    assert {item["canonical_key"] for item in packet["items"]} == {
        "py:anchor.a", "py:anchor.b",
    }
    assert packet["neighbors"] == []
    assert len(packet["relations"]) == 1
    assert {
        packet["relations"][0]["source_key"], packet["relations"][0]["target_key"],
    } == {"py:anchor.a", "py:anchor.b"}
    assert packet["expansion"]["seeds_expanded"] == 1
    assert packet["expansion"]["neighbors_admitted"] == 0
    assert packet["expansion"]["relations_admitted"] == 1
    assert packet["scope"]["scope_complete"] is True
    assert packet["omission_counts"]["output_budget"] == 0
