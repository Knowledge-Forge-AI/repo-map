"""Sandbox argument rewriting and bounded file transfer helpers for gate requests and D12 proofs."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from test_sandbox_contract import Captured, INNER_REPORT_ROOT, Runner

INNER_GATE_REQUEST_PATH = Path("/run/repomap-gate-request.json")
MAX_GATE_REQUEST_BYTES = 1024 * 1024
INNER_D12_SYSTEM_PROOF_PATH = Path("/run/repomap-d12-system-proof.json")
MAX_D12_SYSTEM_PROOF_BYTES = 16 * 1024


class SandboxArgumentsResult(tuple):
    """Result tuple compatible with (inner_argv, report_destination) unpacking."""

    inner_argv: list[str]
    report_destination: Path | None
    gate_request_bytes: bytes | None
    d12_proof_bytes: bytes | None
    d12_host_proof_path: Path | None

    def __new__(
        cls,
        inner_argv: list[str],
        report_destination: Path | None,
        gate_request_bytes: bytes | None = None,
        d12_proof_bytes: bytes | None = None,
        d12_host_proof_path: Path | None = None,
    ) -> SandboxArgumentsResult:
        res = super().__new__(cls, (inner_argv, report_destination))
        res.inner_argv = inner_argv
        res.report_destination = report_destination
        res.gate_request_bytes = gate_request_bytes
        res.d12_proof_bytes = d12_proof_bytes
        res.d12_host_proof_path = d12_host_proof_path
        return res


def _selected_suite(runner_argv: list[str]) -> str:
    suite = "unit"
    index = 0
    while index < len(runner_argv):
        argument = runner_argv[index]
        if argument == "--suite" and index + 1 < len(runner_argv):
            suite = runner_argv[index + 1]
            index += 2
            continue
        if argument.startswith("--suite="):
            suite = argument.partition("=")[2]
        index += 1
    return suite


def _read_d12_proof_bytes(
    host_proof_path_str: str,
    *,
    repo_root: Path,
    max_proof_bytes: int,
) -> bytes:
    if not host_proof_path_str.strip():
        raise RuntimeError("integration sandbox D12 system proof path is empty")
    raw_path = Path(host_proof_path_str)
    host_path = raw_path if raw_path.is_absolute() else (repo_root / raw_path)
    open_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(host_path, open_flags)
    except FileNotFoundError as error:
        raise RuntimeError(
            f"integration sandbox D12 system proof file not found: {host_path}"
        ) from error
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise RuntimeError(
                f"integration sandbox D12 system proof must not be a symlink: {host_path}"
            ) from error
        raise RuntimeError(
            f"integration sandbox D12 system proof open failed: {error}"
        ) from error
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(
                f"integration sandbox D12 system proof path is not a regular file: {host_path}"
            )
        if hasattr(os, "O_NONBLOCK"):
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        if file_stat.st_size > max_proof_bytes:
            raise RuntimeError(
                "integration sandbox D12 system proof exceeds size limit"
            )
        if file_stat.st_size <= 0:
            raise RuntimeError(
                "integration sandbox D12 system proof file is empty"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(max_proof_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > max_proof_bytes:
        raise RuntimeError("integration sandbox D12 system proof exceeds size limit")
    if not data.strip():
        raise RuntimeError("integration sandbox D12 system proof file is empty")
    try:
        decoded = data.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "integration sandbox D12 system proof is not valid UTF-8 JSON"
        ) from error
    if not isinstance(parsed, dict):
        raise RuntimeError(
            "integration sandbox D12 system proof JSON must be an object"
        )
    return data


def sandbox_report_arguments(
    argv: list[str],
    *,
    repo_root: Path,
    inner_report_root: Path = INNER_REPORT_ROOT,
    inner_gate_request_path: Path = INNER_GATE_REQUEST_PATH,
    max_gate_request_bytes: int = MAX_GATE_REQUEST_BYTES,
    inner_d12_proof_path: Path = INNER_D12_SYSTEM_PROOF_PATH,
    max_d12_proof_bytes: int = MAX_D12_SYSTEM_PROOF_BYTES,
) -> SandboxArgumentsResult:
    forwarded_index = argv.index("--") if "--" in argv else len(argv)
    runner_argv = list(argv[:forwarded_index])
    forwarded = list(argv[forwarded_index:])

    if any(
        tok == "--d12-system-proof-json" or tok.startswith("--d12-system-proof-json=")
        for tok in forwarded[1:]
    ):
        raise RuntimeError("--d12-system-proof-json cannot be passed after '--'")

    suite = _selected_suite(runner_argv)
    gate_request_bytes: bytes | None = None
    d12_proof_bytes: bytes | None = None
    d12_host_proof_path: Path | None = None
    seen_d12_proof = False
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
                raise RuntimeError(
                    f"integration sandbox gate request file not found: {host_path}"
                ) from error
            if not resolved_path.is_file():
                raise RuntimeError(
                    f"integration sandbox gate request path is not a regular file: {host_path}"
                )
            try:
                data = resolved_path.read_bytes()
            except OSError as error:
                raise RuntimeError(
                    f"integration sandbox gate request read failed: {error}"
                ) from error
            if len(data) > max_gate_request_bytes:
                raise RuntimeError(
                    "integration sandbox gate request exceeds size limit"
                )
            if not data.strip():
                raise RuntimeError("integration sandbox gate request file is empty")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RuntimeError(
                    "integration sandbox gate request is not valid UTF-8"
                ) from error
            gate_request_bytes = data
            runner_argv[gate_index] = (
                f"--gate-request-json={inner_gate_request_path}"
                if is_equals
                else runner_argv[gate_index]
            )
            if not is_equals:
                runner_argv[gate_index + 1] = str(inner_gate_request_path)
            gate_index += 1 if is_equals else 2
            continue

        host_proof_path_str: str | None = None
        proof_equals = False
        if arg == "--d12-system-proof-json":
            if seen_d12_proof:
                raise RuntimeError(
                    "duplicate --d12-system-proof-json flag is not allowed"
                )
            if suite != "system":
                raise RuntimeError(
                    "--d12-system-proof-json is only valid with --suite system"
                )
            if gate_index + 1 == len(runner_argv):
                raise RuntimeError(
                    "integration sandbox D12 system proof path is missing"
                )
            host_proof_path_str = runner_argv[gate_index + 1]
        elif arg.startswith("--d12-system-proof-json="):
            if seen_d12_proof:
                raise RuntimeError(
                    "duplicate --d12-system-proof-json flag is not allowed"
                )
            if suite != "system":
                raise RuntimeError(
                    "--d12-system-proof-json is only valid with --suite system"
                )
            host_proof_path_str = arg.partition("=")[2]
            proof_equals = True

        if host_proof_path_str is not None:
            seen_d12_proof = True
            d12_proof_bytes = _read_d12_proof_bytes(
                host_proof_path_str,
                repo_root=repo_root,
                max_proof_bytes=max_d12_proof_bytes,
            )
            raw_proof_path = Path(host_proof_path_str)
            d12_host_proof_path = raw_proof_path if raw_proof_path.is_absolute() else repo_root / raw_proof_path
            runner_argv[gate_index] = (
                f"--d12-system-proof-json={inner_d12_proof_path}"
                if proof_equals
                else runner_argv[gate_index]
            )
            if not proof_equals:
                runner_argv[gate_index + 1] = str(inner_d12_proof_path)
            gate_index += 1 if proof_equals else 2
            continue

        gate_index += 1

    if "--report" not in runner_argv and "--d12-core-image-preflight" not in runner_argv:
        return SandboxArgumentsResult(
            [*runner_argv, *forwarded], None, gate_request_bytes, d12_proof_bytes, d12_host_proof_path
        )

    destination, injected_report_dir, index = Path(".test-reports"), True, 0
    while index < len(runner_argv):
        argument = runner_argv[index]
        if argument == "--report-dir":
            if index + 1 == len(runner_argv):
                raise RuntimeError("integration sandbox report directory is missing")
            destination = Path(runner_argv[index + 1])
            runner_argv[index + 1], injected_report_dir, index = (
                str(inner_report_root),
                False,
                index + 2,
            )
            continue
        if argument.startswith("--report-dir="):
            destination = Path(argument.partition("=")[2])
            runner_argv[index], injected_report_dir = (
                f"--report-dir={inner_report_root}",
                False,
            )
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
    return SandboxArgumentsResult(
        [*runner_argv, *forwarded], destination, gate_request_bytes, d12_proof_bytes, d12_host_proof_path
    )


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


def transfer_system_proof(
    runner: Runner,
    container_id: str,
    payload: bytes,
    *,
    captured: Captured,
    inner_proof_path: Path = INNER_D12_SYSTEM_PROOF_PATH,
) -> None:
    if len(payload) > MAX_D12_SYSTEM_PROOF_BYTES:
        raise RuntimeError("integration sandbox D12 system proof exceeds size limit")
    expected_digest = hashlib.sha256(payload).hexdigest()
    transfer_writer = (
        "import hashlib, os, sys; from pathlib import Path; "
        "data = sys.stdin.read().encode('utf-8'); "
        f"assert hashlib.sha256(data).hexdigest() == {expected_digest!r}; "
        f"p = Path({str(inner_proof_path)!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        "flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0); "
        "fd = os.open(p, flags, 0o600); "
        "os.write(fd, data); os.close(fd)"
    )
    result = captured(
        runner,
        ["docker", "exec", "-i", container_id, "python3", "-I", "-c", transfer_writer],
        input_text=payload.decode("utf-8"),
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("integration sandbox D12 system proof transfer failed")
