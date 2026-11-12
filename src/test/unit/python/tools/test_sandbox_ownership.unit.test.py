"""Host receipt protocol: real pipes, closed framing and sandbox lifecycle joins."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import cast
from unittest.mock import Mock

import pytest

import test_sandbox as sandbox
import test_sandbox_ownership as ownership


def control(root: Path) -> dict:
    return {"schema": ownership.CONTROL_SCHEMA, "challenge": "a" * 64,
            "pid": os.getpid(), "birth": 123.5, "source_identity": "sha256:" + "b" * 64,
            "source_root": str(root), "argv": ["--suite", "int"], "sdk_image_id": "sha256:" + "d" * 64}


def close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


@pytest.fixture
def channel(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    control_read, control_write = os.pipe()
    receipt_read, receipt_write = os.pipe()
    monkeypatch.setenv(ownership.CONTROL_FD_ENV, str(control_read))
    monkeypatch.setenv(ownership.RECEIPT_FD_ENV, str(receipt_write))
    try:
        yield tmp_path, control_read, control_write, receipt_read, receipt_write
    finally:
        for fd in (control_read, control_write, receipt_read, receipt_write):
            close(fd)


def test_real_pipe_reports_actual_identity_once_and_closes_host_channel(channel):
    root, reader, writer, output, endpoint = channel
    value = control(root)
    os.write(writer, ownership.encode_frame(value))
    os.close(writer)
    reporter = ownership.prepare_ownership_reporter(value["argv"], root)
    assert reporter is not None and not os.get_inheritable(endpoint)
    assert all(name not in os.environ for name in ownership.CHANNEL_ENV)
    with pytest.raises(OSError):
        os.fstat(reader)
    reporter("c" * 64, "sha256:" + "d" * 64, "e" * 64)
    receipt = ownership.decode_frame(ownership.read_frame_fd(output), receipt=True)
    assert receipt == dict(value, schema=ownership.RECEIPT_SCHEMA, cid="c" * 64,
                           sdk_image_id="sha256:" + "d" * 64,
                           marker_sha256="sha256:" + hashlib.sha256(("e" * 64).encode()).hexdigest())
    assert reporter.spent and reporter.fd == -1
    with pytest.raises(RuntimeError, match="already spent"):
        reporter("c" * 64, "sha256:" + "d" * 64, "e" * 64)


@pytest.mark.parametrize("field,value", [("pid", True), ("pid", 0), ("birth", float("inf")),
    ("birth", True), ("birth", 0), ("challenge", "short"), ("source_identity", "b" * 64),
    ("source_root", "relative"), ("argv", []), ("argv", [None]), ("schema", "other")])
def test_control_rejects_invalid_closed_fields(tmp_path, field, value):
    payload = dict(control(tmp_path), **{field: value})
    with pytest.raises(RuntimeError):
        ownership.decode_frame(json.dumps(payload).encode())


@pytest.mark.parametrize("raw", [b"", b"x" * 4097, b"[]", b"{} {}", b'{"schema":1,"schema":2}'])
def test_control_rejects_invalid_framing(raw):
    with pytest.raises(RuntimeError):
        ownership.decode_frame(raw)


@pytest.mark.parametrize("change", ["extra", "pid", "root", "argv"])
def test_host_mismatch_closes_receipt_without_emitting(channel, change):
    root, _, writer, output, endpoint = channel
    value = control(root)
    if change == "extra":
        value["unexpected"] = True
    elif change == "pid":
        value["pid"] += 1
    elif change == "root":
        value["source_root"] = str(root / "other")
    else:
        value["argv"] += ["--sandbox"]
    os.write(writer, json.dumps(value).encode())
    os.close(writer)
    with pytest.raises(RuntimeError):
        ownership.prepare_ownership_reporter(["--suite", "int"], root)
    assert os.read(output, 1) == b""
    with pytest.raises(OSError):
        os.fstat(endpoint)


def test_absent_configuration_preserves_default(monkeypatch, tmp_path):
    for name in ownership.CHANNEL_ENV:
        monkeypatch.delenv(name, raising=False)
    assert ownership.prepare_ownership_reporter([], tmp_path) is None


def test_partial_configuration_is_fatal(monkeypatch, tmp_path):
    monkeypatch.setenv(ownership.CONTROL_FD_ENV, "3")
    monkeypatch.delenv(ownership.RECEIPT_FD_ENV, raising=False)
    with pytest.raises(RuntimeError, match="partial"):
        ownership.prepare_ownership_reporter([], tmp_path)
    assert all(name not in os.environ for name in ownership.CHANNEL_ENV)


def test_invalid_receipt_descriptor_is_neutralized_before_refusal(tmp_path, monkeypatch):
    reader, writer = os.pipe()
    try:
        with (tmp_path / "not-a-pipe").open("wb") as stream:
            os.set_inheritable(stream.fileno(), True)
            monkeypatch.setenv(ownership.CONTROL_FD_ENV, str(reader))
            monkeypatch.setenv(ownership.RECEIPT_FD_ENV, str(stream.fileno()))
            with pytest.raises(RuntimeError, match="not a pipe"):
                ownership.prepare_ownership_reporter(["--suite", "int"], tmp_path)
            assert not os.get_inheritable(stream.fileno())
            assert all(name not in os.environ for name in ownership.CHANNEL_ENV)
    finally:
        close(reader)
        close(writer)


def test_control_sender_must_close_even_after_complete_frame(channel):
    root, _, writer, output, _ = channel
    os.write(writer, ownership.encode_frame(control(root)))
    with pytest.raises(RuntimeError, match="not closed"):
        ownership.prepare_ownership_reporter(["--suite", "int"], root)
    assert os.read(output, 1) == b""


def test_receipt_endpoint_and_configuration_do_not_cross_exec(channel):
    root, _, writer, _, endpoint = channel
    os.write(writer, ownership.encode_frame(control(root)))
    os.close(writer)
    reporter = ownership.prepare_ownership_reporter(["--suite", "int"], root)
    assert reporter is not None
    try:
        code = (
            "import os,sys;"
            "assert all(k not in os.environ for k in sys.argv[2:]);"
            "fd=int(sys.argv[1]);"
            "exec('try:\\n os.fstat(fd)\\nexcept OSError:\\n pass\\nelse:\\n raise AssertionError(\"fd leaked\")')"
        )
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
            str(endpoint), *ownership.CHANNEL_ENV], close_fds=False, capture_output=True)
        assert result.returncode == 0
    finally:
        reporter.close()


@pytest.mark.parametrize("value", ["0", "1", "2", "-3", "bogus", "99999999"])
def test_invalid_or_standard_descriptor_is_fatal(tmp_path, value):
    with pytest.raises((RuntimeError, OSError)):
        ownership._pipe_fd(value, writing=False)


def test_nonpipe_wrong_access_and_same_pipe_refuse(tmp_path, monkeypatch):
    with (tmp_path / "file").open("wb") as stream:
        with pytest.raises(RuntimeError, match="not a pipe"):
            ownership._pipe_fd(str(stream.fileno()), writing=True)
    reader, writer = os.pipe()
    try:
        with pytest.raises(RuntimeError, match="access"):
            ownership._pipe_fd(str(reader), writing=True)
        monkeypatch.setenv(ownership.CONTROL_FD_ENV, str(reader))
        monkeypatch.setenv(ownership.RECEIPT_FD_ENV, str(writer))
        with pytest.raises(RuntimeError, match="shared pipe|not closed"):
            ownership.prepare_ownership_reporter(["--suite", "int"], tmp_path)
    finally:
        close(reader)
        close(writer)


@pytest.mark.parametrize("status,cached", [(0, "sha256:" + "d" * 64), (1, None), (0, "sha256:" + "f" * 64)])
def test_attested_cache_never_builds_pulls_or_prunes(tmp_path, monkeypatch, status, cached):
    monkeypatch.setattr(sandbox._images, "sandbox_recipe_inputs", lambda _path: {})
    monkeypatch.setattr(sandbox._images, "sandbox_recipe", lambda _inputs: "recipe")
    monkeypatch.setattr(sandbox, "_inspect_managed_image", lambda _runner, _recipe: (status, cached))
    forbidden = Mock(side_effect=AssertionError("cache-only route cannot mutate images"))
    monkeypatch.setattr(sandbox, "ensure_sandbox_image", forbidden)
    monkeypatch.setattr(sandbox, "prune_managed_sandbox_images", forbidden)
    if status == 0 and cached == "sha256:" + "d" * 64:
        assert sandbox.cached_sandbox_image(dockerfile=tmp_path / "Dockerfile",
            expected_image_id=cached) == cached
    else:
        with pytest.raises(RuntimeError, match="exact cached SDK"):
            sandbox.cached_sandbox_image(dockerfile=tmp_path / "Dockerfile",
                expected_image_id="sha256:" + "d" * 64)
    forbidden.assert_not_called()


@pytest.mark.parametrize("failure", ["marker", "create", "receipt", None])
def test_sandbox_reports_after_actual_creation_and_marker_and_cleans_failure(tmp_path, monkeypatch, failure):
    events = []
    cid, image = "c" * 64, "sha256:" + "d" * 64
    empty = sandbox.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def runner(command, **kwargs):
        events.append(command)
        status, output = 0, ""
        if command[:3] == ["docker", "run", "-d"]:
            status, output = (1, "") if failure == "create" else (0, cid + "\n")
        elif command[:2] == ["docker", "wait"]:
            output = "0\n"
        elif command[:3] == ["docker", "container", "inspect"]:
            status = 1
        elif command[:3] == ["docker", "exec", "-i"]:
            events.append("marker")
            if failure == "marker":
                status = 1
        return subprocess.CompletedProcess(command, status, stdout=output, stderr="")

    def report(actual_cid, actual_image, marker):
        assert (actual_cid, actual_image) == (cid, image)
        assert "marker" in events and len(marker) == 64
        events.append("receipt")
        if failure == "receipt":
            raise RuntimeError("receipt failure")

    class Follower:
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(sandbox, "bind_backing_capacity", lambda *_args, **_kwargs: None)
    status = sandbox.run_in_sandbox(["--suite", "int"], repo_root=tmp_path, image_id=image,
        runner=runner, follower_factory=cast(sandbox.LogFollowerFactory, lambda _command: Follower()),
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None, ownership_reporter=report)
    assert status == (0 if failure is None else 2)
    assert ("receipt" in events) == (failure in {None, "receipt"})
    assert (["docker", "rm", "-f", "-v", cid] in events) == (failure != "create")
