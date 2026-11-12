"""Containerized real store/sealer custody; injected faults stay in-process."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from repomap_test_support.metered_store_custody_fixtures import DescriptorWitness, store_state
from repomap_test_support.sealing_governance_fixtures import binding_for, graph_for, seal, write_tree


@pytest.mark.parametrize("operation", ("fchmod", "fdopen"))
def test_sealer_setup_fault_closes_owned_fd_and_preserves_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    source = write_tree(tmp_path / "source", {"main.py": b"VALUE = 1\n"})
    graph = graph_for(binding_for("entry", source))
    store = FileSystemArtifactStore(tmp_path / "store")
    _, previous, _ = seal(graph, store.root)
    previous_bytes = store.read(previous)
    before = store_state(store.root)
    (source / "main.py").write_bytes(b"VALUE = 2\n")
    witness = DescriptorWitness(monkeypatch)
    primary = OSError("setup witness")

    def fail(*args: object, **kwargs: object) -> None:
        raise primary

    monkeypatch.setattr(os, operation, fail)
    try:
        with pytest.raises(ArtifactIntegrityError, match="publication failed") as raised:
            seal(graph, store.root, io_meter=SealingMeter(None, governed=False))
        assert raised.value.__cause__ is primary
        assert witness.acquired and witness.live() == []
        assert store_state(store.root) == before
        assert tuple((store.root / "temporary").iterdir()) == ()
    finally:
        witness.release_witnesses()
    monkeypatch.undo()
    assert store.read(previous) == previous_bytes


def test_sealer_budget_refusal_survives_cleanup_fault_without_changing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_tree(tmp_path / "source", {"main.py": b"VALUE = 1\n"})
    graph = graph_for(binding_for("entry", source))
    store = FileSystemArtifactStore(tmp_path / "store")
    _, previous, _ = seal(graph, store.root)
    previous_bytes = store.read(previous)
    before = store_state(store.root)
    payload = b"VALUE = 2\n"
    (source / "main.py").write_bytes(payload)
    # Admit preflight and the changed body; refuse the following manifest write.
    meter = SealingMeter(SealingBudget(max_write_bytes=len(payload)), governed=True)
    witness = DescriptorWitness(monkeypatch)
    original_unlink = Path.unlink
    refused: list[Path] = []

    def unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.parent == store.root / "temporary":
            refused.append(path)
            raise OSError("cleanup witness")
        original_unlink(path)

    monkeypatch.setattr(Path, "unlink", unlink)
    try:
        with pytest.raises(SealingBudgetExceeded, match="write_bytes"):
            seal(graph, store.root, io_meter=meter)
        assert meter.snapshot().refused_limit == "write_bytes"
        assert meter.snapshot().write_bytes == len(payload)
        assert dict(store_state(store.root)) == dict(before) | {hashlib.sha256(payload).hexdigest(): payload}
        assert witness.acquired and witness.live() == []
        assert len(refused) == 1 and refused[0].is_file()
    finally:
        witness.release_witnesses()
        monkeypatch.undo()
        for path in refused:
            original_unlink(path)
    assert store.read(previous) == previous_bytes


@pytest.mark.parametrize("collision", (False, True))
def test_metered_public_store_retains_exact_bytes_reference_and_operation_counts(
    tmp_path: Path, collision: bool,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    payload = b"bounded public-safe payload"
    previous = store.put(payload) if collision else None
    meter = SealingMeter(
        SealingBudget(max_read_bytes=(2 if collision else 1) * len(payload) + 1,
                      max_write_bytes=len(payload), max_opens=3),
        governed=True,
    )
    reference = store.put(payload, io_meter=meter)
    assert store.read(reference) == payload
    if previous is not None:
        assert reference == previous
    snapshot = meter.snapshot()
    assert snapshot.opens == 3 and snapshot.fsyncs == (1 if collision else 2)
    assert snapshot.read_calls == (4 if collision else 2)
    assert snapshot.read_bytes == (2 if collision else 1) * len(payload)
    assert snapshot.write_bytes == len(payload)
    assert tuple((store.root / "temporary").iterdir()) == ()
