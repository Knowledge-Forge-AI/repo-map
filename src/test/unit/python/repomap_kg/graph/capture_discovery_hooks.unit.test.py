"""Probe lifetime, unchanged classification and snapshot backstops."""
from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from common_lore_index.graph import _discovery_classify, discovery
from common_lore_index.graph._capture_discovery import (
    CaptureDiscoveryHooks,
    ELIDED_DISCOVERY_CONTENT_HASH,
)
from common_lore_index.graph.multi_source import MultiSourceIdentityError, SnapshotManifestEntry
from common_lore_index.graph.multi_source_capture import _capture_inventory
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config

if TYPE_CHECKING:
    from common_lore_index.artifacts._sealing_meter import SealingMeter


def test_probe_never_opens_a_python_binary_body_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "large.py"
    path.write_bytes(b"x" * 4096)

    def reject_reader(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discarded body read")

    monkeypatch.setattr(Path, "open", reject_reader)
    assert CaptureDiscoveryHooks().content_hash(path) == ELIDED_DISCOVERY_CONTENT_HASH


def test_probe_closes_its_descriptor_and_uses_available_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "file.py"
    path.write_bytes(b"hello")
    opened: list[tuple[int, int]] = []
    original_open = os.open

    def tracked_open(path: Path, flags: int) -> int:
        descriptor = original_open(path, flags)
        opened.append((descriptor, flags))
        return descriptor

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", tracked_open)
        CaptureDiscoveryHooks().content_hash(path)
    assert len(opened) == 1
    descriptor, flags = opened[0]
    for name in ("O_NONBLOCK", "O_CLOEXEC"):
        expected = getattr(os, name, 0)
        assert flags & expected == expected
    with pytest.raises(OSError) as error:
        os.fstat(descriptor)
    assert error.value.errno == errno.EBADF


def test_probe_closes_after_a_metadata_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "file.py"
    path.write_bytes(b"hello")
    opened: list[int] = []
    original_open = os.open

    def tracked_open(path: Path, flags: int) -> int:
        descriptor = original_open(path, flags)
        opened.append(descriptor)
        return descriptor

    def fail_stat(_descriptor: int) -> os.stat_result:
        raise OSError(errno.EIO, "synthetic metadata failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", tracked_open)
        patch.setattr(os, "fstat", fail_stat)
        with pytest.raises(OSError) as error:
            CaptureDiscoveryHooks().content_hash(path)
        assert error.value.errno == errno.EIO
    assert len(opened) == 1
    with pytest.raises(OSError) as error:
        os.fstat(opened[0])
    assert error.value.errno == errno.EBADF


def test_probe_preserves_missing_and_directory_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CaptureDiscoveryHooks().content_hash(tmp_path / "missing.py")
    with pytest.raises(IsADirectoryError):
        CaptureDiscoveryHooks().content_hash(tmp_path)


def test_probe_follows_a_regular_alias_without_reading_content(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("X = 1\n", encoding="utf-8")
    alias = tmp_path / "alias.py"
    alias.symlink_to(target.name)
    assert CaptureDiscoveryHooks().content_hash(alias) == ELIDED_DISCOVERY_CONTENT_HASH
    assert target.read_text() == "X = 1\n"


def test_probe_does_not_block_on_an_owned_fifo(tmp_path: Path) -> None:
    fifo = tmp_path / "sample.py"
    os.mkfifo(fifo, 0o600)
    try:
        assert CaptureDiscoveryHooks().content_hash(fifo) == ELIDED_DISCOVERY_CONTENT_HASH
    finally:
        fifo.unlink()


def test_classifier_delegates_to_live_incumbent_readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "fixture"
    observed: list[tuple[str, Path]] = []

    def first_line(value: Path) -> str:
        observed.append(("first_line", value))
        return "#!/bin/zsh"

    def go_marker(value: Path) -> bool:
        observed.append(("go", value))
        return True

    def completion(value: Path) -> bool:
        observed.append(("completion", value))
        return True

    hooks = CaptureDiscoveryHooks()
    monkeypatch.setattr(_discovery_classify, "first_line", first_line)
    monkeypatch.setattr(_discovery_classify, "is_go_generated_file", go_marker)
    monkeypatch.setattr(_discovery_classify, "is_zsh_completion_candidate", completion)
    assert hooks.readers() is hooks
    assert hooks.first_line(path) == "#!/bin/zsh"
    assert hooks.is_go_generated_file(path) is True
    assert hooks.completion(path) is True
    assert observed == [("first_line", path), ("go", path), ("completion", path)]


@pytest.mark.parametrize("name,text", [
    ("module.py", "def f():\n    pass\n"),
    ("generated.go", "// Code generated by fixture. DO NOT EDIT.\npackage fixture\n"),
    ("script.sh", "#!/bin/bash\necho hello\n"),
    ("script", "#!/bin/zsh\necho hello\n"),
    (".profile", "export SAMPLE=value\n"),
    ("completion", "#compdef sample\n_arguments '--help'\n"),
])
def test_provisional_classifier_changes_only_unused_digest(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")
    ordinary = discovery.discover_repository(tmp_path)
    provisional = discovery.discover_repository(tmp_path, io_hooks=CaptureDiscoveryHooks())
    assert len(ordinary) == len(provisional) == 1
    before, after = ordinary[0], provisional[0]
    assert after.content_hash == ELIDED_DISCOVERY_CONTENT_HASH
    assert (after.path, after.language, after.role, after.executable, after.generated, after.confidence) == (
        before.path, before.language, before.role, before.executable, before.generated, before.confidence,
    )


def test_provisional_digest_is_refused_by_snapshot_authority() -> None:
    with pytest.raises(MultiSourceIdentityError, match="digest is invalid"):
        SnapshotManifestEntry("fixture.py", ELIDED_DISCOVERY_CONTENT_HASH, 1)


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", (), object()],
                         ids=["none", "zero", "one", "text", "tuple", "object"])
def test_elision_flag_is_closed_before_capture(tmp_path: Path, invalid: object) -> None:
    graph = create_single_source_graph_config(tmp_path)
    with pytest.raises(ValueError, match="must be boolean"):
        capture_multi_source_candidate(graph, elide_discovery_hash=cast(bool, invalid))
    assert not tuple(tmp_path.iterdir())


def test_meter_and_elision_are_refused_before_inventory(tmp_path: Path) -> None:
    graph = create_single_source_graph_config(tmp_path)
    with pytest.raises(ValueError, match="cannot use a sealing meter"):
        _capture_inventory(graph, elide_discovery_hash=True, io_meter=cast("SealingMeter", object()))
    assert not tuple(tmp_path.iterdir())
