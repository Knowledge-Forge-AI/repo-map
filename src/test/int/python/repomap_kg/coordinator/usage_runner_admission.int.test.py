"""No-coverage subject tests for the closed measured usage launch boundary.

These tests exercise command admission and adapter refusal with inert doubles;
they do not start a worker, collector, or native process and cannot qualify
hosted M/A measurement.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from runner_coverage_capability import ChildCoverageCapability, CapabilityContainmentError, CapabilityValidationError
from runner_portable_coverage import make_portable_worker_spec_adapter
from runner_usage_command import validate_usage_arguments, validate_usage_probe
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec


class _RefusalSubject(ChildCoverageCapability):
    """Only the pre-registration refusal is exercised; no session is issued."""

    def __init__(self) -> None:
        self.portable_command = ("-m", "common_lore_index.coordinator.portable_worker")
        self.session = object()

    def validate_for_launch(self) -> None:
        return None


def _spec(*args: str) -> WorkerLaunchSpec:
    return WorkerLaunchSpec(
        argv=(sys.executable, "-m", "repomap_test_support.usage_worker", *args),
        environment={"PYTHONPATH": "/support:/main"},
        cwd=Path.cwd(),
    )


def test_usage_adapter_rejects_factory_before_registration() -> None:
    capability = _RefusalSubject()
    adapter = make_portable_worker_spec_adapter(lambda *args, **kwargs: None, capability, capability.session)
    with pytest.raises(CapabilityValidationError, match="injected launch factory"):
        adapter(_spec("--case", "nominal", "--capability", "/cap", "--job-id", "job", "--attempt", "1"), {}, {}, _launch_process=lambda: None, collect_usage=True)


def test_usage_arguments_reject_non_measured_abrupt_cases() -> None:
    args = ("--case", "sigkill", "--capability", "/cap", "--job-id", "job", "--attempt", "1")
    with pytest.raises(CapabilityValidationError, match="not admitted"):
        validate_usage_arguments(args, measured_only=True)


def test_usage_probe_requires_absent_private_leaf(tmp_path: Path) -> None:
    session, manifest, data = (tmp_path / name for name in ("session", "manifest", "data"))
    for root in (session, manifest, data):
        root.mkdir(mode=0o700)
    probe_parent = tmp_path / "private"
    probe_parent.mkdir(mode=0o700)
    probe = validate_usage_probe(
        probe_parent / "witness", case="grandchild-remaining",
        session_dir=session, child_manifest_dir=manifest, data_dir=data,
    )
    assert probe == probe_parent / "witness"
    (probe_parent / "witness").write_text("foreign", encoding="ascii")
    with pytest.raises(CapabilityContainmentError, match="absent"):
        validate_usage_probe(
            probe_parent / "witness", case="grandchild-remaining",
            session_dir=session, child_manifest_dir=manifest, data_dir=data,
        )
