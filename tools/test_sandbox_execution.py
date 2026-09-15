"""Execution supervision, cleanup, and report handling for the test sandbox."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
from typing import Callable

from test_sandbox_contract import (
    Captured,
    HostSnapshot,
    INNER_REPORT_ROOT,
    LogFollower,
    LogFollowerFactory,
    Runner,
    Snapshotter,
)


def start_log_follower(follower_factory: LogFollowerFactory, container_id: str) -> LogFollower:
    try:
        return follower_factory(["docker", "logs", "--follow", container_id])
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("integration sandbox log follower failed to start") from error


def terminate_log_follower(follower: LogFollower) -> RuntimeError | None:
    try:
        status = follower.poll()
    except (OSError, subprocess.SubprocessError) as error:
        poll_failure = RuntimeError("integration sandbox log follower state readback failed")
        poll_failure.__cause__ = error
        failure: RuntimeError | None = poll_failure
    else:
        if status is not None:
            return RuntimeError(f"integration sandbox log follower exited with status {status}") if status != 0 else None
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
            return RuntimeError("integration sandbox log follower did not drain and cleanup failed")
        return RuntimeError("integration sandbox log follower did not drain")
    except (OSError, subprocess.SubprocessError) as error:
        cleanup_error = terminate(follower)
        message = "integration sandbox log follower readback failed" + (" and cleanup failed" if cleanup_error is not None else "")
        failure = RuntimeError(message)
        failure.__cause__ = error
        return failure
    if status != 0:
        return RuntimeError(f"integration sandbox log follower exited with status {status}")
    return None


def cleanup_outer(runner: Runner, container_id: str, *, captured: Captured) -> None:
    if captured(runner, ["docker", "rm", "-f", "-v", container_id]).returncode != 0:
        raise RuntimeError("owned integration sandbox removal failed")
    if captured(runner, ["docker", "container", "inspect", container_id], timeout=30).returncode == 0:
        raise RuntimeError("owned integration sandbox remains after removal")


def stop_outer(runner: Runner, container_id: str, *, captured: Captured) -> None:
    if captured(runner, ["docker", "stop", "--time", "10", container_id], timeout=30).returncode != 0:
        raise RuntimeError("owned integration sandbox stop failed")


INNER_GATE_REQUEST_PATH = Path("/run/repomap-gate-request.json")
MAX_GATE_REQUEST_BYTES = 1024 * 1024


class SandboxArgumentsResult(tuple):
    """Result tuple compatible with (inner_argv, report_destination) unpacking."""

    inner_argv: list[str]
    report_destination: Path | None
    gate_request_bytes: bytes | None

    def __new__(
        cls,
        inner_argv: list[str],
        report_destination: Path | None,
        gate_request_bytes: bytes | None = None,
    ) -> SandboxArgumentsResult:
        res = super().__new__(cls, (inner_argv, report_destination))
        res.inner_argv = inner_argv
        res.report_destination = report_destination
        res.gate_request_bytes = gate_request_bytes
        return res


def sandbox_report_arguments(
    argv: list[str],
    *,
    repo_root: Path,
    inner_report_root: Path = INNER_REPORT_ROOT,
    inner_gate_request_path: Path = INNER_GATE_REQUEST_PATH,
    max_gate_request_bytes: int = MAX_GATE_REQUEST_BYTES,
) -> SandboxArgumentsResult:
    forwarded_index = argv.index("--") if "--" in argv else len(argv)
    runner_argv = list(argv[:forwarded_index])
    forwarded = list(argv[forwarded_index:])

    gate_request_bytes: bytes | None = None
    gate_index = 0
    while gate_index < len(runner_argv):
        arg = runner_argv[gate_index]
        host_req_path_str: str | None = None
        is_equals = False
        if arg == "--gate-request-json":
            if gate_index + 1 == len(runner_argv):
                raise RuntimeError("integration sandbox gate request path is missing")
            host_req_path_str = runner_argv[gate_index + 1]
        elif arg.startswith("--gate-request-json="):
            host_req_path_str = arg.partition("=")[2]
            is_equals = True

        if host_req_path_str is not None:
            if not host_req_path_str.strip():
                raise RuntimeError("integration sandbox gate request path is empty")
            raw_path = Path(host_req_path_str)
            host_path = raw_path if raw_path.is_absolute() else (repo_root / raw_path)
            try:
                resolved_path = host_path.resolve(strict=True)
            except (OSError, ValueError) as error:
                raise RuntimeError(f"integration sandbox gate request file not found: {host_path}") from error
            if not resolved_path.is_file():
                raise RuntimeError(f"integration sandbox gate request path is not a regular file: {host_path}")
            try:
                data = resolved_path.read_bytes()
            except OSError as error:
                raise RuntimeError(f"integration sandbox gate request read failed: {error}") from error
            if len(data) > max_gate_request_bytes:
                raise RuntimeError("integration sandbox gate request exceeds size limit")
            if not data.strip():
                raise RuntimeError("integration sandbox gate request file is empty")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RuntimeError("integration sandbox gate request is not valid UTF-8") from error
            gate_request_bytes = data
            runner_argv[gate_index] = f"--gate-request-json={inner_gate_request_path}" if is_equals else runner_argv[gate_index]
            if not is_equals:
                runner_argv[gate_index + 1] = str(inner_gate_request_path)
            gate_index += 1 if is_equals else 2
            continue
        gate_index += 1

    if "--report" not in runner_argv:
        return SandboxArgumentsResult([*runner_argv, *forwarded], None, gate_request_bytes)

    destination, injected_report_dir, index = Path(".test-reports"), True, 0
    while index < len(runner_argv):
        argument = runner_argv[index]
        if argument == "--report-dir":
            if index + 1 == len(runner_argv):
                raise RuntimeError("integration sandbox report directory is missing")
            destination = Path(runner_argv[index + 1])
            runner_argv[index + 1], injected_report_dir, index = str(inner_report_root), False, index + 2
            continue
        if argument.startswith("--report-dir="):
            destination = Path(argument.partition("=")[2])
            runner_argv[index], injected_report_dir = f"--report-dir={inner_report_root}", False
        index += 1
    if injected_report_dir:
        runner_argv.extend(("--report-dir", str(inner_report_root)))
    if not destination.is_absolute():
        destination = repo_root / destination
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(
            f"integration sandbox report destination {destination} already exists; "
            "specify an unused destination with --report-dir"
        )
    return SandboxArgumentsResult([*runner_argv, *forwarded], destination, gate_request_bytes)


def transfer_gate_request(
    runner: Runner,
    container_id: str,
    payload: bytes,
    *,
    captured: Captured,
    inner_gate_request_path: Path = INNER_GATE_REQUEST_PATH,
) -> None:
    expected_digest = hashlib.sha256(payload).hexdigest()
    transfer_writer = (
        "import hashlib, os, sys; from pathlib import Path; "
        "data = sys.stdin.read().encode('utf-8'); "
        f"assert hashlib.sha256(data).hexdigest() == {expected_digest!r}; "
        f"p = Path({str(inner_gate_request_path)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_bytes(data); os.chmod(p, 0o400)"
    )
    result = captured(
        runner,
        ["docker", "exec", "-i", container_id, "python3", "-c", transfer_writer],
        input_text=payload.decode("utf-8"),
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("integration sandbox gate request transfer failed")


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
                raise RuntimeError("integration sandbox report archive exceeds size limit")
        status = process.wait()
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    if status != 0:
        if required:
            raise RuntimeError("integration sandbox report export source is unavailable")
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
    exporter(archive, destination, max_members=max_members, max_content_bytes=max_content_bytes)


def bounded_cleanup_error(error: Exception) -> RuntimeError:
    if isinstance(error, RuntimeError):
        return error
    failure = RuntimeError("integration sandbox cleanup I/O failed")
    failure.__cause__ = error
    return failure


def run_in_sandbox(
    argv: list[str],
    *,
    repo_root: Path, image_id: str, runner: Runner, follower_factory: LogFollowerFactory,
    snapshotter: Snapshotter, boundary_prover: Callable[..., None],
    archive_reader: Callable[[str, bool], bytes | None], captured: Captured,
    outer_run_command: Callable[..., list[str]], install_owner_marker: Callable[[Runner, str, str], None],
    wait_for_inner_daemon: Callable[[Runner, str], None], prepare_workspace: Callable[[Runner, str], None],
    prepare_images: Callable[[Runner, str], None], bind_capacity: Callable[..., None],
    effective_timeout: Callable[[float], float], run_inner_tests: Callable[[Runner, str], int],
    start_follower: Callable[[LogFollowerFactory, str], LogFollower],
    drain_follower: Callable[[LogFollower], RuntimeError | None],
    terminate_follower: Callable[[LogFollower], RuntimeError | None],
    stop_outer: Callable[[Runner, str], None], export_report: Callable[[bytes, Path], None],
    cleanup_outer: Callable[[Runner, str], None], verify_snapshot: Callable[[HostSnapshot, HostSnapshot], None],
    write_diagnostic: Callable[[str], None], exact_container_id: re.Pattern[str],
    set_cleanup_phase: Callable[[bool], None], report_arguments: Callable[..., tuple[list[str], Path | None]],
    cleanup_error_for: Callable[[Exception], RuntimeError],
    transfer_gate: Callable[[Runner, str, bytes], None] | None = None,
) -> int:
    set_cleanup_phase(False)
    arguments_result = report_arguments(argv, repo_root=repo_root)
    inner_argv, report_destination = arguments_result
    gate_request_bytes = getattr(arguments_result, "gate_request_bytes", None)
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
            raise RuntimeError("owned integration sandbox did not return an exact container ID")
        container_id = candidate
        install_owner_marker(runner, container_id, marker_token)
        log_follower = start_follower(follower_factory, container_id)
        wait_for_inner_daemon(runner, container_id)
        prepare_workspace(runner, container_id)
        if gate_request_bytes is not None:
            if transfer_gate is not None:
                transfer_gate(runner, container_id, gate_request_bytes)
            else:
                transfer_gate_request(runner, container_id, gate_request_bytes, captured=captured)
        prepare_images(runner, container_id)
        boundary_prover(runner, container_id=container_id, token=secrets.token_hex(8))
        bind_capacity(runner, container_id, marker_token, timeout_limit=effective_timeout)
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
            follower_error = drain_follower(log_follower) if stop_error is None else terminate_follower(log_follower)
            if logging_error is None:
                logging_error = follower_error
        if report_destination is not None and container_id is not None and stop_error is None:
            try:
                report_required = setup_error is None and exit_code == 0
                archive = archive_reader(container_id, report_required)
                if archive is None and report_required:
                    raise RuntimeError("integration sandbox report export source is unavailable")
                if archive is not None:
                    export_report(archive, report_destination)
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
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
    for err, label in ((setup_error, "failed"), (cleanup_error, "cleanup failed"), (logging_error, "logging failed")):
        if err is not None:
            write_diagnostic(f"integration sandbox {label}: {err}")
    if exit_code == 0 and (cleanup_error is not None or logging_error is not None):
        return 2
    return exit_code
