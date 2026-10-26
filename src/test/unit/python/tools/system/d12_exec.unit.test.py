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
    format_build_failure_excerpt,
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


def test_format_build_failure_excerpt_anchors_before_buildkit_echo_and_bounds_multi_kb_output() -> None:
    long_run = "#14 [final 6/6] RUN REPOMAP_EXPECT_LIBPQ=" + ("A" * 1200) + " python3 -I -c 'probe'"
    pkgs = [f"'pkg-{i:03d}'" for i in range(180)]
    pkgs[15] = "'gcc-14-base'"
    assertion_line = f"#14 0.412 AssertionError: [{', '.join(pkgs)}]"
    stderr = "\n".join([
        long_run,
        long_run,
        "#14 0.412 Traceback (most recent call last):",
        '#14 0.412   File "<string>", line 65, in <module>',
        assertion_line,
        '#14 ERROR: process "/bin/sh -c ' + ("B" * 1200) + '" did not complete successfully: exit code: 1',
        "------",
        " > [final 6/6] RUN REPOMAP_EXPECT_LIBPQ=...",
        "0.412 Traceback (most recent call last):",
        "0.412 AssertionError: ['echoed']",
        "------",
        "Dockerfile:42",
        "--------------------",
        "  41 | >>> RUN REPOMAP_EXPECT_LIBPQ=...",
        "--------------------",
    ])
    excerpt = format_build_failure_excerpt(stderr, "ignored stdout")
    assert len(excerpt) <= 2000
    assert excerpt.startswith("#14 [final 6/6] RUN REPOMAP_EXPECT_LIBPQ=")
    assert "#14 0.412 Traceback (most recent call last):" in excerpt
    assert "AssertionError: ['pkg-000'" in excerpt and "'gcc-14-base'" in excerpt
    assert "...[omitted]..." in excerpt
    assert "Dockerfile:42" not in excerpt and "['echoed']" not in excerpt


def test_format_build_failure_excerpt_stdout_fallback_unicode_and_empty() -> None:
    assert format_build_failure_excerpt("   ", "") == ""
    assert format_build_failure_excerpt("something", "", limit=0) == ""
    out_only = (
        "#9 [stage 2/2] RUN check\n#9 0.210 dpkg-query exited 1: पाथ त्रुटि "
        + ("Ω" * 2200)
        + "\n------\nDockerfile:9\n"
    )
    excerpt = format_build_failure_excerpt("  \n ", out_only, limit=2000)
    assert len(excerpt) <= 2000
    assert excerpt.startswith("#9 [stage 2/2] RUN check\n#9 0.210 dpkg-query exited 1:")
    assert "dpkg-query exited 1: पाथ त्रुटि" in excerpt
    assert "...[omitted]..." in excerpt and "Dockerfile:9" not in excerpt
    stderr_msg_only = "\n".join([
        "#1 [internal] load build definition from Dockerfile",
        "#14 [final 6/6] RUN python3 -I -c 'probe'",
        "#14 0.110 intermediate output",
        "#14 0.310 dpkg-query exited 1: package gcc-14-base is not installed",
        '#14 ERROR: process "/bin/sh -c ' + ("P" * 260) + '" did not complete successfully: exit code: 1',
        "------",
        " > [final 6/6] RUN python3 -I -c 'probe':",
    ])
    stderr_excerpt = format_build_failure_excerpt(stderr_msg_only, "", limit=2000)
    assert len(stderr_excerpt) <= 2000
    assert stderr_excerpt.startswith(
        "...[omitted]...\n#14 [final 6/6] RUN python3 -I -c 'probe'\n...[omitted]...\n"
        "#14 0.310 dpkg-query exited 1: package gcc-14-base is not installed"
    )
    assert stderr_excerpt.endswith("\n...[omitted]...")
    assert "intermediate output" not in stderr_excerpt and "> [final 6/6]" not in stderr_excerpt
    refusal_err = "#8 [stage 1/2] RUN payload\n#8 0.100 ok\n#8 0.200 PayloadRefusal: bad hash\n------\n"
    refusal_excerpt = format_build_failure_excerpt(refusal_err, "")
    assert refusal_excerpt.startswith("#8 [stage 1/2] RUN payload\n...[omitted]...\n#8 0.200 PayloadRefusal:")
