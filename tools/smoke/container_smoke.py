"""Build-free, exact-image container smoke checks for the current checkout."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, TextIO

from repomap_test_support.resource_docker_current import (
    CurrentRunDockerBaselineError,
    CurrentRunDockerCleanupError,
    CurrentRunDockerContainers,
)

from . import is_exact_image_reference
from .lifecycle import SmokeBudget, run_lifecycle


SMOKE_HOME = "/tmp/repomap-smoke-home"
SMOKE_CONFIG_HOME = "/tmp/repomap-smoke-config"
SMOKE_REPOMAP_HOME = f"{SMOKE_HOME}/.repo-map"
SMOKE_WORKSPACE = "/workspace"
SMOKE_PYTHONPATH = f"{SMOKE_WORKSPACE}/src/main/python"
SMOKE_POSTGRES_DATA = "/var/lib/postgresql/data"
SMOKE_DESIGN_TARGET_SECONDS: float = 600.0
SMOKE_WATCHDOG_DEFAULT_SECONDS: int = 900


@dataclass(frozen=True)
class SmokeConfig:
    repo_root: Path
    image_reference: str | None
    psycopg_release_version: str
    timeout_seconds: int = SMOKE_WATCHDOG_DEFAULT_SECONDS
    pg_container_port: int = 55433

    @property
    def source_root(self) -> Path:
        return self.repo_root.resolve() / "src" / "main" / "python"


def _docker_client():
    try:
        import docker
    except ImportError as error:
        raise RuntimeError(
            "Docker SDK is required for --suite smoke; install the scale-tools extra"
        ) from error
    return docker.from_env()


def run_container_smoke(
    config: SmokeConfig,
    *,
    resource_run: Any,
    docker_client_factory: Callable[[], Any] = _docker_client,
    lifecycle_runner: Callable[..., dict[str, Any]] = run_lifecycle,
    clock: Callable[[], float] = time.monotonic,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the bounded RepoMap lifecycle with exactly owned Docker resources."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    if not is_exact_image_reference(config.image_reference):
        print(
            "ERROR: smoke requires an exact local image ID in the form "
            "sha256:<64 lowercase hex>; a mutable tag is not accepted",
            file=stderr,
        )
        return 2
    if resource_run is None or getattr(resource_run, "ledger", None) is None:
        print("ERROR: smoke requires a managed resource run", file=stderr)
        return 2
    if config.timeout_seconds < 1:
        print("ERROR: smoke timeout must be at least 1 second", file=stderr)
        return 2
    if not 1 <= config.pg_container_port <= 65535:
        print("ERROR: smoke PostgreSQL port must be between 1 and 65535", file=stderr)
        return 2
    if not config.source_root.is_dir():
        print(
            f"ERROR: smoke source root is missing: {config.source_root}",
            file=stderr,
        )
        return 2

    client = None
    try:
        client = docker_client_factory()
        client.ping()
        image = client.images.get(config.image_reference)
        if image.id != config.image_reference:
            raise RuntimeError("exact local image ID failed Engine readback")
        containers = CurrentRunDockerContainers(resource_run, client)
    except Exception as error:
        print(f"ERROR: host_admission_refused: {error}", file=stderr)
        if client is not None:
            client.close()
        return 2

    cleanup_error = None
    workload_error = None
    result = 2
    try:
        budget = SmokeBudget(config.timeout_seconds, clock=clock)
        report = lifecycle_runner(config, resource_run, containers, client, budget)
        if report.get("result") != "passed":
            raise RuntimeError("smoke lifecycle did not report a passing result")
        elapsed_seconds = float(report.get("elapsed_seconds", budget.elapsed()))
        if elapsed_seconds >= SMOKE_DESIGN_TARGET_SECONDS:
            warnings = list(report.get("warnings") or [])
            warning_msg = (
                f"Smoke lifecycle elapsed time ({elapsed_seconds:.3f}s) "
                f"exceeded advisory target of {SMOKE_DESIGN_TARGET_SECONDS:.1f}s"
            )
            warnings.append(warning_msg)
            report["warnings"] = warnings
            print(f"WARNING: {warning_msg}", file=stderr)
        report["timing_telemetry"] = {
            "platform": sys.platform,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "advisory_target_seconds": SMOKE_DESIGN_TARGET_SECONDS,
            "target_exceeded": elapsed_seconds >= SMOKE_DESIGN_TARGET_SECONDS,
        }
        _retain_report(resource_run, report)
        result = 0
    except CurrentRunDockerCleanupError as error:
        cleanup_error = error
    except Exception as error:
        workload_error = error

    baseline_error = None
    try:
        containers.verify_baseline()
    except CurrentRunDockerBaselineError as error:
        baseline_error = error
    finally:
        if client is not None:
            client.close()

    if cleanup_error is not None:
        print(f"ERROR: current_run_cleanup_failed: {cleanup_error}", file=stderr)
        return 2
    if baseline_error is not None:
        print(f"ERROR: external_unattributed_mutation: {baseline_error}", file=stderr)
        return 2
    if workload_error is not None:
        print(f"ERROR: container smoke execution failed: {workload_error}", file=stderr)
        return 2

    if result == 0:
        elapsed = float(report.get("elapsed_seconds", 0.0))
        print(f"Smoke suite passed in {elapsed:.3f}s.", file=stdout, flush=True)
        for name, duration in sorted(report.get("step_timings", {}).items()):
            print(f"Smoke timing: {name}={float(duration):.3f}s", file=stdout)
    return result


def _retain_report(resource_run: Any, report: dict[str, Any]) -> None:
    evidence_root = resource_run.layout.run_root / "evidence"
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    report_path = evidence_root / "smoke-lifecycle.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resource_run.retain_evidence(evidence_root, reason="report_source")
