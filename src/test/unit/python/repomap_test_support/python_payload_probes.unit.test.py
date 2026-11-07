"""Unit tests for the python_payload stdlib import probe test-support adapter (ADR 0093)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from common_lore_index.runtime import python_payload as payload
from repomap_test_support.python_payload_probes import (
    is_stdlib_import_probe_command,
    make_stdlib_import_probe_runner,
    validate_allowed_stdlib_modules,
)
from runner_coverage_bootstrap import RUNNER_BOOTSTRAP_MARKER

_PY = "/usr/local/bin/python3.12"
ENV_COVERAGE_PROCESS_START = "COVERAGE_PROCESS_START"
ENV_COVERAGE_CHILD_MANIFEST_DIR = "COVERAGE_CHILD_MANIFEST_DIR"
ENV_COVERAGE_SESSION_INVOCATION_ID = "COVERAGE_SESSION_INVOCATION_ID"
ENV_COVERAGE_SESSION_SUITE = "COVERAGE_SESSION_SUITE"
ENV_COVERAGE_SESSION_REVISION = "COVERAGE_SESSION_REVISION"


def _seed_coverage_env(bootstrap_dir: Path, *, extra_pythonpath: str | None = "/opt/custom/py") -> dict[str, str]:
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    (bootstrap_dir / "sitecustomize.py").write_text(f"{RUNNER_BOOTSTRAP_MARKER}\n", encoding="utf-8")
    py_path = (
        f"{bootstrap_dir}{os.pathsep}{extra_pythonpath}"
        if extra_pythonpath
        else str(bootstrap_dir)
    )
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "CALLER_SENTINEL": "preserved",
        "PYTHONPATH": py_path,
        "COVERAGE_FILE": "/tmp/stale/.coverage",
        "COVERAGE_PROCESS_CONFIG": "stub-serialized-coverage-config",
        ENV_COVERAGE_PROCESS_START: "/tmp/stale/coverage.rc",
        ENV_COVERAGE_CHILD_MANIFEST_DIR: "/tmp/stale/manifests",
        ENV_COVERAGE_SESSION_INVOCATION_ID: "inv-ci64",
        ENV_COVERAGE_SESSION_SUITE: "int",
        ENV_COVERAGE_SESSION_REVISION: "0284aa36",
    }


def test_validate_allowed_stdlib_modules_accepts_stdlib_and_refuses_product_or_invalid() -> None:
    allowed = validate_allowed_stdlib_modules(["math", "cmath", "_tkinter"])
    assert allowed == frozenset({"math", "cmath", "_tkinter"})

    for invalid in (
        [],
        [""],
        ["1bad"],
        ["math.sin"],
        ["common_lore_index"],
        ["common_lore_index.runtime"],
        ["repomap_test_support"],
        ["not_a_stdlib_module_xyz"],
    ):
        with pytest.raises(ValueError):
            validate_allowed_stdlib_modules(invalid)

    with pytest.raises(ValueError, match="executable must be a non-empty string"):
        make_stdlib_import_probe_runner(["math"], executable="")


def test_probe_runner_scrubs_coverage_env_only_for_approved_stdlib_probes_and_preserves_caller_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot_dir = tmp_path / "cov_bootstrap"
    base_env = _seed_coverage_env(boot_dir, extra_pythonpath="/opt/custom/py")
    for key, val in base_env.items():
        monkeypatch.setenv(key, val)
    env_before = dict(os.environ)

    recorded: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(command: list[str], *_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raw_env = kwargs.get("env")
        recorded.append((list(command), dict(raw_env) if isinstance(raw_env, dict) else None))
        return subprocess.CompletedProcess(command, 0, "", "")

    runner = make_stdlib_import_probe_runner(("math", "cmath", "_tkinter"), run=fake_run, executable=_PY)

    caller_probe_env = {**os.environ, "LD_BIND_NOW": "1"}
    caller_probe_snapshot = dict(caller_probe_env)
    res = runner([_PY, "-I", "-B", "-c", "import math"], env=caller_probe_env, capture_output=True, text=True)
    assert res.returncode == 0
    assert caller_probe_env == caller_probe_snapshot
    assert dict(os.environ) == env_before

    assert len(recorded) == 1
    cmd, child_env = recorded[0]
    assert cmd == [_PY, "-I", "-B", "-c", "import math"]
    assert child_env is not None
    assert child_env["LD_BIND_NOW"] == "1"
    assert child_env["CALLER_SENTINEL"] == "preserved"
    assert child_env["PYTHONPATH"] == "/opt/custom/py"
    for cov_key in (
        "COVERAGE_FILE",
        "COVERAGE_PROCESS_CONFIG",
        ENV_COVERAGE_PROCESS_START,
        ENV_COVERAGE_CHILD_MANIFEST_DIR,
        ENV_COVERAGE_SESSION_INVOCATION_ID,
        ENV_COVERAGE_SESSION_SUITE,
        ENV_COVERAGE_SESSION_REVISION,
    ):
        assert cov_key not in child_env

    boot_only_env = _seed_coverage_env(boot_dir, extra_pythonpath=None)
    monkeypatch.setenv("PYTHONPATH", boot_only_env["PYTHONPATH"])
    runner([_PY, "-I", "-B", "-c", "import _tkinter"], capture_output=True, text=True)
    _, implicit_env = recorded[-1]
    assert implicit_env is not None
    assert "PYTHONPATH" not in implicit_env
    assert "COVERAGE_PROCESS_CONFIG" not in implicit_env
    assert ENV_COVERAGE_PROCESS_START not in implicit_env


def test_non_probe_commands_pass_through_untouched_and_unapproved_probes_refuse(
    tmp_path: Path,
) -> None:
    boot_dir = tmp_path / "cov_bootstrap"
    raw_cov_env = _seed_coverage_env(boot_dir)
    recorded: list[tuple[Any, dict[str, Any]]] = []

    def fake_run(command: Any, *_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded.append((command, dict(kwargs)))
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    runner = make_stdlib_import_probe_runner(("math", "cmath"), run=fake_run, executable=_PY)

    runner(["ldd", "/usr/local/lib/python3.12/lib-dynload/math.so"], capture_output=True, text=True)
    assert recorded[-1][0] == ["ldd", "/usr/local/lib/python3.12/lib-dynload/math.so"]
    assert "env" not in recorded[-1][1]

    runner(["dpkg-query", "-S", "/lib/libc.so.6"], env=raw_cov_env, capture_output=True, text=True)
    assert recorded[-1][0] == ["dpkg-query", "-S", "/lib/libc.so.6"]
    assert recorded[-1][1]["env"] == raw_cov_env
    assert "COVERAGE_PROCESS_CONFIG" in recorded[-1][1]["env"]
    assert ENV_COVERAGE_PROCESS_START in recorded[-1][1]["env"]

    runner([_PY, "-m", "pytest"], env=raw_cov_env)
    assert recorded[-1][0] == [_PY, "-m", "pytest"]
    assert recorded[-1][1]["env"] == raw_cov_env
    assert "COVERAGE_PROCESS_CONFIG" in recorded[-1][1]["env"]

    runner(["/other/python3", "-I", "-B", "-c", "import math"], env=raw_cov_env)
    assert recorded[-1][0] == ["/other/python3", "-I", "-B", "-c", "import math"]
    assert recorded[-1][1]["env"] == raw_cov_env
    assert "COVERAGE_PROCESS_CONFIG" in recorded[-1][1]["env"]

    assert (
        is_stdlib_import_probe_command(
            "not-a-sequence", executable=_PY, allowed_modules=frozenset({"math"})
        )
        is False
    )

    count_before = len(recorded)
    for refused_cmd in (
        [_PY, "-I", "-B", "-c", "import json"],
        [_PY, "-I", "-B", "-c", "import common_lore_index"],
        [_PY, "-I", "-B", "-c", "import math; import os"],
        [_PY, "-I", "-B", "-c", "print(1)"],
        [_PY, "-c", "import math"],
    ):
        with pytest.raises(ValueError, match="refusing unapproved python"):
            runner(refused_cmd, env=raw_cov_env)
    assert len(recorded) == count_before


def test_payload_observe_with_probe_runner_preserves_outcomes_and_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot_dir = tmp_path / "cov_bootstrap"
    for key, val in _seed_coverage_env(boot_dir).items():
        monkeypatch.setenv(key, val)

    mount = tmp_path / "mount"
    dyn = mount / payload.DYNLOAD.lstrip("/")
    dyn.mkdir(parents=True, exist_ok=True)
    elf_bytes = b"\x7fELF\x02\x01\x01" + bytes(11) + (183).to_bytes(2, "little") + b"body"
    (dyn / "math.cpython-312.so").write_bytes(elf_bytes)
    (dyn / "_tkinter.cpython-312.so").write_bytes(elf_bytes)
    (dyn / "1bad.cpython-312.so").write_bytes(elf_bytes)

    seen_calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(command: list[str], *_args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        seen_calls.append((list(command), dict(env) if isinstance(env, dict) else None))
        if command[0] == "ldd":
            return subprocess.CompletedProcess(command, 0, "\tstatically linked\n", "")
        if command[-1] == "import math":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[-1] == "import _tkinter":
            return subprocess.CompletedProcess(command, 1, "", "ImportError: libtk8.6.so\n")
        raise AssertionError(f"unexpected command: {command}")

    probe_run = make_stdlib_import_probe_runner(("math", "_tkinter"), run=fake_run, executable=_PY)
    _entries, obs = payload.observe(probe_run, mount, _PY, "aarch64")

    assert obs["imports"] == ["math"]
    assert obs["failed"]["1bad"] == {"exit": None, "error": "not an importable module name"}
    assert obs["failed"]["_tkinter"] == {"exit": 1, "error": "ImportError: libtk8.6.so"}

    ldd_envs = [env for cmd, env in seen_calls if cmd[0] == "ldd"]
    probe_envs = [env for cmd, env in seen_calls if cmd[0] == _PY]
    assert ldd_envs == [None, None, None]
    assert len(probe_envs) == 2
    for p_env in probe_envs:
        assert p_env is not None
        assert p_env["LD_BIND_NOW"] == "1"
        assert p_env["CALLER_SENTINEL"] == "preserved"
        assert "COVERAGE_PROCESS_CONFIG" not in p_env
        assert ENV_COVERAGE_PROCESS_START not in p_env
