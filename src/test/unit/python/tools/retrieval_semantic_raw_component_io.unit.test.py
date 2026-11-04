"""Complete model directories are explicit, bounded regular-file inputs."""

from pathlib import Path
import os
import socket

import pytest

from retrieval_semantic_pair_artifacts import PairReportRefusal
import retrieval_semantic_raw_component_io as io_module
from retrieval_semantic_raw_component_io import capture_file, read_model_members, verify_unchanged


MEMBERS = (
    "declaration.json", "report.json", "source-manifest.json",
    "sources.zip", "terminal.json",
)


def _bundle(root: Path) -> Path:
    root.mkdir()
    for name in MEMBERS:
        (root / name).write_bytes(b"public fixture\n")
    return root


def test_complete_bundle_returns_original_member_bytes(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "model")
    assert dict(read_model_members(root)) == {
        name: b"public fixture\n" for name in MEMBERS
    }


@pytest.mark.parametrize("missing", MEMBERS)
def test_partial_bundle_refuses(tmp_path: Path, missing: str) -> None:
    root = _bundle(tmp_path / "model")
    (root / missing).unlink()
    with pytest.raises(PairReportRefusal):
        read_model_members(root)


def test_extra_bundle_member_refuses(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "model")
    (root / "unexpected.json").write_bytes(b"{}\n")
    with pytest.raises(PairReportRefusal):
        read_model_members(root)


def test_symlink_root_refuses(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "model")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(PairReportRefusal):
        read_model_members(alias)


def test_symlink_member_refuses(tmp_path: Path) -> None:
    root = _bundle(tmp_path / "model")
    target = tmp_path / "external.json"
    target.write_bytes(b"{}\n")
    (root / "report.json").unlink()
    (root / "report.json").symlink_to(target)
    with pytest.raises(PairReportRefusal):
        read_model_members(root)


def test_fifo_is_refused_before_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("special files must refuse before open")
    monkeypatch.setattr(io_module.os, "open", forbidden_open)
    with pytest.raises(PairReportRefusal, match="unsafe"):
        capture_file(fifo)


def test_socket_is_refused_before_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "socket"
    monkeypatch.chdir(tmp_path)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind("socket")
        with pytest.raises(PairReportRefusal, match="unsafe"):
            capture_file(path)


def test_device_is_refused() -> None:
    with pytest.raises(PairReportRefusal):
        capture_file(Path("/dev/null"))


def test_open_is_nonblocking_and_nofollow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "regular"
    path.write_bytes(b"public")
    original = io_module.os.open
    observed = []
    def observe_open(name, flags):
        observed.append(flags)
        return original(name, flags)
    monkeypatch.setattr(io_module.os, "open", observe_open)
    assert capture_file(path).raw == b"public"
    assert observed[0] & os.O_NONBLOCK
    assert observed[0] & os.O_NOFOLLOW


def test_bounded_read_refuses_oversize_without_allocating_it(tmp_path: Path) -> None:
    path = tmp_path / "large"
    path.write_bytes(b"1234")
    with pytest.raises(PairReportRefusal, match="size"):
        capture_file(path, limit=3)


def test_composed_read_detects_replacement_with_equal_bytes(tmp_path: Path) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"public")
    before = capture_file(path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"public")
    replacement.replace(path)
    with pytest.raises(PairReportRefusal, match="source_changed"):
        verify_unchanged([before])


def test_read_detects_content_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"public")
    original = io_module.os.read
    def mutate_after_read(descriptor, limit):
        result = original(descriptor, limit)
        path.write_bytes(b"changed")
        return result
    monkeypatch.setattr(io_module.os, "read", mutate_after_read)
    with pytest.raises(PairReportRefusal, match="changed"):
        capture_file(path)
