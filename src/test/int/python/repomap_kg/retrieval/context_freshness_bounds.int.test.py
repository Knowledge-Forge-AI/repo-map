"""Storage-to-packet freshness checks retain root and output-budget authority."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest, FreshnessCheckConfig
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


def test_freshness_missing_root_is_cached_as_unavailable(tmp_path: Path) -> None:
    """A caller-selected root that does not exist yields a safe per-location refusal."""
    _db, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path / "fixture")
    missing_root = tmp_path / "does-not-exist"
    request = ContextRequest(
        graph_id=CTX_GRAPH_ID,
        mode="exact_identity",
        canonical_key="py:pkg.billing.InvoiceService",
        freshness="check",
        source_roots={BINDING_CORE: missing_root},
    )
    with adapter:
        packet = build_compact_context(
            request,
            adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: missing_root}
            ),
        )
    assert_valid_context_packet(packet)
    location = packet["items"][0]["locations"][0]
    assert location["freshness"]["state"] == "unavailable"
    assert location["freshness"]["reason"] == "missing_root"
    assert packet["freshness"]["counts"]["unavailable"] >= 1


def test_freshness_rejects_symlinked_root_and_invalid_relative_path(tmp_path: Path) -> None:
    """Root and descriptor traversal are refused before any source bytes are exposed."""
    root_dir = tmp_path / "fixture"
    _db, cfg, _graph, _binding, adapter = build_sqlite_context_fixture(root_dir)
    core_root = Path(cfg.graphs[0].root_path)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(core_root, target_is_directory=True)
    with adapter:
        root_packet = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: linked_root},
            ),
            adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: linked_root}
            ),
        )
    assert_valid_context_packet(root_packet)
    assert root_packet["items"][0]["locations"][0]["freshness"]["reason"] == (
        "symlink_or_traversal_rejected"
    )

    traversal_root = tmp_path / "traversal"
    traversal_root.mkdir()
    extra = {
        "canonical_key": "py:pkg.billing.Traversal",
        "kind": "python.function",
        "display_name": "Traversal",
        "raw_kind": "python.function",
        "binding_id": BINDING_CORE,
        "snapshot_id": SNAP_CORE,
        "path": "../outside.py",
        "start_line": 1,
        "end_line": 1,
    }
    # A fresh fixture keeps the malformed descriptor in the database while the
    # selected root remains a real directory, so the path grammar is exercised
    # independently from root opening.
    _db2, _cfg2, _graph2, _binding2, adapter2 = build_sqlite_context_fixture(
        tmp_path / "fixture-traversal", extra_subjects=(extra,)
    )
    with adapter2:
        traversal_packet = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.Traversal",
                freshness="check",
                source_roots={BINDING_CORE: traversal_root},
            ),
            adapter2,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: traversal_root}
            ),
        )
    assert_valid_context_packet(traversal_packet)
    assert traversal_packet["items"][0]["locations"][0]["freshness"]["reason"] == (
        "ineligible_location"
    )


def test_freshness_accepts_lf_without_final_newline(tmp_path: Path) -> None:
    """Descriptor-anchored line counting accepts an ordinary file without an EOF newline."""
    root_dir = tmp_path / "fixture"
    canonical_key = "py:pkg.billing.NoFinalNewline"
    extra = {
        "canonical_key": canonical_key,
        "kind": "python.function",
        "display_name": "NoFinalNewline",
        "raw_kind": "python.function",
        "binding_id": BINDING_CORE,
        "snapshot_id": SNAP_CORE,
        "path": "src/no_final_newline.py",
        "start_line": 1,
        "end_line": 2,
    }
    _db, cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        root_dir, extra_subjects=(extra,)
    )
    source_root = Path(cfg.graphs[0].root_path)
    source = source_root / "src/no_final_newline.py"
    source.write_text("one\ntwo", encoding="utf-8")
    with adapter:
        packet = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key=canonical_key,
                freshness="check",
                source_roots={BINDING_CORE: source_root},
            ),
            adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: source_root}
            ),
        )
    assert_valid_context_packet(packet)
    observation = packet["items"][0]["locations"][0]["freshness"]
    assert observation["state"] == "no_change_observed_with_limits"
    assert packet["freshness"]["files_checked"] == 1
    assert packet["freshness"]["bytes_read"] == len("one\ntwo")


def test_freshness_file_limit_reports_unchecked_locations(tmp_path: Path) -> None:
    """The sixteen-file cap is reported per location while admitted items remain intact."""
    root_dir = tmp_path / "fixture"
    extras = tuple(
        {
            "canonical_key": f"py:pkg.billing.Limit{i:02d}",
            "kind": "python.function",
            "display_name": f"Limit{i:02d}",
            "raw_kind": "python.function",
            "binding_id": BINDING_CORE,
            "snapshot_id": SNAP_CORE,
            "path": f"src/limit_{i:02d}.py",
            "start_line": 1,
            "end_line": 1,
        }
        for i in range(17)
    )
    _db, cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        root_dir, extra_subjects=extras
    )
    source_root = Path(cfg.graphs[0].root_path)
    for i in range(17):
        (source_root / f"src/limit_{i:02d}.py").write_text(
            f"def limit_{i:02d}():\n", encoding="utf-8"
        )
    with adapter:
        packet = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="Limit",
                bindings=(BINDING_CORE,),
                path_prefixes={BINDING_CORE: ("src",)},
                kinds=("python.function",),
                max_items=17,
                budget_bytes=65536,
                freshness="check",
                source_roots={BINDING_CORE: source_root},
            ),
            adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: source_root}
            ),
        )
    assert_valid_context_packet(packet)
    observations = [
        loc["freshness"]
        for item in packet["items"]
        for loc in item["locations"]
    ]
    assert len(observations) == 17
    assert packet["freshness"]["files_checked"] == 16
    assert sum(obs["reason"] == "file_limit" for obs in observations) == 1
    assert packet["freshness"]["counts"]["not_checked"] >= 1
