"""Real-filesystem sealing governance: exact counters, sentinel witness, equivalence.

Expectations are computed from the tree layout, never from the subject meter.
The sentinel witness records every ``os.open`` basename at the test boundary,
so it holds under any user identity (including root) without mode-000 files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.graph.multi_source import graph_source_binding_id
from repomap_test_support.sealing_governance_fixtures import (
    GRAPH_ID, binding_for, expectation_for, graph_for, open_descriptor_count, record_opens, seal, write_tree,
)

ENTRY = {
    "a-first.txt": b"first\n" * 1000,
    "nested/b.py": b"b = 2\n" * 3000,
    "nested/deeper/c.txt": os.urandom(1024 * 1024 + 3),
    "empty.txt": b"",
    "zz-sentinel.txt": b"sentinel body\n",
}
INPUT = {"input.txt": b"input\n" * 64, "z/empty.py": b""}


def _two_bindings(tmp_path: Path):
    entry = write_tree(tmp_path / "entry", ENTRY)
    other = write_tree(tmp_path / "input", INPUT)
    first_id = graph_source_binding_id(GRAPH_ID, "entry")
    alias = next(f"input{index}" for index in range(100)
                 if graph_source_binding_id(GRAPH_ID, f"input{index}") > first_id)
    graph = graph_for(binding_for("entry", entry), binding_for(alias, other))
    return graph, expectation_for(entry, ENTRY), expectation_for(other, INPUT)


def test_exact_counters_on_known_trees_new_and_collision(tmp_path: Path) -> None:
    graph, first, second = _two_bindings(tmp_path)
    plain = seal(graph, tmp_path / "plain")
    manifest = len(plain[0].canonical_bytes())
    total = first.total + second.total
    meter = SealingMeter(None, governed=False)
    metered = seal(graph, tmp_path / "store", io_meter=meter)
    assert (metered[0], metered[2]) == (plain[0], plain[2])
    snapshot = meter.snapshot()
    assert snapshot.read_bytes == 4 * total + manifest
    # The second empty body collides with the first by independently derived digest;
    # the manifest is one new object owned by the combined seal.
    second_collisions = second.collision_paths(first)
    assert snapshot.read_calls == (
        first.read_calls(0, collision=False, include_manifest=False)
        + second.read_calls(manifest, collision=False, collision_paths=second_collisions)
    )
    assert snapshot.opens == (
        first.opens(walks=2, collision=False, include_manifest=False)
        + second.opens(walks=2, collision=False)
    ), "the manifest put is counted once, not per binding"
    assert snapshot.fsyncs == (
        first.fsyncs(collision=False, include_manifest=False)
        + second.fsyncs(collision=False, collision_paths=second_collisions)
    )
    assert snapshot.directory_entries == 2 * (first.listed_entries + second.listed_entries)
    assert snapshot.write_bytes == total + manifest

    again = SealingMeter(None, governed=False)
    seal(graph, tmp_path / "store", io_meter=again)
    assert again.snapshot().read_bytes == 5 * total + 2 * manifest
    assert again.snapshot().reader("store") == 2 * (total + manifest)


def test_a_file_after_the_budget_point_is_never_opened(tmp_path: Path, monkeypatch) -> None:
    entry = write_tree(tmp_path / "entry", {"a.txt": b"a\n", "zz-sentinel.txt": b"never\n"})
    graph = graph_for(binding_for("entry", entry))
    # Opens: preflight listing, first-scan listing, a.txt capture; the sentinel capture is fourth.
    meter = SealingMeter(SealingBudget(max_opens=3), governed=True)
    before = open_descriptor_count()
    with record_opens(monkeypatch) as opened:
        with pytest.raises(SealingBudgetExceeded, match="opens"):
            seal(graph, tmp_path / "store", io_meter=meter)
    assert opened.opened("a.txt") and not opened.opened("zz-sentinel.txt")
    assert meter.snapshot().opens == 3 and meter.snapshot().reader("discovery") == 0 and meter.snapshot().reader("capture") == len(b"a\n")
    assert open_descriptor_count() == before


def test_planned_refusal_opens_no_body_at_all(tmp_path: Path, monkeypatch) -> None:
    graph, first, second = _two_bindings(tmp_path)
    total = first.total + second.total
    meter = SealingMeter(SealingBudget(max_read_bytes=4 * total), governed=True)
    with record_opens(monkeypatch) as opened:
        with pytest.raises(SealingBudgetExceeded, match="planned_read_bytes"):
            seal(graph, tmp_path / "store", io_meter=meter)
    assert opened.names == [] and meter.snapshot().read_calls == 0


def test_a_plan_sized_budget_refuses_at_manifest_readback_with_custody_kept(tmp_path: Path) -> None:
    # 4S+1 admits the plan and every body read, but not the manifest readback.
    graph, first, second = _two_bindings(tmp_path)
    total = first.total + second.total
    meter = SealingMeter(SealingBudget(max_read_bytes=4 * total + 1), governed=True)
    before = open_descriptor_count()
    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        seal(graph, tmp_path / "store", io_meter=meter)
    snapshot = meter.snapshot()
    assert snapshot.read_bytes == 4 * total and snapshot.refused_limit == "read_bytes"
    assert snapshot.reader("store") == total, "every body was read back; the manifest was not"
    assert open_descriptor_count() == before
    assert not list((tmp_path / "store" / "temporary").iterdir())


def test_governed_seal_equals_default_and_counts_three_walks(tmp_path: Path) -> None:
    graph, first, second = _two_bindings(tmp_path)
    plain = seal(graph, tmp_path / "plain")
    meter = SealingMeter(SealingBudget(max_read_bytes=10**12, max_elapsed_ms=86_400_000), governed=True)
    governed = seal(graph, tmp_path / "store", io_meter=meter)
    assert governed[0] == plain[0] and governed[2] == plain[2]
    snapshot = meter.snapshot()
    assert snapshot.directory_entries == 3 * (first.listed_entries + second.listed_entries)
    assert snapshot.plan is not None and snapshot.plan.inventory_bytes == first.total + second.total
    assert snapshot.plan.inventory_files == len(ENTRY) + len(INPUT) and snapshot.plan.bindings == 2
