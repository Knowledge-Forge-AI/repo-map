from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from actual_refresh_startup import (
    ActualRefreshStartup,
    StartupChildError,
    StartupReadinessError,
    StartupState,
    wait_for_startup_release,
)
from scale13_actual_refresh_supervisor import start_actual_refresh_child


def _ready(startup: ActualRefreshStartup) -> None:
    startup.mark_storage_baseline_ready()
    startup.mark_backend_observer_ready()
    startup.mark_resource_authorities_ready()
    startup.mark_event_receiver_ready()
    startup.mark_failure_collector_ready()


def _write_probe_product(root: Path) -> None:
    package = root / "repomap_kg"
    package.mkdir()
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    package.joinpath("__main__.py").write_text(
        """from pathlib import Path
import os
import sys

marker = Path(sys.argv[sys.argv.index("--marker") + 1])
descriptor = int(sys.argv[sys.argv.index("--probe-fd") + 1])
try:
    os.fstat(descriptor)
except OSError:
    state = "closed"
else:
    state = "open"
marker.write_text(state, encoding="utf-8")
""",
        encoding="utf-8",
    )


def _probe_arguments(marker: Path, descriptor: int) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "repomap_kg",
        "ops",
        "refresh-graph",
        "--marker",
        str(marker),
        "--probe-fd",
        str(descriptor),
    )


def _start_probe(root: Path, marker: Path, startup: ActualRefreshStartup):
    return start_actual_refresh_child(
        _probe_arguments(marker, startup.child_descriptor),
        inherited_fds=(),
        cwd=root,
        environment={"PYTHONPATH": str(root)},
        startup=startup,
    )


def _settle_probe(process) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=1)


def test_startup_release_requires_every_parent_authority() -> None:
    startup = ActualRefreshStartup.create()
    try:
        assert startup.child_timeout_seconds == 30.0
        with pytest.raises(StartupReadinessError, match="order"):
            startup.release()

        _ready(startup)
        assert startup.state is StartupState.FAILURE_COLLECTOR_READY
    finally:
        startup.close()


def test_startup_release_is_single_use_and_observed_by_child() -> None:
    startup = ActualRefreshStartup.create()
    child_descriptor = os.dup(startup.child_descriptor)
    try:
        startup.child_started()
        _ready(startup)
        startup.release()

        wait_for_startup_release(child_descriptor, timeout_seconds=0.1)
        assert startup.state is StartupState.CHILD_RELEASED
        with pytest.raises(StartupReadinessError, match="order"):
            startup.release()
    finally:
        startup.close()


def test_startup_failure_closes_gate_without_release() -> None:
    startup = ActualRefreshStartup.create()
    child_descriptor = os.dup(startup.child_descriptor)
    try:
        startup.child_started()
        startup.fail()

        with pytest.raises(StartupChildError, match="closed"):
            wait_for_startup_release(child_descriptor, timeout_seconds=0.1)
        assert startup.state is StartupState.FAILED
    finally:
        startup.close()


def test_startup_failure_before_launch_closes_parent_child_descriptor() -> None:
    startup = ActualRefreshStartup.create()
    child_descriptor = startup.child_descriptor

    startup.fail()

    with pytest.raises(OSError):
        os.fstat(child_descriptor)
    assert startup.state is StartupState.FAILED


def test_child_startup_wait_has_a_distinct_bounded_timeout() -> None:
    read_descriptor, write_descriptor = os.pipe()
    try:
        with pytest.raises(StartupChildError, match="timed out"):
            wait_for_startup_release(read_descriptor, timeout_seconds=0.01)
    finally:
        os.close(write_descriptor)


def test_startup_gate_stress_is_deterministic_without_sleep() -> None:
    for _iteration in range(100):
        startup = ActualRefreshStartup.create()
        child_descriptor = os.dup(startup.child_descriptor)
        try:
            startup.child_started()
            _ready(startup)
            startup.release()
            wait_for_startup_release(child_descriptor, timeout_seconds=0.1)
        finally:
            startup.close()


def test_executable_bootstrap_blocks_product_and_closes_gate_before_exec(
    tmp_path,
) -> None:
    _write_probe_product(tmp_path)
    marker = tmp_path / "product-started"
    startup = ActualRefreshStartup.create(child_timeout_seconds=1)
    process = _start_probe(tmp_path, marker, startup)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.05)
        assert not marker.exists()

        _ready(startup)
        startup.release()
        assert process.wait(timeout=1) == 0
        assert marker.read_text(encoding="utf-8") == "closed"
    finally:
        _settle_probe(process)
        startup.close()


def test_executable_bootstrap_gate_close_prevents_product_exec(tmp_path) -> None:
    _write_probe_product(tmp_path)
    marker = tmp_path / "product-started"
    startup = ActualRefreshStartup.create(child_timeout_seconds=1)
    process = _start_probe(tmp_path, marker, startup)
    try:
        startup.fail()
        assert process.wait(timeout=1) != 0
        assert not marker.exists()
    finally:
        _settle_probe(process)
        startup.close()


def test_executable_bootstrap_cleanup_stress(tmp_path) -> None:
    _write_probe_product(tmp_path)
    for iteration in range(25):
        marker = tmp_path / f"product-started-{iteration}"
        startup = ActualRefreshStartup.create(child_timeout_seconds=1)
        process = _start_probe(tmp_path, marker, startup)
        try:
            _ready(startup)
            startup.release()
            assert process.wait(timeout=1) == 0
            assert marker.read_text(encoding="utf-8") == "closed"
        finally:
            _settle_probe(process)
            startup.close()
