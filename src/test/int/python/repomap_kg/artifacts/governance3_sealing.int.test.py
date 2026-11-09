"""Real-filesystem governance3 sealing counters, budgets and race refusals.

The expected byte and call totals are derived from the fixture sizes and
documented reader chunks.  They are not copied from the meter or planner.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import (
    SealingBudget,
    SealingBudgetExceeded,
)
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.graph._capture_contracts import MultiSourceCaptureError
from repomap_test_support.sealing_governance_fixtures import (
    binding_for,
    expectation_for,
    graph_for,
    open_descriptor_count,
    seal,
    write_tree,
)


BOUNDARY_SIZES = (0, 1, 65_535, 65_536, 65_537, 1_048_576, 1_048_577)


def _boundary_files() -> dict[str, bytes]:
    files = {
        f"size-{size}.bin": bytes([index + 1]) * size
        for index, size in enumerate(BOUNDARY_SIZES)
    }
    files["duplicate.bin"] = files["size-1.bin"]
    return files


def _boundary_tree(tmp_path: Path):
    files = _boundary_files()
    source = write_tree(tmp_path / "source", files)
    (source / "alias-size-1.bin").symlink_to(source / "size-1.bin")
    return source, files, graph_for(binding_for("entry", source))


def _store_state(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        sorted(
            (path.relative_to(root).as_posix(), path.read_bytes())
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def test_replay_exact_counters_cover_boundaries_duplicate_and_alias(
    tmp_path: Path,
) -> None:
    source, files, graph = _boundary_tree(tmp_path)
    expected = expectation_for(source, files)
    first = seal(graph, tmp_path / "store")
    manifest_bytes = len(first[0].canonical_bytes())
    collision_reads = expected.read_bytes(manifest_bytes, collision=True)
    required = collision_reads + 1

    assert first[0].total_files == len(files)
    assert "alias-size-1.bin" not in {
        item.source_relative_path for item in first[0].entries
    }

    meter = SealingMeter(
        SealingBudget(max_read_bytes=required), governed=True
    )
    before = open_descriptor_count()
    replay = seal(graph, tmp_path / "store", io_meter=meter)
    snapshot = meter.snapshot()

    assert replay[0] == first[0]
    assert len(replay[0].canonical_bytes()) == manifest_bytes
    assert replay[0].canonical_bytes() == first[0].canonical_bytes()
    assert snapshot.read_bytes == collision_reads
    assert snapshot.read_calls == expected.read_calls(manifest_bytes, collision=True, scans=2)
    assert snapshot.reader("capture") == 2 * expected.total
    assert snapshot.reader("copy") == expected.total
    assert snapshot.reader("store") == 2 * (expected.total + manifest_bytes)
    assert snapshot.reader("discovery") == 0
    assert snapshot.reader("classification") == 0
    assert snapshot.write_bytes == expected.total + manifest_bytes
    assert snapshot.opens == expected.opens(walks=3, collision=True)
    assert snapshot.fsyncs == expected.fsyncs(collision=True)
    assert snapshot.directory_entries == 3 * expected.listed_entries
    assert snapshot.plan is not None
    assert snapshot.plan.inventory_bytes == expected.total
    assert snapshot.plan.inventory_files == len(files)
    assert open_descriptor_count() == before
    assert not list((tmp_path / "store" / "temporary").iterdir())


def test_replay_one_byte_below_exact_need_refuses_and_keeps_prior_manifest(
    tmp_path: Path,
) -> None:
    source, files, graph = _boundary_tree(tmp_path)
    expected = expectation_for(source, files)
    first = seal(graph, tmp_path / "store")
    manifest_bytes = len(first[0].canonical_bytes())
    required = expected.read_bytes(manifest_bytes, collision=True) + 1
    meter = SealingMeter(
        SealingBudget(max_read_bytes=required - 1), governed=True
    )
    before = open_descriptor_count()

    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        seal(graph, tmp_path / "store", io_meter=meter)

    snapshot = meter.snapshot()
    store = FileSystemArtifactStore(tmp_path / "store")
    assert snapshot.refused_limit == "read_bytes"
    assert snapshot.read_bytes == required - 1
    assert store.read(first[1]) == first[0].canonical_bytes()
    assert not list((tmp_path / "store" / "temporary").iterdir())
    assert open_descriptor_count() == before


@pytest.mark.parametrize(
    ("governed", "mutation", "category"),
    (
        (False, "deleted", "source_changed"),
        (False, "directory", "source_invalid"),
        (False, "fifo", "source_invalid"),
        (True, "deleted", "source_changed"),
        (True, "directory", "source_invalid"),
        (True, "fifo", "source_invalid"),
    ),
)
def test_post_lstat_swaps_refuse_without_body_read_or_store_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    governed: bool,
    mutation: str,
    category: str,
) -> None:
    source = write_tree(tmp_path / "source", {"main.py": b"VALUE = 1\n"})
    target = source / "main.py"
    graph = graph_for(binding_for("entry", source))
    accepted_root = tmp_path / "accepted"
    seal(graph, accepted_root)
    accepted_state = _store_state(accepted_root)
    before_descriptors = open_descriptor_count()
    real_open = os.open
    real_read = os.read
    real_write = os.write
    mutated = False
    read_calls = 0
    write_calls = 0

    def mutate_at_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal mutated
        if not mutated and os.fspath(path) == os.fspath(target):
            target.unlink()
            if mutation == "directory":
                target.mkdir()
            elif mutation == "fifo":
                os.mkfifo(target)
            mutated = True
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def count_read(descriptor: int, length: int) -> bytes:
        nonlocal read_calls
        read_calls += 1
        return real_read(descriptor, length)

    def count_write(descriptor: int, data: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        return real_write(descriptor, data)

    monkeypatch.setattr(os, "open", mutate_at_open)
    monkeypatch.setattr(os, "read", count_read)
    monkeypatch.setattr(os, "write", count_write)
    meter = SealingMeter(SealingBudget(max_read_bytes=10**9), governed=True) if governed else None
    with pytest.raises(MultiSourceCaptureError) as raised:
        seal(graph, accepted_root, io_meter=meter)

    assert mutated
    assert raised.value.category == category
    assert str(raised.value) == {
        "source_changed": "source binding changed during capture",
        "source_invalid": "source inventory is invalid",
    }[category]
    assert os.fspath(target) not in str(raised.value)
    assert read_calls == write_calls == 0
    assert _store_state(accepted_root) == accepted_state
    assert not list((accepted_root / "temporary").iterdir())
    assert open_descriptor_count() == before_descriptors
    if meter is not None:
        snapshot = meter.snapshot()
        assert snapshot.read_bytes == 0 and snapshot.write_bytes == 0
        assert snapshot.reader("capture") == snapshot.reader("store") == 0
