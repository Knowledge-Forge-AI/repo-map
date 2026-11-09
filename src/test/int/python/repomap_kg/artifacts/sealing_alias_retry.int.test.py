"""Real aliases/retries: native I/O witnesses independent of the subject meter."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.ops.sealing_plan import build_sealing_plan
from repomap_test_support.sealing_governance_fixtures import (
    GRAPH_ID, binding_for, graph_for, open_descriptor_count, seal, write_tree,
)

BODY = b"x=1\n" * (1024 * 1024 // 4)
Identity = tuple[int, int]


def _identity(path: Path) -> Identity:
    details = path.stat()
    return details.st_dev, details.st_ino


@dataclass
class NativeReads:
    source_bytes: int = 0
    all_bytes: int = 0
    read_calls: int = 0
    source_eofs: int = 0
    regular_opens: set[Identity] = field(default_factory=set)


@contextmanager
def _native_reads(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    on_source_eof: Callable[[int], None] | None = None,
) -> Iterator[NativeReads]:
    """Record actual completed native reads and opened regular-file identities."""

    witness = NativeReads()
    wanted = _identity(source)
    real_read = os.read
    real_open = os.open

    def observed_read(descriptor: int, length: int) -> bytes:
        details = os.fstat(descriptor)
        identity = (details.st_dev, details.st_ino)
        data = real_read(descriptor, length)
        witness.read_calls += 1
        witness.all_bytes += len(data)
        if identity == wanted:
            witness.source_bytes += len(data)
            if not data:
                witness.source_eofs += 1
                if on_source_eof is not None:
                    on_source_eof(witness.source_eofs)
        return data

    def observed_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        details = os.fstat(descriptor)
        if stat.S_ISREG(details.st_mode):
            witness.regular_opens.add((details.st_dev, details.st_ino))
        return descriptor

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", observed_read)
        patch.setattr(os, "open", observed_open)
        yield witness


@pytest.mark.parametrize("alias_first", (True, False))
def test_alias_inventory_deduplicates_but_charges_every_encounter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias_first: bool,
) -> None:
    root = write_tree(tmp_path / "source", {"middle.py": BODY, "excluded.py": b"excluded\n"})
    source = root / "middle.py"
    alias = root / ("aa-alias.py" if alias_first else "zz-alias.py")
    alias.symlink_to("middle.py")
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"outside-sentinel\n")
    (root / "escape.py").symlink_to(outside)
    graph = graph_for(binding_for("entry", root, exclude_paths=("excluded.py",)))
    forbidden = {_identity(outside), _identity(root / "excluded.py")}
    descriptors = open_descriptor_count()

    with _native_reads(monkeypatch, source) as reads:
        plan = build_sealing_plan(SimpleNamespace(graphs=(graph,)), GRAPH_ID)
    payload = plan.to_payload()
    assert reads.read_calls == 0 and reads.regular_opens == set()
    assert payload["inventory_files"] == 1 and payload["inventory_bytes"] == len(BODY)
    assert payload["inventory_symlinked_files"] == 1, "all eligible aliases, regardless of visit order"
    assert payload["planned_min_read_bytes"] == 4 * len(BODY) + 1
    assert payload["planned_min_write_bytes"] == len(BODY)
    assert payload["directory_entries"] == 4 and payload["projected_directory_entries"] == 12
    assert payload["effective_max_directory_entries"] == 100_000
    assert payload["factors"] == {
        "full_body_reads_per_file": 4,
        "collision_extra_reads_per_file": 1,
        "stable_capture_max_attempts": 3,
    }
    assert payload["projection_basis"] == "three_walks_of_unchanged_metadata_tree_estimate"

    plain = seal(graph, tmp_path / "plain")
    manifest_bytes = len(plain[0].canonical_bytes())
    # An overinclusive 2S plan would falsely refuse this otherwise sufficient cap.
    budget = 4 * len(BODY) + manifest_bytes + 1
    assert 4 * len(BODY) + 1 <= budget
    meter = SealingMeter(SealingBudget(max_read_bytes=budget), governed=True)
    with _native_reads(monkeypatch, source) as reads:
        actual = seal(graph, tmp_path / "governed", io_meter=meter)
    snapshot = meter.snapshot()
    assert (actual[0], actual[2]) == (plain[0], plain[2])
    assert reads.source_bytes == 3 * len(BODY)
    assert reads.all_bytes == 4 * len(BODY) + manifest_bytes
    assert snapshot.read_bytes == reads.all_bytes and snapshot.read_calls == reads.read_calls
    assert not reads.regular_opens & forbidden
    assert open_descriptor_count() == descriptors


@pytest.mark.parametrize("limited", (False, True))
def test_real_signature_change_retries_without_refunding_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limited: bool,
) -> None:
    root = write_tree(tmp_path / "source", {"one.py": BODY})
    source = root / "one.py"
    graph = graph_for(binding_for("entry", root))
    plain = seal(graph, tmp_path / "plain")
    manifest_bytes = len(plain[0].canonical_bytes())
    limit = 4 * len(BODY) + manifest_bytes + 1 if limited else 10**12
    meter = SealingMeter(SealingBudget(max_read_bytes=limit), governed=True)
    changed = []

    def change_signature(eof_number: int) -> None:
        # R5 captures first. Change the real file only after R5's first complete
        # read and before its closing fstat. No sleeps or synthetic stat result.
        if eof_number == 1:
            before = source.stat()
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            changed.append(source.stat().st_mtime_ns != before.st_mtime_ns)

    descriptors = open_descriptor_count()
    store = tmp_path / "governed"
    with _native_reads(monkeypatch, source, change_signature) as reads:
        if limited:
            with pytest.raises(SealingBudgetExceeded) as caught:
                seal(graph, store, io_meter=meter)
            assert caught.value.limit == "read_bytes"
        else:
            actual = seal(graph, store, io_meter=meter)
            assert (actual[0], actual[2]) == (plain[0], plain[2])
    snapshot = meter.snapshot()
    assert changed == [True] and snapshot.capture_retries == 1
    assert snapshot.read_bytes == reads.all_bytes and snapshot.read_calls == reads.read_calls
    assert snapshot.read_bytes <= limit
    if limited:
        assert reads.source_bytes == 3 * len(BODY)
        # The second scan refuses before manifest construction/readback.
        assert reads.all_bytes == 4 * len(BODY)
        assert snapshot.refused_limit == "read_bytes"
        assert not list((store / "temporary").iterdir())
    else:
        assert reads.source_bytes == 4 * len(BODY)
        assert reads.all_bytes == 5 * len(BODY) + manifest_bytes
    assert source.read_bytes() == BODY and open_descriptor_count() == descriptors
