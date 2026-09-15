"""Compatibility facade for the RepoMap integration-test sandbox launcher."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import time
from typing import Callable, Mapping

# Keep legacy imported module globals available to callers that patch seams.
_LEGACY_IMPORTS = (Callable, dataclass, hashlib, json, re, secrets, signal)

import test_sandbox_contract as _contract
import test_sandbox_execution as _execution
import test_sandbox_images as _images
import test_sandbox_inner as _inner
from test_sandbox_capacity import bind_backing_capacity
from test_sandbox_report import export_sandbox_report, write_sandbox_diagnostic
from test_sandbox_contract import (
    ALPINE_PROBE_IMAGE,
    BoundaryProver,
    ENV_ACTIVE,
    ENV_SYSTEM_DEADLINE_EPOCH,
    ENV_SYSTEM_START_EPOCH,
    ENV_TOKEN,
    EXACT_CONTAINER_ID,
    EXACT_ID,
    GO_RELEASE_IMAGE,
    HostSnapshot,
    IMAGE_OWNER_LABEL,
    IMAGE_RECIPE_LABEL,
    IMAGE_TAG,
    INNER_DOCKER_HOST,
    INNER_DOCKER_SOCKET,
    INNER_OWNER_PATH,
    INNER_REPORT_ROOT,
    INNER_TEST_SCRATCH_ROOT,
    LogFollower,
    LogFollowerFactory,
    MAX_REPORT_ARCHIVE_BYTES,
    MAX_REPORT_CONTENT_BYTES,
    MAX_REPORT_MEMBERS,
    PRODUCTION_POSTGRES_IMAGE,
    PYTHON_RELEASE_IMAGE,
    ReportArchiveReader,
    Runner,
    Snapshotter,
    TEST_POSTGRES_IMAGE,
)


_CLEANUP_PHASE = False


def active_sandbox(
    environ: Mapping[str, str] | None = None,
    *,
    marker_path: Path = INNER_OWNER_PATH,
    host_socket_exists: bool | None = None,
    inner_socket_exists: bool | None = None,
) -> bool:
    return _contract.active_sandbox(
        environ,
        marker_path=marker_path,
        host_socket_exists=host_socket_exists,
        inner_socket_exists=inner_socket_exists,
        active_name=ENV_ACTIVE,
        token_name=ENV_TOKEN,
        docker_host=INNER_DOCKER_HOST,
        inner_socket=INNER_DOCKER_SOCKET,
    )


def outer_run_command(
    *, image_id: str, container_name: str, repo_root: Path, host_gid: int, argv: list[str]
) -> list[str]:
    return _contract.outer_run_command(
        image_id=image_id,
        container_name=container_name,
        repo_root=repo_root,
        host_gid=host_gid,
        argv=argv,
        exact_id=EXACT_ID,
        inner_docker_host=INNER_DOCKER_HOST,
        start_epoch_name=ENV_SYSTEM_START_EPOCH,
        deadline_epoch_name=ENV_SYSTEM_DEADLINE_EPOCH,
    )


def _captured(
    runner: Runner,
    command: list[str],
    *,
    timeout: int | float = 120,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=_effective_timeout(float(timeout)),
        input=input_text,
    )


def _install_owner_marker(runner: Runner, container_id: str, token: str) -> None:
    marker_writer = (
        "from pathlib import Path; import os,sys; "
        "token=sys.stdin.read().strip(); "
        "assert len(token) == 64 and all(c in '0123456789abcdef' for c in token); "
        f"path=Path({str(INNER_OWNER_PATH)!r}); "
        "path.write_text(token+'\\n', encoding='utf-8'); os.chmod(path, 0o600)"
    )
    result = _captured(
        runner,
        ["docker", "exec", "-i", container_id, "python3", "-c", marker_writer],
        input_text=token + "\n",
    )
    if result.returncode != 0:
        raise RuntimeError("integration sandbox owner marker installation failed")


def _effective_timeout(requested: float) -> float:
    deadline_text = os.environ.get(ENV_SYSTEM_DEADLINE_EPOCH)
    if deadline_text is None:
        return requested
    try:
        remaining = float(deadline_text) - time.time()
    except ValueError as error:
        raise RuntimeError("system deadline environment is malformed") from error
    if not _CLEANUP_PHASE:
        remaining -= 120.0
    if remaining <= 0:
        phase = "cleanup" if _CLEANUP_PHASE else "test"
        raise RuntimeError(f"system {phase} deadline is exhausted")
    return max(1.0, min(requested, remaining))


def _inspect_managed_image(runner: Runner, recipe: str) -> tuple[int, str | None]:
    return _images.inspect_managed_image(
        runner, recipe, captured=_captured, image_tag=IMAGE_TAG,
        owner_label=IMAGE_OWNER_LABEL, recipe_label=IMAGE_RECIPE_LABEL,
        exact_id=EXACT_ID,
    )


def ensure_sandbox_image(*, dockerfile: Path, runner: Runner = subprocess.run) -> str:
    return _images.ensure_sandbox_image(
        dockerfile=dockerfile, runner=runner, captured=_captured,
        inspect=_inspect_managed_image, prune=prune_managed_sandbox_images,
        image_tag=IMAGE_TAG,
    )


def prune_managed_sandbox_images(
    runner: Runner, *, keep_image_id: str, retention_limit: int = 2
) -> None:
    _images.prune_managed_sandbox_images(
        runner, keep_image_id=keep_image_id, captured=_captured, ids=_ids,
        exact_id=EXACT_ID, owner_label=IMAGE_OWNER_LABEL,
        retention_limit=retention_limit,
    )


def _ids(runner: Runner, command: list[str]) -> frozenset[str]:
    return _images.ids(runner, command, captured=_captured)


def snapshot_host_resources(runner: Runner = subprocess.run) -> HostSnapshot:
    return _images.snapshot_host_resources(runner, ids=_ids)


def verify_host_snapshot(before: HostSnapshot, after: HostSnapshot) -> None:
    _images.verify_host_snapshot(before, after)


def _wait_for_inner_daemon(runner: Runner, container_id: str) -> None:
    _inner.wait_for_inner_daemon(runner, container_id, captured=_captured)


def _prepare_inner_images(runner: Runner, container_id: str) -> None:
    _inner.prepare_inner_images(
        runner, container_id, captured=_captured,
        images=(TEST_POSTGRES_IMAGE, PRODUCTION_POSTGRES_IMAGE, ALPINE_PROBE_IMAGE,
                PYTHON_RELEASE_IMAGE, GO_RELEASE_IMAGE),
    )


def _prepare_workspace_and_identity(runner: Runner, container_id: str) -> None:
    _inner.prepare_workspace_and_identity(
        runner, container_id, require_inner_command=_require_inner_command,
        inner_report_root=INNER_REPORT_ROOT,
        inner_test_scratch_root=INNER_TEST_SCRATCH_ROOT,
    )


def _inner_exec(container_id: str, *command: str) -> list[str]:
    return ["docker", "exec", container_id, *command]


def _require_inner_command(
    runner: Runner, container_id: str, command: tuple[str, ...], *, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    result = _captured(runner, _inner_exec(container_id, *command), timeout=timeout)
    if result.returncode != 0:
        operation = " ".join(command[:2])
        diagnostic = result.stderr.strip().replace("\n", " ")[:400]
        raise RuntimeError(
            "integration sandbox boundary probe failed: "
            f"operation={operation!r} status={result.returncode} diagnostic={diagnostic!r}"
        )
    return result


def _remove_inner_container(runner: Runner, outer_id: str, inner_id: str) -> None:
    _inner.remove_inner_container(
        runner, outer_id, inner_id, require_inner_command=_require_inner_command,
        captured=_captured, inner_exec=_inner_exec,
    )


def _probe_inner_volume(runner: Runner, container_id: str, token: str) -> None:
    _inner.probe_inner_volume(
        runner, container_id, token, require_inner_command=_require_inner_command,
        captured=_captured, inner_exec=_inner_exec,
    )


def prove_inner_boundary(runner: Runner, *, container_id: str, token: str) -> None:
    _inner.prove_inner_boundary(
        runner, container_id=container_id, token=token,
        require_inner_command=_require_inner_command, captured=_captured,
        inner_exec=_inner_exec, remove_container=_remove_inner_container,
        probe_volume=_probe_inner_volume, exact_container_id=EXACT_CONTAINER_ID,
        alpine_probe_image=ALPINE_PROBE_IMAGE,
    )


def _run_inner_tests(runner: Runner, container_id: str) -> int:
    return _inner.run_inner_tests(
        runner, container_id, require_inner_command=_require_inner_command,
        captured=_captured,
    )


def _start_log_follower(follower_factory: LogFollowerFactory, container_id: str) -> LogFollower:
    return _execution.start_log_follower(follower_factory, container_id)


def _terminate_log_follower(follower: LogFollower) -> RuntimeError | None:
    return _execution.terminate_log_follower(follower)


def _drain_log_follower(follower: LogFollower) -> RuntimeError | None:
    return _execution.drain_log_follower(follower, terminate=_terminate_log_follower)


def _cleanup_outer(runner: Runner, container_id: str) -> None:
    _execution.cleanup_outer(runner, container_id, captured=_captured)


def _stop_outer(runner: Runner, container_id: str) -> None:
    _execution.stop_outer(runner, container_id, captured=_captured)


def _sandbox_report_arguments(argv: list[str], *, repo_root: Path) -> tuple[list[str], Path | None]:
    return _execution.sandbox_report_arguments(
        argv, repo_root=repo_root, inner_report_root=INNER_REPORT_ROOT
    )


def _read_container_report_archive(container_id: str, required: bool) -> bytes | None:
    return _execution.read_container_report_archive(
        container_id, required, popen=subprocess.Popen,
        inner_report_root=INNER_REPORT_ROOT, max_archive_bytes=MAX_REPORT_ARCHIVE_BYTES,
    )


def _export_sandbox_report(archive: bytes, destination: Path) -> None:
    _execution.export_sandbox_report_archive(
        archive, destination, exporter=export_sandbox_report,
        max_members=MAX_REPORT_MEMBERS, max_content_bytes=MAX_REPORT_CONTENT_BYTES,
    )


INNER_GATE_REQUEST_PATH = _execution.INNER_GATE_REQUEST_PATH


def _transfer_gate_request(
    runner: Runner,
    container_id: str,
    payload: bytes,
    *,
    inner_gate_request_path: Path = INNER_GATE_REQUEST_PATH,
) -> None:
    _execution.transfer_gate_request(
        runner,
        container_id,
        payload,
        captured=_captured,
        inner_gate_request_path=inner_gate_request_path,
    )


def _bounded_cleanup_error(error: Exception) -> RuntimeError:
    return _execution.bounded_cleanup_error(error)


def _set_cleanup_phase(value: bool) -> None:
    global _CLEANUP_PHASE
    _CLEANUP_PHASE = value


def run_in_sandbox(
    argv: list[str], *, repo_root: Path, image_id: str,
    runner: Runner = subprocess.run,
    follower_factory: LogFollowerFactory = subprocess.Popen,
    snapshotter: Snapshotter = snapshot_host_resources,
    boundary_prover: BoundaryProver = prove_inner_boundary,
    archive_reader: ReportArchiveReader = _read_container_report_archive,
) -> int:
    return _execution.run_in_sandbox(
        argv, repo_root=repo_root, image_id=image_id, runner=runner,
        follower_factory=follower_factory, snapshotter=snapshotter,
        boundary_prover=boundary_prover, archive_reader=archive_reader,
        captured=_captured, outer_run_command=outer_run_command,
        install_owner_marker=_install_owner_marker,
        wait_for_inner_daemon=_wait_for_inner_daemon,
        prepare_workspace=_prepare_workspace_and_identity,
        prepare_images=_prepare_inner_images, bind_capacity=bind_backing_capacity,
        effective_timeout=_effective_timeout, run_inner_tests=_run_inner_tests,
        start_follower=_start_log_follower, drain_follower=_drain_log_follower,
        terminate_follower=_terminate_log_follower, stop_outer=_stop_outer,
        export_report=_export_sandbox_report, cleanup_outer=_cleanup_outer,
        verify_snapshot=verify_host_snapshot, write_diagnostic=write_sandbox_diagnostic,
        exact_container_id=EXACT_CONTAINER_ID, set_cleanup_phase=_set_cleanup_phase,
        report_arguments=_sandbox_report_arguments,
        cleanup_error_for=_bounded_cleanup_error,
        transfer_gate=_transfer_gate_request,
    )
