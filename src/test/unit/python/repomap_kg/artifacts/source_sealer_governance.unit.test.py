"""Governed and observe-only ``seal_configured_sources`` against independent expectations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import common_lore_index.graph._metered_capture as metered_capture
from common_lore_index.artifacts._manifest_records import ArtifactLimits
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.graph.discovery import discover_repository
from common_lore_index.graph.multi_source_capture import MultiSourceCaptureError, _capture_inventory
from common_lore_index.graph.multi_source import graph_source_binding_id
from repomap_test_support.sealing_governance_fixtures import (
    GRAPH_ID,
    binding_for,
    expectation_for,
    graph_for,
    open_descriptor_count,
    seal,
    write_tree,
)

FILES = {
    "a.txt": b"alpha\n" * 300,
    "pkg/b.py": b"value = 2\n" * 50,
    "pkg/deep/c.txt": os.urandom(70_000),
    "empty.txt": b"",
}


def _fixture(tmp_path: Path):
    root = write_tree(tmp_path / "entry", FILES)
    graph = graph_for(binding_for("entry", root))
    return root, graph, expectation_for(root, FILES)


def _manifest_bytes(result) -> int:
    return len(result[0].canonical_bytes())


def test_observe_only_seal_equals_the_unmetered_seal_with_exact_counters(tmp_path: Path) -> None:
    root, graph, expected = _fixture(tmp_path)
    plain = seal(graph, tmp_path / "plain")
    meter = SealingMeter(None, governed=False)
    metered = seal(graph, tmp_path / "metered", io_meter=meter)
    assert metered[0] == plain[0] and metered[2] == plain[2]
    assert metered[1].content_digest == plain[1].content_digest
    m = _manifest_bytes(plain)
    snapshot = meter.snapshot()
    assert snapshot.read_bytes == expected.read_bytes(m, collision=False)
    assert snapshot.reader("discovery") == 0 and snapshot.reader("capture") == 2 * expected.total
    assert snapshot.reader("copy") == expected.total and snapshot.reader("classification") == 0
    assert snapshot.reader("store") == expected.total + m
    assert snapshot.read_calls == expected.read_calls(m, collision=False)
    assert snapshot.write_bytes == expected.total + m
    assert snapshot.opens == expected.opens(walks=2, collision=False)
    assert snapshot.directory_entries == 2 * expected.listed_entries
    assert snapshot.fsyncs == expected.fsyncs(collision=False)
    assert snapshot.capture_retries == 0 and snapshot.plan is None and not snapshot.complete


def test_metered_capture_inventory_tuple_equals_the_default_tuple(tmp_path: Path) -> None:
    _root, graph, _expected = _fixture(tmp_path)
    default = _capture_inventory(graph, discover_fn=discover_repository)
    metered = _capture_inventory(
        graph, discover_fn=discover_repository, io_meter=SealingMeter(None, governed=False)
    )
    assert metered == default


def test_collision_reseal_counts_each_object_and_manifest_once(tmp_path: Path) -> None:
    _root, graph, expected = _fixture(tmp_path)
    first = seal(graph, tmp_path / "store")
    meter = SealingMeter(None, governed=False)
    again = seal(graph, tmp_path / "store", io_meter=meter)
    assert again[0] == first[0]
    m = _manifest_bytes(first)
    snapshot = meter.snapshot()
    assert snapshot.read_bytes == expected.read_bytes(m, collision=True) == 5 * expected.total + 2 * m
    assert snapshot.read_calls == expected.read_calls(m, collision=True)
    assert snapshot.opens == expected.opens(walks=2, collision=True)
    assert snapshot.fsyncs == expected.fsyncs(collision=True)


def test_governed_seal_walks_metadata_first_and_records_the_plan(tmp_path: Path) -> None:
    _root, graph, expected = _fixture(tmp_path)
    meter = SealingMeter(SealingBudget(max_read_bytes=10**9), governed=True)
    result = seal(graph, tmp_path / "store", io_meter=meter)
    assert result[0] == seal(graph, tmp_path / "plain")[0]
    snapshot = meter.snapshot()
    assert snapshot.plan is not None
    assert (snapshot.plan.bindings, snapshot.plan.inventory_files, snapshot.plan.inventory_bytes) == (
        1, len(FILES), expected.total,
    )
    assert snapshot.directory_entries == 3 * expected.listed_entries
    assert snapshot.opens == expected.opens(walks=3, collision=False)
    assert snapshot.effective_max_directory_entries == 100_000


def _need(graph, tmp_path: Path, name: str) -> int:
    """Exact read/write need of one successful seal: counters plus one EOF probe byte."""
    meter = SealingMeter(None, governed=False)
    seal(graph, tmp_path / f"probe-{name}", io_meter=meter)
    snapshot = meter.snapshot()
    return snapshot.read_bytes + 1 if name == "read_bytes" else snapshot.write_bytes


@pytest.mark.parametrize("name", ["read_bytes", "write_bytes", "opens", "directory_entries"])
def test_exact_need_passes_and_need_minus_one_refuses_for_each_budget(tmp_path: Path, name: str) -> None:
    _root, graph, expected = _fixture(tmp_path)
    if name == "directory_entries":
        need = 3 * expected.listed_entries
    elif name == "opens":
        need = expected.opens(walks=3, collision=False)
    else:
        need = _need(graph, tmp_path, name)
    field = {"read_bytes": "max_read_bytes", "write_bytes": "max_write_bytes",
             "opens": "max_opens", "directory_entries": "max_directory_entries"}[name]
    seal(graph, tmp_path / "exact", io_meter=SealingMeter(SealingBudget(**{field: need}), governed=True))
    before = open_descriptor_count()
    short = SealingMeter(SealingBudget(**{field: need - 1}), governed=True)
    with pytest.raises(SealingBudgetExceeded) as raised:
        seal(graph, tmp_path / "short", io_meter=short)
    assert raised.value.limit == name and short.refused_limit == name
    assert open_descriptor_count() == before, "every refusal point closes its descriptors"
    assert getattr(short.snapshot(), name) <= need - 1


def test_elapsed_budget_refuses_cooperatively_with_an_injected_clock(tmp_path: Path) -> None:
    _root, graph, _expected = _fixture(tmp_path)
    ticks = iter(range(0, 10**12, 1_000_000))
    meter = SealingMeter(SealingBudget(max_elapsed_ms=5), governed=True, _monotonic_ns=lambda: next(ticks))
    with pytest.raises(SealingBudgetExceeded, match="elapsed_ms"):
        seal(graph, tmp_path / "store", io_meter=meter)
    assert meter.snapshot().opens + meter.snapshot().directory_entries <= 5


@pytest.mark.parametrize(("budget", "limit"), [
    (lambda total: SealingBudget(max_read_bytes=4 * total), "planned_read_bytes"),
    (lambda total: SealingBudget(max_write_bytes=total - 1), "planned_write_bytes"),
])
def test_planned_overruns_refuse_before_any_body_read(tmp_path: Path, budget, limit: str) -> None:
    _root, graph, expected = _fixture(tmp_path)
    meter = SealingMeter(budget(expected.total), governed=True)
    with pytest.raises(SealingBudgetExceeded, match=limit):
        seal(graph, tmp_path / "store", io_meter=meter)
    snapshot = meter.snapshot()
    assert snapshot.read_bytes == 0 and snapshot.read_calls == 0 and snapshot.write_bytes == 0
    assert snapshot.directory_entries == expected.listed_entries, "only the metadata preflight ran"


@pytest.mark.parametrize(("limits", "message"), [
    (ArtifactLimits(max_artifacts=3), "artifact count bounds exceeded"),
    (ArtifactLimits(max_total_bytes=100), "artifact byte bounds exceeded"),
    (ArtifactLimits(max_path_bytes=8), "artifact path bounds exceeded"),
])
def test_governed_preflight_applies_the_inventory_predicate_before_bodies(tmp_path: Path, limits, message) -> None:
    _root, graph, _expected = _fixture(tmp_path)
    meter = SealingMeter(SealingBudget(max_read_bytes=10**9), governed=True)
    with pytest.raises(ValueError, match=message):
        seal(graph, tmp_path / "store", limits=limits, io_meter=meter)
    assert meter.snapshot().read_bytes == 0
    with pytest.raises(ValueError, match=message):
        seal(graph, tmp_path / "default", limits=limits)


def test_availability_of_every_binding_precedes_any_governed_body_read(tmp_path: Path) -> None:
    entry = write_tree(tmp_path / "entry", FILES)
    first = graph_source_binding_id(GRAPH_ID, "entry")
    # Bindings are processed in binding-id order; the missing one must sort last.
    alias = next(f"input{index}" for index in range(100)
                 if graph_source_binding_id(GRAPH_ID, f"input{index}") > first)
    graph = graph_for(binding_for("entry", entry), binding_for(alias, tmp_path / "missing"))
    governed = SealingMeter(SealingBudget(max_read_bytes=10**9), governed=True)
    with pytest.raises(MultiSourceCaptureError) as raised:
        seal(graph, tmp_path / "governed", io_meter=governed)
    assert raised.value.category == "source_unavailable" and governed.snapshot().read_bytes == 0
    observe = SealingMeter(None, governed=False)
    with pytest.raises(MultiSourceCaptureError):
        seal(graph, tmp_path / "observe", io_meter=observe)
    assert observe.snapshot().read_bytes > 0, "observe-only keeps incumbent per-binding order"


def test_refusals_inside_scans_are_never_relabelled_as_capture_categories(tmp_path: Path) -> None:
    _root, graph, expected = _fixture(tmp_path)
    meter = SealingMeter(SealingBudget(max_read_bytes=4 * expected.total + 1), governed=True)
    with pytest.raises(SealingBudgetExceeded) as raised:
        seal(graph, tmp_path / "store", io_meter=meter)
    assert not isinstance(raised.value, MultiSourceCaptureError)
    assert raised.value.limit == "read_bytes"


def test_stable_capture_retries_are_counted_and_their_bytes_stay_charged(tmp_path: Path, monkeypatch) -> None:
    _root, graph, expected = _fixture(tmp_path)
    real_signature = metered_capture._file_signature
    calls = {"count": 0}

    def unstable_signature(details: os.stat_result) -> tuple[int, ...]:
        calls["count"] += 1
        signature = real_signature(details)
        # Call 4 is the after-read signature of the first capture attempt.
        return (*signature[:-1], signature[-1] + 1) if calls["count"] == 4 else signature

    monkeypatch.setattr(metered_capture, "_file_signature", unstable_signature)
    meter = SealingMeter(None, governed=False)
    seal(graph, tmp_path / "store", io_meter=meter)
    snapshot = meter.snapshot()
    assert snapshot.capture_retries == 1
    assert snapshot.reader("capture") == 2 * expected.total + expected.sizes["a.txt"]


def test_in_root_symlink_aliases_are_hashed_twice_but_sealed_once(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "entry", {"target.txt": b"target\n"})
    (root / "zlink.txt").symlink_to(root / "target.txt")
    graph = graph_for(binding_for("entry", root))
    meter = SealingMeter(None, governed=False)
    plain = seal(graph, tmp_path / "plain")
    metered = seal(graph, tmp_path / "metered", io_meter=meter)
    assert metered[0] == plain[0]
    assert meter.snapshot().reader("discovery") == 0 and meter.snapshot().reader("capture") == 2 * len(b"target\n")
