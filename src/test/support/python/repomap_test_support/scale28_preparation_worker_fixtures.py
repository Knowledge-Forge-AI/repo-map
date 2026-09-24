"""Public-safe spawn-importable fixtures for preparation-worker tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scale28_preparation_values import ResourceBaseline
from runner_coverage_execution import prepare_child_coverage_environment


@dataclass(slots=True)
class SyntheticPreparedResources:
    baseline: ResourceBaseline
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def prepare_synthetic_resources(_specification) -> SyntheticPreparedResources:
    return SyntheticPreparedResources(
        ResourceBaseline(
            schema_version=1,
            client_peak_rss_bytes=64_000_000,
            postgresql_container_rss_upper_bound=96_000_000,
            temporary_byte_upper_bound_delta=0,
            wal_upper_bound_delta=4_096,
            allocated_delta_bytes=8_192,
            backing_free_bytes=4_000_000_000,
            pgdata_reader_elapsed_ns=1_000_000,
            availability="available",
        )
    )


def fail_synthetic_resources(_specification):
    raise RuntimeError("synthetic preparation failure")


def _rebuild_slow_bootstrap_preparer(delay_seconds: float):
    # Runs while the child unpickles spawn arguments, so the cost lands in the
    # bootstrap interval, strictly before the worker signals readiness.
    time.sleep(delay_seconds)
    return SlowBootstrapPreparer(delay_seconds)


class SlowBootstrapPreparer:
    """Charge deliberate cost to child bootstrap rather than to preparation."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    def __call__(self, specification) -> SyntheticPreparedResources:
        return prepare_synthetic_resources(specification)

    def __reduce__(self):
        return (_rebuild_slow_bootstrap_preparer, (self.delay_seconds,))


class SlowSemanticPreparer:
    """Charge deliberate cost to the semantic operation after readiness."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    def __call__(self, specification) -> SyntheticPreparedResources:
        time.sleep(self.delay_seconds)
        return prepare_synthetic_resources(specification)


def exit_with_synthetic_descendant(specification) -> None:
    """Crash the worker leader after creating one same-group descendant."""

    descendant = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os, time; print(os.getpid(), flush=True); time.sleep(60)",
        ],
        close_fds=True,
        stdout=subprocess.PIPE,
        env=prepare_child_coverage_environment(family="unmeasured"),
    )
    assert descendant.stdout is not None
    ready = descendant.stdout.readline().decode("ascii").strip()
    descendant.stdout.close()
    Path(specification.pgdata_root, "descendant.launch.json").write_text(
        json.dumps({"leader_pid": os.getpid(), "descendant_pid": descendant.pid,
                    "process_group": os.getpgid(descendant.pid), "ready": ready}),
        encoding="ascii",
    )
    Path(specification.pgdata_root, "descendant.pid").write_text(
        str(descendant.pid),
        encoding="ascii",
    )
    os._exit(17)


__all__ = [
    "exit_with_synthetic_descendant",
    "fail_synthetic_resources",
    "prepare_synthetic_resources",
    "SlowBootstrapPreparer",
    "SlowSemanticPreparer",
]
