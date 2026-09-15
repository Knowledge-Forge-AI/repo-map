"""Administrative executor and private effective-argv receipts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import os
import subprocess
from typing import Callable, Mapping, Sequence

from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    ProcessBoundaryEvidence,
    ProcessBoundaryRecorder,
)


@dataclass(frozen=True, slots=True)
class AdministrativeReceipt:
    """Public-safe evidence bound to the undisclosed effective command."""

    redacted_argv_shape: tuple[str, ...]
    effective_argv_digest: str
    redaction_manifest: tuple[int, ...]
    host_executable: str
    returncode: int | None
    execution_disposition: str
    shell: bool
    timeout_seconds: int
    process_evidence: ProcessBoundaryEvidence
    disposable_identity_digest: str = ""
    cleanup_contract: str = ""
    cleanup_proved: bool = False
    purpose: str = "qualification_executor_enactment_rehearsal"
    model_rehearsal_only: bool = True
    qualification_status: str = "unqualified"


_PUBLIC_OPTIONS = frozenset(
    {
        "--dry-run",
        "--force",
        "--from-source",
        "--json",
        "--no-stream",
        "--suite",
        "--time",
        "-d",
        "-f",
        "-h",
        "-p",
        "-U",
        "-v",
    }
)


def _redact(argv: Sequence[str]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    redacted: list[str] = []
    manifest: list[int] = []
    preserve_next = False
    for index, value in enumerate(argv):
        if index == 0:
            redacted.append(Path(value).name)
            continue
        if value.startswith("-"):
            redacted.append(value)
            preserve_next = value in {"--suite", "--time", "-v"}
            continue
        if preserve_next:
            redacted.append(value)
            preserve_next = False
            continue
        redacted.append("{redacted}")
        manifest.append(index)
    return tuple(redacted), tuple(manifest)


def _disposition(returncode: int | None, timed_out: bool) -> str:
    if timed_out:
        return "controlled_timeout"
    if returncode == 0:
        return "completed"
    return "controlled_preflight_refusal"


def execute_administrative_operation(
    entry: CatalogEntry,
    effective_argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> AdministrativeReceipt:
    """Execute one frozen K command and bind the command before redaction."""

    if entry.semantic_group != "K":
        raise ValueError("administrative executor requires a Group K entry")
    argv = tuple(str(value) for value in effective_argv)
    if not argv or not argv[0]:
        raise ValueError("effective argv is empty")
    timeout_value = dict(entry.parameter_values)["timeout_seconds"]
    if not isinstance(timeout_value, (int, str)):
        raise TypeError("timeout_seconds must be int or str")
    timeout = int(timeout_value)
    argv_digest = canonical_digest(
        {
            "effective_argv": argv,
            "shell": False,
            "timeout_seconds": timeout,
        }
    )
    redacted, manifest = _redact(argv)
    timed_out = False
    returncode: int | None

    def operation() -> subprocess.CompletedProcess[str] | None:
        nonlocal timed_out, returncode
        try:
            completed = runner(
                list(argv),
                cwd=cwd,
                env=None if environment is None else dict(environment),
                shell=False,
                timeout=timeout,
                check=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
            return None
        returncode = int(completed.returncode)
        return completed

    returncode = None
    _, process_evidence = ProcessBoundaryRecorder().run(operation)
    disposition = _disposition(returncode, timed_out)
    expected = entry.expected_execution_disposition
    if expected is None:
        raise ValueError("Group K entry lacks expected disposition")
    if disposition != expected:
        raise RuntimeError(
            f"administrative disposition mismatch: expected {expected}, got {disposition}"
        )
    return AdministrativeReceipt(
        redacted,
        argv_digest,
        manifest,
        Path(argv[0]).name,
        returncode,
        disposition,
        False,
        timeout,
        process_evidence,
    )


def execute_psql_native_load(
    entry: CatalogEntry,
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
) -> AdministrativeReceipt:
    """K06 structural binding; no host/user/database literal is authoritative."""

    if entry.condition_id != "K06" or Path(str(argv[0])).name != "psql":
        raise ValueError("K06 requires a structural psql command")
    return execute_administrative_operation(
        entry, argv, cwd=cwd, environment=environment
    )


execute_backup = execute_administrative_operation
execute_restore = execute_administrative_operation
execute_schema_migration = execute_administrative_operation
execute_database_initialization = execute_administrative_operation
execute_database_removal = execute_administrative_operation
execute_container_build = execute_administrative_operation
execute_container_start = execute_administrative_operation
execute_container_stop = execute_administrative_operation
execute_container_removal = execute_administrative_operation
execute_test_harness = execute_administrative_operation
execute_docker_stats_diagnostic = execute_administrative_operation


def rehearse_actual_administrative_operation(
    repository_root: Path,
    temp_root: Path,
    entry: CatalogEntry,
) -> AdministrativeReceipt:
    """Run one K case against the predecessor's disposable fixture lifecycle."""

    from repomap_test_support import test_cov5k_r2_fix1_executors as fixture

    captured_argv: tuple[str, ...] | None = None
    captured_cwd = temp_root
    captured_environment: dict[str, str] | None = None
    captured_timeout: subprocess.TimeoutExpired | None = None
    captured_completed: subprocess.CompletedProcess[str] | None = None
    original = fixture._run_k

    def run_actual(
        command: list[str],
        cwd: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        nonlocal captured_argv, captured_cwd, captured_environment
        nonlocal captured_timeout, captured_completed
        environment = dict(environment)
        environment.pop("REPOMAP_TEST_RUN_ROOT", None)
        captured_argv = tuple(command)
        captured_cwd = cwd
        captured_environment = dict(environment)
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                shell=False,
                timeout=10,
                check=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as error:
            captured_timeout = error
            completed = subprocess.CompletedProcess(command, 124, "", "")
        captured_completed = completed
        return completed

    fixture._run_k = run_actual
    ambient_pytest = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        fixture_result, process_evidence = ProcessBoundaryRecorder().run(
            lambda: fixture.execute_group_k(repository_root, temp_root, entry)
        )
    finally:
        fixture._run_k = original
        if ambient_pytest is not None:
            os.environ["PYTEST_CURRENT_TEST"] = ambient_pytest
    argv = captured_argv
    if argv is None:
        raise RuntimeError("administrative fixture did not execute its operation")

    def replay(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if captured_timeout is not None:
            raise captured_timeout
        completed = captured_completed
        if completed is None:
            raise RuntimeError("administrative completion is unavailable")
        return completed

    receipt = execute_administrative_operation(
        entry,
        argv,
        cwd=captured_cwd,
        environment=captured_environment,
        runner=replay,
    )
    fixture_values = dict(fixture_result)
    case_root = temp_root / entry.condition_id
    cleanup_proved = (
        fixture_values.get("cleanup_disposition")
        == "disposable_resource_settled"
        and not case_root.exists()
    )
    if entry.cleanup_contract != "disposable_resource_settled" or not cleanup_proved:
        raise RuntimeError("administrative cleanup contract is not proved")
    disposable_identity_digest = canonical_digest(
        {
            "authority_id": entry.authority_id,
            "case_root_digest": canonical_digest(str(case_root.resolve())),
        }
    )
    return replace(
        receipt,
        process_evidence=process_evidence,
        disposable_identity_digest=disposable_identity_digest,
        cleanup_contract=entry.cleanup_contract,
        cleanup_proved=True,
    )
