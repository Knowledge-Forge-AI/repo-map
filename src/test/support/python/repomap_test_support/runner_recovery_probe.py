"""Controlled inputs for a discovery-only integration fixture, never host evidence."""
from pathlib import Path
import sys
from typing import Any, ClassVar
from unittest.mock import patch
from test_sandbox import active_sandbox

from repomap_test_support.resource_admission import HostSignals, MemoryPressure
from repomap_test_support.resource_hygiene_policy import GIB
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.test_scratch import TestScratchLayout

MISSING_SELECTOR = "src/test/int/python/tools/runner_failure_recovery.int.test.py::test_missing_recovery_probe"


class RecoveryResourceRun(TestResourceRun):
    """Use the existing signal seam while preserving admission and managed state."""

    capacity_available: ClassVar[bool] = True

    @classmethod
    def start(cls, layout: TestScratchLayout, **kwargs: Any) -> TestResourceRun | None:
        if "host_signals" in kwargs:
            raise ValueError("recovery probe refuses conflicting host signals")
        signals = HostSignals(
            free_disk_bytes=200 * GIB if cls.capacity_available else 0,
            free_disk_percent=50 if cls.capacity_available else 0,
            memory_pressure=MemoryPressure.NORMAL,
            docker_responsive=True,
            live_mutating_runs=0,
            operator_attested_exclusive=kwargs.get("operator_attested_exclusive", False),
            operator_attested_pressure_degradation=kwargs.get("operator_attested_pressure_degradation", False),
            campaign_plan_id=kwargs.get("campaign_plan_id"),
            declared_complete_gates=kwargs.get("declared_complete_gates", 0),
        )
        return super().start(layout, host_signals=signals, **kwargs)


def refuse_workload(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("discovery-only recovery probe must never execute tests")


def run_probe(reports: Path, *, capacity_available: bool) -> int:
    """Call the real canonical entrypoint with one deliberately missing node."""
    import run_tests

    if type(capacity_available) is not bool:
        raise ValueError("recovery probe requires an explicit capacity fixture")
    if not active_sandbox():
        raise RuntimeError("recovery probe requires the active integration sandbox")
    with (
        patch.object(RecoveryResourceRun, "capacity_available", capacity_available),
        patch.object(run_tests, "TestResourceRun", RecoveryResourceRun),
        patch.object(run_tests, "run_pytest", refuse_workload),
        patch.object(run_tests, "run_pytest_with_coverage", refuse_workload),
    ):
        return run_tests.main([
            "--suite", "int", "--no-coverage", "--jobs", "1",
            "--report-dir", str(reports), "--", MISSING_SELECTOR,
        ])


def probe_command(repo_root: Path, reports: Path, *, capacity_available: bool) -> list[str]:
    """Construct an argument-vector-only child; caller owns environment isolation."""
    if type(capacity_available) is not bool:
        raise ValueError("recovery probe requires an explicit capacity fixture")
    bootstrap = (
        "import sys; from pathlib import Path; "
        "sys.path[:0]=sys.argv[1:4]; "
        "from repomap_test_support.runner_recovery_probe import run_probe; "
        "raise SystemExit(run_probe(Path(sys.argv[4]), capacity_available=sys.argv[5]=='available'))"
    )
    return [sys.executable, "-B", "-c", bootstrap,
            str(repo_root / "tools"), str(repo_root / "src/main/python"),
            str(repo_root / "src/test/support/python"), str(reports),
            "available" if capacity_available else "unavailable"]
