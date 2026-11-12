"""Metered acquisition, all-owned cleanup and actual-primary preservation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts._store_common import ArtifactIntegrityError
import common_lore_index.artifacts._store_metered as metered
from common_lore_index.artifacts._store_filesystem import _private_details
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.artifacts.store import FileSystemArtifactStore
from repomap_test_support.metered_store_custody_fixtures import CloseFaultStream, DescriptorWitness, store_state


class _ProducerStop(BaseException):
    """Pure control-flow witness; no operating-system signal is sent."""


@pytest.mark.parametrize("operation", ("fchmod", "fdopen"))
@pytest.mark.parametrize("permission", (False, True))
def test_setup_failure_closes_the_actual_temporary_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, permission: bool,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    incumbent = store.put(b"accepted")
    before = store_state(store.root)
    meter = SealingMeter(None, governed=False)
    witness = DescriptorWitness(monkeypatch)
    primary = PermissionError("temporary setup witness") if permission else OSError("temporary setup witness")

    def fail(*args: object, **kwargs: object) -> None:
        raise primary

    monkeypatch.setattr(os, operation, fail)
    try:
        with pytest.raises(ArtifactIntegrityError, match="publication failed") as raised:
            store.put(b"new bytes", io_meter=meter)
        assert raised.value.__cause__ is primary
        assert raised.value.code == ("permission_denied" if permission else "write_failed")
        assert len(witness.acquired) == 1 and witness.live() == []
        assert meter.snapshot().opens == 1 and meter.snapshot().write_bytes == 0
        assert tuple((store.root / "temporary").iterdir()) == ()
        assert store_state(store.root) == before
    finally:
        witness.release_witnesses()
    monkeypatch.undo()
    assert store.read(incumbent) == b"accepted"


def test_normal_unlink_failure_is_visible_even_inside_a_callers_except(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    accepted = store.put(b"accepted")
    before = store_state(store.root)
    original_unlink = Path.unlink
    refused: list[Path] = []

    def unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.parent == store.root / "temporary":
            refused.append(path)
            raise OSError("cleanup witness")
        original_unlink(path)

    monkeypatch.setattr(Path, "unlink", unlink)
    try:
        try:
            raise RuntimeError("unrelated caller exception")
        except RuntimeError:
            with pytest.raises(ArtifactIntegrityError, match="temporary cleanup failed"):
                store.put(b"accepted", io_meter=SealingMeter(None, governed=False))
        assert store_state(store.root) == before
        assert len(refused) == 1 and refused[0].is_file()
    finally:
        monkeypatch.undo()
        for path in refused:
            original_unlink(path)
    assert store.read(accepted) == b"accepted"


@pytest.mark.parametrize("failure", ("producer", "budget", "control"))
def test_unlink_failure_preserves_the_actual_producer_or_budget_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    store.put(b"incumbent")
    before = store_state(store.root)
    sentinel = store.root / "temporary" / ".artifact-unrelated.tmp"
    sentinel.write_bytes(b"unrelated")
    primary = _ProducerStop("control witness") if failure == "control" else RuntimeError("producer witness")
    real_unlink = Path.unlink
    refused: list[Path] = []

    def chunks():
        yield b"prefix"
        raise primary

    def unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.parent == store.root / "temporary":
            refused.append(path)
            raise OSError("cleanup witness")
        real_unlink(path)

    meter = SealingMeter(SealingBudget(max_write_bytes=0) if failure == "budget" else None, governed=True)
    monkeypatch.setattr(Path, "unlink", unlink)
    try:
        expected = SealingBudgetExceeded if failure == "budget" else type(primary)
        with pytest.raises(expected) as raised:
            store.put(chunks(), io_meter=meter)
        if failure != "budget":
            assert raised.value is primary
        else:
            assert str(raised.value) == "sealing budget exceeded: write_bytes"
        assert len(refused) == 1 and refused[0].is_file()
        assert store_state(store.root) == before and sentinel.read_bytes() == b"unrelated"
    finally:
        monkeypatch.undo()
        for path in refused:
            real_unlink(path)


@pytest.mark.parametrize("has_primary", (False, True))
@pytest.mark.parametrize("close_after_release", (False, True))
@pytest.mark.parametrize("failed_close", ("temporary", "target", "both"))
def test_collision_attempts_both_closes_and_preserves_first_or_primary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_primary: bool, close_after_release: bool,
    failed_close: str,
) -> None:
    target, temporary = tmp_path / "target", tmp_path / "temporary"
    target.write_bytes(b"payload")
    temporary.write_bytes(b"payload")
    target.chmod(0o600)
    temporary.chmod(0o600)
    witness = DescriptorWitness(monkeypatch)
    original_open = metered.metered_open
    first, second = OSError("temporary close witness"), OSError("target close witness")
    primary = ArtifactIntegrityError("read witness")

    def opened(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        if len(witness.acquired) == 2:
            if failed_close in ("temporary", "both"):
                witness.close_faults[witness.acquired[1][0]] = (first, close_after_release)
            if failed_close in ("target", "both"):
                witness.close_faults[witness.acquired[0][0]] = (second, close_after_release)
        return descriptor

    def fail_read(*args: object, **kwargs: object) -> bytes:
        raise primary

    monkeypatch.setattr(metered, "metered_open", opened)
    if has_primary:
        monkeypatch.setattr(metered, "metered_read", fail_read)
    try:
        with pytest.raises(ArtifactIntegrityError if has_primary else OSError) as raised:
            metered.metered_compare_and_verify_collision(
                target, temporary, 7, "sha256:" + hashlib.sha256(b"payload").hexdigest(), 7,
                owner_uid=os.getuid(), private_details_fn=_private_details,
                meter=SealingMeter(None, governed=False),
            )
        assert raised.value is (primary if has_primary else second if failed_close == "target" else first)
        assert witness.close_attempts == [witness.acquired[1][0], witness.acquired[0][0]]
        remaining = [fd for fd, _, _ in witness.acquired if (
            failed_close == "both" or fd == witness.acquired[1 if failed_close == "temporary" else 0][0]
        )]
        assert witness.live() == ([] if close_after_release else remaining)
        assert target.read_bytes() == temporary.read_bytes() == b"payload"
    finally:
        witness.release_witnesses()


@pytest.mark.parametrize("operation", ("directory", "verify"))
def test_close_does_not_replace_an_active_metered_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    reference = store.put(b"payload")
    witness = DescriptorWitness(monkeypatch)
    original_open = metered.metered_open
    primary = SealingBudgetExceeded("elapsed_ms")

    def opened(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        witness.close_faults[descriptor] = (OSError("secondary close witness"), True)
        return descriptor

    def fail(*args: object, **kwargs: object) -> None:
        raise primary

    monkeypatch.setattr(metered, "metered_open", opened)
    monkeypatch.setattr(metered, "metered_fsync" if operation == "directory" else "metered_read", fail)
    try:
        with pytest.raises(SealingBudgetExceeded) as raised:
            if operation == "directory":
                metered.metered_fsync_directory(store.root, SealingMeter(None, governed=False))
            else:
                metered.metered_verify_path(
                    store.object_path(reference), digest=reference.content_digest,
                    length=7, bound=7, expected_version=None, owner_uid=os.getuid(),
                    private_details_fn=_private_details, meter=SealingMeter(None, governed=False),
                )
        assert raised.value is primary
        assert len(witness.acquired) == 1 and witness.live() == []
    finally:
        witness.release_witnesses()


@pytest.mark.parametrize("failure", ("none", "producer", "control", "budget"))
@pytest.mark.parametrize("release", (False, True))
def test_temporary_stream_close_keeps_primary_and_never_reports_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, release: bool,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    store.put(b"accepted")
    before = store_state(store.root)
    original_fdopen = os.fdopen
    streams: list[CloseFaultStream] = []
    primary = _ProducerStop("control witness") if failure == "control" else RuntimeError("producer witness")
    secondary = OSError("close witness")

    def fdopen(*args, **kwargs):
        stream = CloseFaultStream(original_fdopen(*args, **kwargs), secondary, release=release)
        streams.append(stream)
        return stream

    def chunks():
        yield b"payload"
        if failure in ("producer", "control"):
            raise primary

    monkeypatch.setattr(os, "fdopen", fdopen)
    expected = type(primary) if failure in ("producer", "control") else (
        SealingBudgetExceeded if failure == "budget" else ArtifactIntegrityError
    )
    meter = SealingMeter(SealingBudget(max_write_bytes=0) if failure == "budget" else None, governed=True)
    try:
        with pytest.raises(expected) as raised:
            store.put(chunks(), io_meter=meter)
        if failure in ("producer", "control"):
            assert raised.value is primary
        elif failure == "budget":
            assert str(raised.value) == "sealing budget exceeded: write_bytes"
        else:
            assert raised.value.__cause__ is secondary
        assert len(streams) == 1 and streams[0].stream.closed is release and streams[0].close_calls == 1
        assert store_state(store.root) == before
        assert tuple((store.root / "temporary").iterdir()) == ()
    finally:
        for stream in streams:
            stream.stream.close()
