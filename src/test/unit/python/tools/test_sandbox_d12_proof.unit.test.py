"""Unit tests for pre-sandbox D12 system proof verification and stdin pipe transfer."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ci.d12_system_grant import D12SystemGrantError
from repomap_test_support.d12_system_test_children import (
    hold_exclusive_flock,
    poisoned_coverage_base_env,
    transfer_proof_locally,
)
import test_sandbox as sandbox_owner
from test_sandbox_arguments import (
    INNER_D12_SYSTEM_PROOF_PATH,
    MAX_D12_SYSTEM_PROOF_BYTES,
    sandbox_report_arguments,
    transfer_system_proof,
)
from test_sandbox_dispatch import integration_sandbox_dispatch
from src.test.unit.python.tools.sandbox_test_fixtures import (
    _capacity_boundary as _capacity_boundary,
    completed,
    finished_follower,
)


def test_sandbox_report_arguments_rewrites_and_captures_system_proof_bytes(
    tmp_path: Path,
) -> None:
    proof_file = tmp_path / "proof.json"
    raw_bytes = b'{"schema": "repomap-d12-system-admission-proof-v1"}\n'
    proof_file.write_bytes(raw_bytes)

    res = sandbox_report_arguments(
        [
            "--suite",
            "system",
            "--d12-system-proof-json",
            str(proof_file),
            "--no-coverage",
        ],
        repo_root=tmp_path,
    )
    inner_argv, dest = res
    assert dest is None
    assert res.d12_proof_bytes == raw_bytes
    idx = inner_argv.index("--d12-system-proof-json")
    assert inner_argv[idx + 1] == str(INNER_D12_SYSTEM_PROOF_PATH)

    res_eq = sandbox_report_arguments(
        [
            "--suite=system",
            f"--d12-system-proof-json={proof_file}",
        ],
        repo_root=tmp_path,
    )
    assert f"--d12-system-proof-json={INNER_D12_SYSTEM_PROOF_PATH}" in res_eq.inner_argv
    assert res_eq.d12_proof_bytes == raw_bytes


def test_sandbox_report_arguments_rejects_invalid_proof_options_and_files(
    tmp_path: Path,
) -> None:
    proof_file = tmp_path / "proof.json"
    proof_file.write_bytes(b'{"ok": true}\n')

    with pytest.raises(RuntimeError, match="only valid with --suite system"):
        sandbox_report_arguments(
            ["--suite", "int", "--d12-system-proof-json", str(proof_file)],
            repo_root=tmp_path,
        )

    with pytest.raises(RuntimeError, match="duplicate --d12-system-proof-json"):
        sandbox_report_arguments(
            [
                "--suite",
                "system",
                "--d12-system-proof-json",
                str(proof_file),
                f"--d12-system-proof-json={proof_file}",
            ],
            repo_root=tmp_path,
        )

    with pytest.raises(RuntimeError, match="cannot be passed after '--'"):
        sandbox_report_arguments(
            ["--suite", "system", "--", "--d12-system-proof-json", str(proof_file)],
            repo_root=tmp_path,
        )

    symlink_proof = tmp_path / "symlink-proof.json"
    symlink_proof.symlink_to(proof_file)
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        sandbox_report_arguments(
            ["--suite", "system", "--d12-system-proof-json", str(symlink_proof)],
            repo_root=tmp_path,
        )

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b" " * MAX_D12_SYSTEM_PROOF_BYTES + b"}")
    with pytest.raises(RuntimeError, match="exceeds size limit"):
        sandbox_report_arguments(
            ["--suite", "system", "--d12-system-proof-json", str(oversized)],
            repo_root=tmp_path,
        )


def test_transfer_system_proof_pipes_via_docker_exec_with_o_excl(
    tmp_path: Path,
) -> None:
    payload = b'{"schema": "repomap-d12-system-admission-proof-v1"}\n'
    calls: list[tuple[list[str], str | None]] = []

    def fake_captured(
        _runner: Any,
        cmd: list[str],
        *,
        input_text: str | None = None,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        _ = timeout
        calls.append((cmd, input_text))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    transfer_system_proof(
        MagicMock(),
        "cid-1234",
        payload,
        captured=fake_captured,
    )
    assert len(calls) == 1
    cmd, stdin_data = calls[0]
    assert cmd[:6] == ["docker", "exec", "-i", "cid-1234", "python3", "-I"]
    assert "O_EXCL" in cmd[7]
    assert "0o600" in cmd[7]
    assert stdin_data == payload.decode("utf-8")


def test_integration_sandbox_dispatch_verifies_system_proof_before_sandbox_image_build(
    tmp_path: Path,
) -> None:
    args = SimpleNamespace(suite="system", d12_system_proof_json=None)
    ensure_image_mock = MagicMock()
    with (
        patch("test_sandbox.active_sandbox", return_value=False),
        patch("test_sandbox.ensure_sandbox_image", ensure_image_mock),
        patch(
            "test_sandbox_dispatch.verify_host_system_proof_for_dispatch",
            side_effect=D12SystemGrantError("missing proof before sandbox build"),
        ),
    ):
        rc = integration_sandbox_dispatch(
            args, ["--suite", "system"], repo_root=tmp_path
        )
    assert rc == 2
    ensure_image_mock.assert_not_called()


def test_run_in_sandbox_transfers_proof_and_cleans_outer_on_transfer_failure(
    tmp_path: Path,
) -> None:
    proof_file = tmp_path / "proof.json"
    proof_file.write_bytes(b'{"ok": true}\n')
    outer_id = "d" * 64
    empty = sandbox_owner.HostSnapshot(
        frozenset(), frozenset(), frozenset(), frozenset()
    )
    calls: list[list[str]] = []

    def fake_runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        if (
            command[:4] == ["docker", "exec", "-i", outer_id]
            and len(command) > 7
            and "repomap-d12-system-proof" in command[7]
        ):
            return completed(command, status=1)
        return completed(command)

    rc = sandbox_owner.run_in_sandbox(
        ["--suite", "system", "--d12-system-proof-json", str(proof_file)],
        repo_root=tmp_path,
        image_id="sha256:" + "e" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_a, **_kw: None,
    )
    assert rc == 2
    assert ["docker", "rm", "-f", "-v", outer_id] in calls


def test_sandbox_report_arguments_rejects_fifo_proof_nonblocking(
    tmp_path: Path,
) -> None:
    fifo_path = tmp_path / "fifo-proof.json"
    os.mkfifo(fifo_path)
    with pytest.raises(RuntimeError, match="is not a regular file"):
        sandbox_report_arguments(
            ["--suite", "system", "--d12-system-proof-json", str(fifo_path)],
            repo_root=tmp_path,
        )


def test_isolated_stdlib_child_helpers_scrub_coverage_env_and_enforce_o_excl_and_flock(
    tmp_path: Path,
) -> None:
    parent_before = (
        os.environ.get("COVERAGE_PROCESS_START"),
        os.environ.get("COVERAGE_PROCESS_CONFIG"),
    )
    poisoned = poisoned_coverage_base_env()
    assert (
        os.environ.get("COVERAGE_PROCESS_START"),
        os.environ.get("COVERAGE_PROCESS_CONFIG"),
    ) == parent_before
    target_proof = tmp_path / "inner" / "proof.json"
    proof_bytes = b'{"schema": "repomap-d12-system-admission-proof-v1"}\n'
    recorded, digest = transfer_proof_locally(
        None, "cid-unit", proof_bytes, target_path=target_proof, base_env=poisoned
    )
    assert len(recorded) == 8 and recorded[:7] == ["docker", "exec", "-i", "cid-unit", "python3", "-I", "-c"]
    assert "O_EXCL" in recorded[7] and "0o600" in recorded[7]
    assert digest == hashlib.sha256(proof_bytes).hexdigest()
    assert target_proof.read_bytes() == proof_bytes
    assert stat.S_IMODE(target_proof.lstat().st_mode) == 0o600
    with pytest.raises(RuntimeError, match="integration sandbox D12 system proof transfer failed"):
        transfer_proof_locally(
            None, "cid-unit", proof_bytes, target_path=target_proof, base_env=poisoned
        )
    lock_file = tmp_path / "contended.lock"
    with hold_exclusive_flock(lock_file, base_env=poisoned) as holder:
        assert holder.poll() is None
        with pytest.raises(RuntimeError, match="flock holder child failed"):
            with hold_exclusive_flock(lock_file, base_env=poisoned):
                pass
    assert holder.poll() == 0

    never_spawn = MagicMock()
    bad_sanitizer = lambda **_kw: {"COVERAGE_PROCESS_START": "/bad"}
    with pytest.raises(RuntimeError, match="unresolved coverage env"):
        transfer_proof_locally(
            None, "cid-unit", proof_bytes, target_path=tmp_path / "no.json",
            base_env=poisoned, sanitizer=bad_sanitizer, run_child=never_spawn,
        )
    with pytest.raises(RuntimeError, match="unresolved coverage env"):
        with hold_exclusive_flock(lock_file, base_env=poisoned, sanitizer=bad_sanitizer, popen_fn=never_spawn):
            pass
    never_spawn.assert_not_called()

    def _failing_child(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert "leaked coverage env" in cmd[3]
        assert not any(k.startswith("COVERAGE_") for k in kw["env"])
        return subprocess.CompletedProcess(cmd, 1, "", "simulated child failure")

    with pytest.raises(RuntimeError, match="integration sandbox D12 system proof transfer failed"):
        transfer_proof_locally(
            None, "cid-unit", proof_bytes, target_path=tmp_path / "fail.json",
            base_env=poisoned, run_child=_failing_child,
        )
    fake_proc = MagicMock()
    fake_proc.stdout.readline.return_value = "locked\n"
    fake_proc.wait.side_effect = [subprocess.TimeoutExpired("python3", 10), 0]
    with hold_exclusive_flock(lock_file, base_env=poisoned, popen_fn=lambda *_a, **_kw: fake_proc):
        pass
    fake_proc.kill.assert_called_once()
    fake_proc.stdin.close.assert_called_once()
    fake_proc.stdout.close.assert_called_once()
    fake_proc.stderr.close.assert_called_once()
    assert (
        os.environ.get("COVERAGE_PROCESS_START"),
        os.environ.get("COVERAGE_PROCESS_CONFIG"),
    ) == parent_before
