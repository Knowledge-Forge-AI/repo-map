"""Shared helpers for resource-report file custody and observed CLI-child proofs.

New canonical ``-m common_lore_index`` children use the existing observed launch
helper with the ``cli_module`` family, shared PID namespace registration and an
explicit bounded timeout, so measurement registration is preserved.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from common_lore_index.ops.resource_reports._codec import decode_report
from common_lore_index.ops.resource_reports._files import read_report_file

CLI_CHILD_TIMEOUT_SECONDS = 300
TEMP_PREFIX = ".cloe-resource-report-"


def private_directory(path: Path) -> Path:
    """Create (test setup only) an owner-only report directory."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def report_payload(
    path: Path,
    *,
    operation: str,
    backend: str | None,
    outcome: str,
    instrumentation: str | None = None,
    forbidden: Iterable[object] = (),
) -> dict[str, Any]:
    """Read one delivered report through the product reader and check custody."""
    details = os.lstat(path)
    assert stat.S_ISREG(details.st_mode), details
    assert stat.S_IMODE(details.st_mode) == 0o600, oct(details.st_mode)
    assert details.st_uid == os.geteuid()
    data = read_report_file(path)
    assert data.endswith(b"\n") and data.count(b"\n") == 1, data
    payload = decode_report(data).to_payload()
    assert (payload["operation"], payload["backend"], payload["outcome"]) == (
        operation, backend, outcome,
    ), payload
    if instrumentation is not None:
        assert payload["instrumentation"] == instrumentation, payload
    text = data.decode("utf-8")
    for item in forbidden:
        if item:
            assert str(item) not in text, "report retained an identity or path"
    return payload


def metric(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in payload["metrics"] if item["name"] == name)


def limit(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in payload["limits"] if item["name"] == name)


def report_leftovers(directory: Path) -> list[str]:
    """Temporary names a delivery left behind in ``directory``."""
    return sorted(name for name in os.listdir(directory) if name.startswith(TEMP_PREFIX))


def run_cloe(
    *args: str, cwd: Path, extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one canonical CLI child under the shared measurement registration."""
    from runner_coverage_observer import launch_observed_process

    from repomap_test_support.cli_in_process import module_process_environment

    return launch_observed_process(
        [sys.executable, "-m", "common_lore_index", *args],
        family="cli_module",
        cwd=cwd,
        env=module_process_environment(extra_env=dict(extra_env or {})),
        pid_namespace_relation="shared",
        timeout=CLI_CHILD_TIMEOUT_SECONDS,
    )


__all__ = (
    "CLI_CHILD_TIMEOUT_SECONDS", "TEMP_PREFIX", "limit", "metric", "private_directory",
    "report_leftovers", "report_payload", "run_cloe",
)
