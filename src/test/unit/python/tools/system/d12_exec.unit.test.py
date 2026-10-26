"""Unit tests for tools.system.d12_exec and tools.system.compose_command."""

from __future__ import annotations

import errno
from pathlib import Path
import subprocess
import traceback
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.system.compose_command import _run_compose, normalize_compose_args
from tools.system.config import SystemTestError
from tools.system.d12_exec import (
    INNER_DOCKER_HOST,
    BoundedExecContainer,
    build_d12_container_exec_command,
    run_d12_container_exec,
    wrap_create_with_bounded_exec,
)


def test_build_and_run_d12_container_exec() -> None:
    cmd = build_d12_container_exec_command(
        "cid-123",
        ["python", "-V"],
        user="postgres",
        workdir="/workspace",
        env={"PGUSER": "postgres"},
    )
    assert cmd == [
        "docker",
        "exec",
        "-i",
        "--user",
        "postgres",
        "--workdir",
        "/workspace",
        "--env",
        "PGUSER=postgres",
        "cid-123",
        "python",
        "-V",
    ]
    calls: list[list[str]] = []

    def fake_run(c: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(c))
        return subprocess.CompletedProcess(c, 0, "Python 3.12\n", "")

    res = run_d12_container_exec(
        "cid-123",
        ["python", "-V"],
        run_cmd=fake_run,
    )
    assert res.returncode == 0
    assert calls[0][:3] == ["docker", "exec", "-i"]


def test_bounded_exec_container_demux_and_wrap_create() -> None:
    calls: list[list[str]] = []

    def fake_run(c: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(c))
        if kw.get("stderr") == subprocess.STDOUT:
            return subprocess.CompletedProcess(c, 0, b"out\nerr\n", b"")
        return subprocess.CompletedProcess(c, 0, b"out\n", b"err\n")

    raw_container = SimpleNamespace(id="cid-999", status="running")
    wrapped = BoundedExecContainer(
        raw_container, default_timeout_seconds=15.0, run_cmd=fake_run
    )
    res_combined = wrapped.exec_run(["echo", "hi"], demux=False)
    assert res_combined.exit_code == 0
    assert res_combined.output == b"out\nerr\n"

    res_demux = wrapped.exec_run(["echo", "hi"], demux=True)
    assert res_demux.exit_code == 0
    assert res_demux.output == (b"out\n", b"err\n")

    wrapped_create = wrap_create_with_bounded_exec(
        lambda *_a, **_kw: ("cid-999", raw_container),
        default_timeout_seconds=15.0,
        run_cmd=fake_run,
    )
    cid, c_obj = wrapped_create("owner", "client", "img:tag", ["sleep", "1"], label="probe")
    assert cid == "cid-999"
    assert isinstance(c_obj, BoundedExecContainer)


def test_build_d12_container_exec_rejects_empty_inputs() -> None:
    with pytest.raises(SystemTestError, match="non-empty container_id"):
        build_d12_container_exec_command("", ["true"])
    with pytest.raises(SystemTestError, match="non-empty command"):
        build_d12_container_exec_command("cid-123", [])


def test_normalize_compose_args_injects_no_build_and_pull_never() -> None:
    assert normalize_compose_args(["up", "-d", "postgres"]) == [
        "up",
        "--no-build",
        "--pull",
        "never",
        "-d",
        "postgres",
    ]
    assert normalize_compose_args(["run", "--rm", "init-upgrade"]) == [
        "run",
        "--pull",
        "never",
        "--rm",
        "init-upgrade",
    ]
    assert normalize_compose_args(["ps", "--format", "json"]) == [
        "ps",
        "--format",
        "json",
    ]


def test_normalize_compose_args_rejects_build_or_non_never_pull() -> None:
    with pytest.raises(SystemTestError, match="forbidden subcommand 'build'"):
        normalize_compose_args(["build", "http"])
    with pytest.raises(SystemTestError, match="forbidden build flag"):
        normalize_compose_args(["up", "--build", "-d"])
    with pytest.raises(SystemTestError, match="forbidden --pull policy"):
        normalize_compose_args(["up", "--pull", "always", "-d"])
    with pytest.raises(SystemTestError, match="forbidden --pull policy"):
        normalize_compose_args(["run", "--pull=missing", "http"])


def test_run_compose_executes_normalized_command(tmp_path: Path) -> None:
    with patch("tools.system.compose_command.subprocess.run") as run_mock:
        run_mock.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        _run_compose(tmp_path, ["up", "-d", "http"])
    called_cmd = run_mock.call_args.args[0]
    assert called_cmd == [
        "docker",
        "compose",
        "up",
        "--no-build",
        "--pull",
        "never",
        "-d",
        "http",
    ]


def test_run_d12_container_exec_sanitizes_timeout_expired_secret_env() -> None:
    def fake_run(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            cmd=["docker", "exec", "--env", "PGPASSWORD=supersecret", "cid", "python"],
            timeout=10.0,
            output=b"out",
            stderr=b"secret-stderr",
        )

    with pytest.raises(SystemTestError) as exc_info:
        run_d12_container_exec(
            "cid-123", ["python", "-V"], timeout_seconds=10.0, run_cmd=fake_run
        )

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    formatted = "".join(traceback.format_exception(exc))
    for secret in ("supersecret", "PGPASSWORD", "secret-stderr", "/Users/private/secret-path"):
        assert secret not in str(exc)
        assert secret not in formatted


def test_run_d12_container_exec_sanitizes_oserror_secret_env() -> None:
    def fake_run(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
        raise OSError(errno.ENOENT, "No such file or directory", "/Users/private/secret-path")

    with pytest.raises(SystemTestError) as exc_info:
        run_d12_container_exec("cid-123", ["python", "-V"], run_cmd=fake_run)

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    formatted = "".join(traceback.format_exception(exc))
    for secret in ("supersecret", "PGPASSWORD", "secret-stderr", "/Users/private/secret-path"):
        assert secret not in str(exc)
        assert secret not in formatted


def test_bounded_exec_container_sanitizes_timeout_expired_secret_env() -> None:
    def fake_run(*_a: object, **_kw: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(
            cmd=["docker", "exec", "--env", "PGPASSWORD=supersecret", "cid", "python"],
            timeout=15.0,
            output=b"out",
            stderr=b"secret-stderr",
        )

    raw_container = SimpleNamespace(id="cid-999", status="running")
    wrapped = BoundedExecContainer(
        raw_container, default_timeout_seconds=15.0, run_cmd=fake_run
    )
    with pytest.raises(SystemTestError) as exc_info:
        wrapped.exec_run(["python", "-V"])

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    formatted = "".join(traceback.format_exception(exc))
    for secret in ("supersecret", "PGPASSWORD", "secret-stderr", "/Users/private/secret-path"):
        assert secret not in str(exc)
        assert secret not in formatted


def test_bounded_exec_container_sanitizes_oserror_secret_env() -> None:
    def fake_run(*_a: object, **_kw: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError(errno.ENOENT, "No such file or directory", "/Users/private/secret-path")

    raw_container = SimpleNamespace(id="cid-999", status="running")
    wrapped = BoundedExecContainer(
        raw_container, default_timeout_seconds=15.0, run_cmd=fake_run
    )
    with pytest.raises(SystemTestError) as exc_info:
        wrapped.exec_run(["python", "-V"])

    exc = exc_info.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    formatted = "".join(traceback.format_exception(exc))
    for secret in ("supersecret", "PGPASSWORD", "secret-stderr", "/Users/private/secret-path"):
        assert secret not in str(exc)
        assert secret not in formatted


def test_bounded_exec_container_exec_run_pins_docker_host_and_strips_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "test-context")
    monkeypatch.setenv("DOCKER_HOST", "tcp://custom-host:2375")
    captured_env: dict[str, str] = {}

    def fake_run(c: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
        env_arg = kw.get("env")
        if isinstance(env_arg, dict):
            captured_env.update(env_arg)
        return subprocess.CompletedProcess(c, 0, b"ok", b"")

    raw_container = SimpleNamespace(id="cid-999", status="running")
    wrapped = BoundedExecContainer(raw_container, run_cmd=fake_run)
    wrapped.exec_run(["echo", "hi"])

    assert "DOCKER_CONTEXT" not in captured_env
    assert captured_env.get("DOCKER_HOST") == INNER_DOCKER_HOST
