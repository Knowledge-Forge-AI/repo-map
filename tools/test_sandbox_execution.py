"""Execution supervision, cleanup, and report handling for the test sandbox."""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
from typing import Callable

from test_sandbox_arguments import (
    INNER_D12_SYSTEM_PROOF_PATH,
    INNER_GATE_REQUEST_PATH,
    MAX_D12_SYSTEM_PROOF_BYTES,
    MAX_GATE_REQUEST_BYTES,
    SandboxArgumentsResult,
    sandbox_report_arguments,
    transfer_gate_request,
    transfer_system_proof,
)
from test_sandbox_contract import (
    Captured,
    HostSnapshot,
    INNER_REPORT_ROOT,
    LogFollower,
    LogFollowerFactory,
    Runner,
    Snapshotter,
)

__all__ = (
    "INNER_D12_SYSTEM_PROOF_PATH",
    "INNER_GATE_REQUEST_PATH",
    "MAX_D12_SYSTEM_PROOF_BYTES",
    "MAX_GATE_REQUEST_BYTES",
    "SandboxArgumentsResult",
    "bounded_cleanup_error",
    "cleanup_outer",
    "drain_log_follower",
    "export_sandbox_report_archive",
    "read_container_report_archive",
    "run_in_sandbox",
    "sandbox_report_arguments",
    "start_log_follower",
    "stop_outer",
    "terminate_log_follower",
    "transfer_gate_request",
    "transfer_system_proof",
)


def start_log_follower(
    follower_factory: LogFollowerFactory, container_id: str
) -> LogFollower:
    try:
        return follower_factory(["docker", "logs", "--follow", container_id])
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            "integration sandbox log follower failed to start"
        ) from error


def terminate_log_follower(follower: LogFollower) -> RuntimeError | None:
    try:
        status = follower.poll()
    except (OSError, subprocess.SubprocessError) as error:
        poll_failure = RuntimeError(
            "integration sandbox log follower state readback failed"
        )
        poll_failure.__cause__ = error
        failure: RuntimeError | None = poll_failure
    else:
        if status is not None:
            return (
                RuntimeError(
                    f"integration sandbox log follower exited with status {status}"
                )
                if status != 0
                else None
            )
        failure = None
    try:
        follower.terminate()
        try:
            follower.wait(timeout=5)
        except subprocess.TimeoutExpired:
            follower.kill()
            follower.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        if failure is None:
            failure = RuntimeError("integration sandbox log follower cleanup failed")
            failure.__cause__ = error
    return failure


def drain_log_follower(
    follower: LogFollower,
    *,
    terminate: Callable[[LogFollower], RuntimeError | None],
) -> RuntimeError | None:
    try:
        status = follower.wait(timeout=60)
    except subprocess.TimeoutExpired:
        if terminate(follower) is not None:
            return RuntimeError(
                "integration sandbox log follower did not drain and cleanup failed"
            )
        return RuntimeError("integration sandbox log follower did not drain")
    except (OSError, subprocess.SubprocessError) as error:
        cleanup_error = terminate(follower)
        message = "integration sandbox log follower readback failed" + (
            " and cleanup failed" if cleanup_error is not None else ""
        )
        failure = RuntimeError(message)
        failure.__cause__ = error
        return failure
    if status != 0:
        return RuntimeError(
            f"integration sandbox log follower exited with status {status}"
        )
    return None


def cleanup_outer(runner: Runner, container_id: str, *, captured: Captured) -> None:
    if captured(runner, ["docker", "rm", "-f", "-v", container_id]).returncode != 0:
        raise RuntimeError("owned integration sandbox removal failed")
    if (
        captured(
            runner, ["docker", "container", "inspect", container_id], timeout=30
        ).returncode
        == 0
    ):
        raise RuntimeError("owned integration sandbox remains after removal")


def stop_outer(runner: Runner, container_id: str, *, captured: Captured) -> None:
    if (
        captured(
            runner, ["docker", "stop", "--time", "10", container_id], timeout=30
        ).returncode
        != 0
    ):
        raise RuntimeError("owned integration sandbox stop failed")


def read_container_report_archive(
    container_id: str,
    required: bool,
    *,
    popen: Callable[..., subprocess.Popen[bytes]],
    inner_report_root: Path = INNER_REPORT_ROOT,
    max_archive_bytes: int,
) -> bytes | None:
    command = ["docker", "cp", f"{container_id}:{inner_report_root}/.", "-"]
    try:
        process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as error:
        raise RuntimeError("integration sandbox report export failed") from error
    archive = bytearray()
    assert process.stdout is not None
    try:
        while chunk := process.stdout.read(64 * 1024):
            archive.extend(chunk)
            if len(archive) > max_archive_bytes:
                process.kill()
                process.wait()
                raise RuntimeError(
                    "integration sandbox report archive exceeds size limit"
                )
        status = process.wait()
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    if status != 0:
        if required:
            raise RuntimeError(
                "integration sandbox report export source is unavailable"
            )
        return None
    return bytes(archive)


def export_sandbox_report_archive(
    archive: bytes,
    destination: Path,
    *,
    exporter: Callable[..., None],
    max_members: int,
    max_content_bytes: int,
) -> None:
    exporter(
        archive,
        destination,
        max_members=max_members,
        max_content_bytes=max_content_bytes,
    )


def bounded_cleanup_error(error: Exception) -> RuntimeError:
    if isinstance(error, RuntimeError):
        return error
    failure = RuntimeError("integration sandbox cleanup I/O failed")
    failure.__cause__ = error
    return failure


def run_in_sandbox(
    argv: list[str],
    *,
    repo_root: Path,
    image_id: str,
    runner: Runner,
    follower_factory: LogFollowerFactory,
    snapshotter: Snapshotter,
    boundary_prover: Callable[..., None],
    archive_reader: Callable[[str, bool], bytes | None],
    captured: Captured,
    outer_run_command: Callable[..., list[str]],
    install_owner_marker: Callable[[Runner, str, str], None],
    wait_for_inner_daemon: Callable[[Runner, str], None],
    prepare_workspace: Callable[[Runner, str], None],
    prepare_images: Callable[[Runner, str], None],
    bind_capacity: Callable[..., None],
    effective_timeout: Callable[[float], float],
    run_inner_tests: Callable[[Runner, str], int],
    start_follower: Callable[[LogFollowerFactory, str], LogFollower],
    drain_follower: Callable[[LogFollower], RuntimeError | None],
    terminate_follower: Callable[[LogFollower], RuntimeError | None],
    stop_outer: Callable[[Runner, str], None],
    export_report: Callable[[bytes, Path], None],
    cleanup_outer: Callable[[Runner, str], None],
    verify_snapshot: Callable[[HostSnapshot, HostSnapshot], None],
    write_diagnostic: Callable[[str], None],
    exact_container_id: re.Pattern[str],
    set_cleanup_phase: Callable[[bool], None],
    report_arguments: Callable[..., tuple[list[str], Path | None]],
    cleanup_error_for: Callable[[Exception], RuntimeError],
    transfer_gate: Callable[[Runner, str, bytes], None] | None = None,
    transfer_proof: Callable[[Runner, str, bytes], None] | None = None,
) -> int:
    set_cleanup_phase(False)
    arguments_result = report_arguments(argv, repo_root=repo_root)
    inner_argv, report_destination = arguments_result
    gate_request_bytes = getattr(arguments_result, "gate_request_bytes", None)
    d12_proof_bytes = getattr(arguments_result, "d12_proof_bytes", None)
    d12_host_proof_path = getattr(arguments_result, "d12_host_proof_path", None)
    marker_token = secrets.token_hex(32)
    container_name = f"repomap-test-sandbox-{secrets.token_hex(8)}"
    before = snapshotter(runner)
    container_id: str | None = None
    log_follower: LogFollower | None = None
    exit_code = 2
    cleanup_error: RuntimeError | None = None
    logging_error: RuntimeError | None = None
    setup_error: BaseException | None = None
    outer_stopped = False

    def interrupt_for_termination(_signum, _frame) -> None:
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_for_termination)
    try:
        result = captured(
            runner,
            outer_run_command(
                image_id=image_id,
                container_name=container_name,
                repo_root=repo_root,
                host_gid=os.getgid(),
                argv=inner_argv,
            ),
            timeout=120,
        )
        candidate = result.stdout.strip()
        if result.returncode != 0 or exact_container_id.fullmatch(candidate) is None:
            raise RuntimeError(
                "owned integration sandbox did not return an exact container ID"
            )
        container_id = candidate
        install_owner_marker(runner, container_id, marker_token)
        log_follower = start_follower(follower_factory, container_id)
        wait_for_inner_daemon(runner, container_id)
        prepare_workspace(runner, container_id)
        if gate_request_bytes is not None:
            if transfer_gate is not None:
                transfer_gate(runner, container_id, gate_request_bytes)
            else:
                transfer_gate_request(
                    runner, container_id, gate_request_bytes, captured=captured
                )
        if d12_proof_bytes is not None:
            if transfer_proof is not None:
                transfer_proof(runner, container_id, d12_proof_bytes)
            else:
                transfer_system_proof(
                    runner, container_id, d12_proof_bytes, captured=captured
                )
        prepare_images(runner, container_id)
        boundary_prover(runner, container_id=container_id, token=secrets.token_hex(8))
        bind_capacity(
            runner, container_id, marker_token, timeout_limit=effective_timeout
        )
        exit_code = run_inner_tests(runner, container_id)
        outer_stopped = True
        logging_error = drain_follower(log_follower)
        log_follower = None
    except KeyboardInterrupt:
        exit_code = 130
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        setup_error = error
        exit_code = 2
    finally:
        set_cleanup_phase(True)
        stop_error: RuntimeError | None = None
        if container_id is not None and not outer_stopped:
            try:
                stop_outer(runner, container_id)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                stop_error = cleanup_error = cleanup_error_for(error)
        if log_follower is not None:
            follower_error = (
                drain_follower(log_follower)
                if stop_error is None
                else terminate_follower(log_follower)
            )
            if logging_error is None:
                logging_error = follower_error
        if (
            report_destination is not None
            and container_id is not None
            and stop_error is None
        ):
            try:
                report_required = setup_error is None and exit_code == 0
                archive = archive_reader(container_id, report_required)
                if archive is None and report_required:
                    raise RuntimeError(
                        "integration sandbox report export source is unavailable"
                    )
                if archive is not None:
                    expected_manifest = None
                    if report_required and d12_proof_bytes is not None:
                        from tools.system.d12_export_manifest import retain_host_manifest

                        if d12_host_proof_path is None:
                            raise RuntimeError("D12 host proof origin is unavailable")
                        expected_manifest = retain_host_manifest(archive, expected_proof_bytes=d12_proof_bytes,
                                                                 host_proof_path=d12_host_proof_path)
                    export_report(archive, report_destination)
                    if report_required and d12_proof_bytes is not None:
                        try:
                            from tools.system.d12_qualification_export import verify_exported_qualification

                            if expected_manifest is None:
                                raise RuntimeError("D12 host export manifest is unavailable")
                            verify_exported_qualification(report_destination, repo_root=repo_root,
                                expected_proof_bytes=d12_proof_bytes, expected_export_manifest_bytes=expected_manifest)
                        except Exception as error:
                            raise RuntimeError("D12 exported qualification verification failed") from error
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = cleanup_error_for(error)
        if container_id is not None:
            try:
                cleanup_outer(runner, container_id)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                if cleanup_error is None:
                    cleanup_error = cleanup_error_for(error)
        try:
            verify_snapshot(before, snapshotter(runner))
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            if cleanup_error is None:
                cleanup_error = cleanup_error_for(error)
        signal.signal(signal.SIGTERM, previous_sigterm)
        set_cleanup_phase(False)
    for err, label in (
        (setup_error, "failed"),
        (cleanup_error, "cleanup failed"),
        (logging_error, "logging failed"),
    ):
        if err is not None:
            write_diagnostic(f"integration sandbox {label}: {err}")
    if exit_code == 0 and (cleanup_error is not None or logging_error is not None):
        return 2
    return exit_code
