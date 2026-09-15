"""Fixed complete-gate, selection, and exact-pytest executor contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import Mapping, Sequence

from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidence


@dataclass(frozen=True, slots=True)
class RunnerManifest:
    argv_shape: tuple[str, ...]
    environment_class: str
    timeout_seconds: int
    returncode: int | None
    passed_count: int
    skipped_count: int
    coverage_line: str | None
    cleanup_complete: bool
    disposition: str
    run_id: str | None
    failure_nodes: tuple[str, ...]
    smoke_passed: bool


_COUNTS = re.compile(r"(?P<passed>\d+) passed(?:, (?P<skipped>\d+) skipped)?")
_RUN_ID = re.compile(r"^Test run: (?P<run_id>t[0-9a-f]+) ", re.MULTILINE)
_FAILED_NODE = re.compile(r"FAILED (?P<node>[^\s]+)")


def _cleanup_complete(output: str, environment: Mapping[str, str]) -> tuple[str | None, bool]:
    matches = tuple(_RUN_ID.finditer(output))
    if not matches:
        return None, False
    run_id = matches[0].group("run_id")
    scratch_root = Path(environment.get("REPOMAP_TEST_SCRATCH_ROOT", "/Users/Shared/agent-scratch"))
    manifest_path = scratch_root / "r" / run_id / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return run_id, False
    return run_id, bool(
        manifest.get("state") == "passed"
        and manifest.get("exit_status") == 0
        and manifest.get("live_runtime_residue") is False
    )


def _run(
    argv: Sequence[str],
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    environment_class: str,
) -> RunnerManifest:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=repository_root,
            env=dict(environment),
            shell=False,
            timeout=timeout_seconds,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as error:
        output = str(error.stdout or "") + str(error.stderr or "")
        returncode = None
        disposition = "controlled_timeout"
    else:
        output = completed.stdout + completed.stderr
        returncode = completed.returncode
        disposition = "completed" if returncode == 0 else "controlled_refusal"
    match = _COUNTS.search(output)
    coverage = next(
        (line.strip() for line in output.splitlines() if "aggregate line coverage:" in line),
        None,
    )
    run_id, cleanup_complete = _cleanup_complete(output, environment)
    failure_nodes = tuple(dict.fromkeys(match.group("node") for match in _FAILED_NODE.finditer(output)))
    return RunnerManifest(
        (Path(argv[0]).name, *tuple(argv[1:])),
        environment_class,
        timeout_seconds,
        returncode,
        0 if match is None else int(match.group("passed")),
        0 if match is None or match.group("skipped") is None else int(match.group("skipped")),
        coverage,
        cleanup_complete,
        disposition,
        run_id,
        failure_nodes,
        "Smoke suite passed." in output,
    )


def execute_complete_gate(
    entry: CatalogEntry,
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    postgres_port: int,
) -> ExecutorEvidence:
    manifest = _run(
        (
            sys.executable,
            "tools/run_tests.py",
            "--suite",
            "staging",
            "--pg-container-port",
            str(postgres_port),
        ),
        repository_root=repository_root,
        environment=environment,
        timeout_seconds=1_800,
        environment_class="capable_isolated_cpython313",
    )
    if manifest.returncode != 0 or not manifest.cleanup_complete or not manifest.smoke_passed:
        nodes = ", ".join(manifest.failure_nodes) or "runner-or-smoke failure"
        raise RuntimeError(f"complete-gate executor rehearsal failed: {nodes}")
    observed = (
        ("primary_result_category", "passed"),
        ("runner_manifest", manifest),
    )
    return ExecutorEvidence(entry.authority_id, True, entry.parameter_values, observed)


def execute_focused_selection(
    entry: CatalogEntry,
    *,
    repository_root: Path,
    environment: Mapping[str, str],
) -> ExecutorEvidence:
    node = str(dict(entry.parameter_values)["pytest_node_id"])
    manifest = _run(
        (
            sys.executable,
            "tools/run_tests.py",
            "--suite",
            "unit",
            "--no-coverage",
            "--",
            node,
        ),
        repository_root=repository_root,
        environment=environment,
        timeout_seconds=300,
        environment_class="capable_isolated_cpython313",
    )
    if manifest.returncode != 0 or not manifest.cleanup_complete:
        raise RuntimeError("focused-selection executor rehearsal failed")
    return ExecutorEvidence(
        entry.authority_id,
        True,
        entry.parameter_values,
        (("primary_result_category", "passed"), ("runner_manifest", manifest)),
    )


def execute_former_failure_node(
    entry: CatalogEntry,
    *,
    repository_root: Path,
    environment: Mapping[str, str],
) -> ExecutorEvidence:
    if entry.pytest_node_id is None:
        raise ValueError("former-failure executor lacks an exact pytest node")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    manifest = _run(
        (
            sys.executable,
            "tools/run_tests.py",
            "--suite",
            "int",
            "--no-coverage",
            "--pg-container-port",
            str(port),
            "--",
            entry.pytest_node_id,
        ),
        repository_root=repository_root,
        environment=environment,
        timeout_seconds=300,
        environment_class="capable_isolated_cpython313",
    )
    if manifest.returncode != 0 or not manifest.cleanup_complete:
        raise RuntimeError("former-failure node failed")
    return ExecutorEvidence(
        entry.authority_id,
        True,
        entry.parameter_values,
        (("primary_result_category", "source_category_preserved"), ("runner_manifest", manifest)),
    )
