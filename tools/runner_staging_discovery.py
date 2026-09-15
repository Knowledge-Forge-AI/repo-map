"""Invocation-owned isolated population collection; no measurement authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from repomap_test_support.test_scratch import establish_run
from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS, validate_declarations
from runner_integration_population import SealedPopulationPartition, partition_population
from runner_staging_discovery_contract import (
    DISCOVERY_RECEIPT_SCHEMA as DISCOVERY_RECEIPT_SCHEMA,
    MAX_RECEIPT_BYTES as MAX_RECEIPT_BYTES,
    PopulationDiscoveryError as PopulationDiscoveryError,
    REQUEST_SCHEMA, discovery_failure_detail, validate_discovery_receipt, validate_request, write_document,
)

# Discovery has no inherited runner deadline. This fixed bound plus the two
# five-second settlement windows is independent of hosted suite qualification.
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 120.0


def filter_child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Pass test-owned inputs, tool lookup and sandbox admission, not bootstrap."""
    exact = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TMP", "TEMP",
             "REPOMAP_GO_HELPER", "DOCKER_HOST",
             "DOCKER_CONFIG", "DOCKER_CONTEXT", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
             "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    return {key: value for key, value in environ.items()
            if key in exact or key.startswith(("REPOMAP_TEST_", "_REPOMAP_TEST_SANDBOX_"))}


def _group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True


def terminate_and_reap(process: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    """Settle the exact group created for this discovery, including descendants."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        deadline = time.monotonic() + timeout
        if _group_exists(process.pid):
            os.killpg(process.pid, sig)
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            continue
        while _group_exists(process.pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        if not _group_exists(process.pid):
            return
    raise PopulationDiscoveryError("discovery process group cleanup is unproved")


def _python_paths(source_root: Path, support_root: Path, repo_root: Path) -> list[str]:
    # Copy the caller's effective order, including canonical runtime insertions.
    # Known inherited Coverage bootstrap roots must not run at child startup.
    bootstrap = {str(Path(os.environ[key]).resolve().parent)
                 for key in ("COVERAGE_PROCESS_START", "COVERAGE_CHILD_MANIFEST_DIR")
                 if os.environ.get(key)}
    paths = [str(Path(path or os.getcwd()).resolve()) for path in sys.path]
    for path in (source_root, support_root, repo_root / "tools", repo_root):
        if str(path) not in paths:
            paths.insert(0, str(path))
    return list(dict.fromkeys(path for path in paths if path not in bootstrap))


def discover_staging_population(
    args: Any, pytest_args: Sequence[str], *, repo_root: Path, source_root: Path,
    test_support_root: Path, invocation_id: str, candidate_identity: dict[str, str],
    scoped: bool, timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    child_script_path: Path | None = None, declarations=MAINTAINED_ABRUPT_DECLARATIONS,
) -> SealedPopulationPartition:
    """Seal one exact collection from a bounded child; never retry discovery."""
    if not 0 < timeout_seconds <= DEFAULT_DISCOVERY_TIMEOUT_SECONDS:
        raise PopulationDiscoveryError("invalid discovery timeout")
    declarations = tuple(declarations)
    validate_declarations(declarations)
    environment = filter_child_environment(os.environ)
    request = {
        "schema": REQUEST_SCHEMA, "invocation_id": invocation_id,
        "candidate": dict(candidate_identity), "suite": args.suite, "scoped": scoped,
        "pytest_args": list(pytest_args), "cwd": str(repo_root.resolve()),
        "python_paths": _python_paths(source_root, test_support_root, repo_root),
        "declarations": [asdict(item) for item in declarations], "environment": environment,
    }
    validate_request(request)
    script = child_script_path or Path(__file__).with_name("runner_staging_discovery_child.py")
    # An admitted canonical invocation already owns this root. No scratch
    # admission failure is converted into a fallback temporary authority.
    with tempfile.TemporaryDirectory(prefix="discovery-", dir=establish_run().tmp) as raw:
        root = Path(raw)
        request_path, receipt_path = root / "request.json", root / "receipt.json"
        write_document(request_path, request)
        command = [sys.executable, "-I", str(script), str(request_path), str(receipt_path)]
        process = subprocess.Popen(command, cwd=repo_root, env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            try:
                code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                raise PopulationDiscoveryError("discovery child timed out") from error
            if code != 0:
                detail = discovery_failure_detail(receipt_path, request=request, exit_code=code)
                raise PopulationDiscoveryError(f"discovery child failed with exit {code}; {detail}")
            receipt = validate_discovery_receipt(receipt_path, request=request)
            partition = partition_population(
                receipt["eligible"], declarations=declarations, suite=args.suite, scoped=scoped,
                collected_nodes=receipt["collected"], deferred_nodes=receipt["deferred"],
            )
        finally:
            terminate_and_reap(process)
        return partition
