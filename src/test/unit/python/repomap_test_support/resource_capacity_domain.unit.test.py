"""PR26-STAGING-FIX2 capacity-domain regression with injected measurements."""

from pathlib import Path
from types import SimpleNamespace

from repomap_test_support import resource_admission as admission
from repomap_test_support.resource_hygiene_policy import (
    GIB,
    HygieneConfig,
    HygieneProfile,
)
import test_sandbox
import test_sandbox_capacity as capacity
import pytest


@pytest.mark.parametrize("backing_free,expected", [(200 * GIB, "True"), (GIB, "False")])
def test_new_nested_process_can_admit_late_but_uses_current_backing(
    tmp_path, backing_free, expected
):
    import json
    import subprocess
    import sys

    binding = tmp_path / "binding"
    owner = tmp_path / "owner"
    owner.write_text("a" * 64)
    binding.write_text(
        json.dumps(
            {
                "schema": capacity.SCHEMA,
                "token": "a" * 64,
                "mount_sha256": "b" * 64,
                "issued_seconds": 1000,
            }
        )
    )
    code = """
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = sys.argv[1:3]
import test_sandbox
import test_sandbox_capacity as capacity
from repomap_test_support import resource_admission as admission
from repomap_test_support.resource_hygiene_policy import HygieneConfig, HygieneProfile
capacity.BINDING_PATH, capacity.OWNER_PATH = map(Path, sys.argv[3:5])
capacity.time.time = lambda: 1121
capacity.os.fstat = lambda fd: SimpleNamespace(st_uid=0, st_mode=0o100600)
capacity.root_mount = lambda: ("/layer", "b" * 64)
readings = {"/": (int(sys.argv[5]), 400 * capacity.GIB),
            "/sandbox-scratch": (8 * capacity.GIB, 8 * capacity.GIB),
            "/var/lib/docker": (4 * capacity.GIB, 4 * capacity.GIB)}
capacity.space = lambda path: readings[path]
test_sandbox.active_sandbox = lambda: True
admission.read_memory_pressure_reading = lambda: (admission.MemoryPressure.NORMAL, 50)
admission.read_docker_responsive = lambda: True
signals = admission.collect_host_signals(Path("/sandbox-scratch/test-scratch"),
    profile=HygieneProfile.EXHAUSTIVE, operator_attested_exclusive=True)
print(admission.decide_host_admission(HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals).admitted)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(Path(capacity.__file__).parent),
            str(Path(admission.__file__).parents[1]),
            str(binding),
            str(owner),
            str(backing_free),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.fixture
def sandbox_measurements(monkeypatch):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    monkeypatch.setattr(capacity, "read_binding", lambda: {})
    readings = {
        "/": (200 * GIB, 400 * GIB),
        "/sandbox-scratch": (8 * GIB, 8 * GIB),
        "/var/lib/docker": (4 * GIB, 4 * GIB),
    }
    original_statvfs = capacity.os.statvfs

    def measured(path):
        if str(path) not in readings:
            return original_statvfs(path)
        free, total = readings[str(path)]
        return SimpleNamespace(f_bavail=free, f_blocks=total, f_frsize=1)

    monkeypatch.setattr(capacity.os, "statvfs", measured)
    monkeypatch.setattr(
        admission,
        "read_memory_pressure_reading",
        lambda: (admission.MemoryPressure.NORMAL, 50),
    )
    monkeypatch.setattr(admission, "read_docker_responsive", lambda: True)
    return readings


@pytest.mark.parametrize(
    "suite,requested", [("int", None), ("staging", HygieneProfile.EXHAUSTIVE)]
)
@pytest.mark.parametrize("free", [8 * GIB, GIB, GIB - 1])
def test_runner_selected_profiles_use_current_whole_tmpfs_pressure(
    sandbox_measurements, suite, requested, free
):
    from repomap_test_support.resource_runner_profile import resolve_runner_profile

    selection = resolve_runner_profile(
        suite,
        requested_profile=requested,
        declared_complete_gates=int(suite == "staging"),
        campaign_plan_id=None,
        operator_attested_exclusive=True,
        operator_attested_pressure_degradation=False,
    )
    sandbox_measurements["/sandbox-scratch"] = (free, 8 * GIB)

    def collect():
        return admission.collect_host_signals(
            Path("/sandbox-scratch/test-scratch"),
            profile=selection.selected_profile,
            operator_attested_exclusive=True,
        )

    if free < GIB:
        with pytest.raises(RuntimeError, match="scratch_headroom_insufficient"):
            collect()
    else:
        assert admission.decide_host_admission(
            selection.selected_profile, HygieneConfig(), collect()
        ).admitted


@pytest.mark.usefixtures("isolate_test_resource_run_process_state")
@pytest.mark.parametrize("sandboxed", [True, False])
@pytest.mark.parametrize("quota", [None, (2 * GIB, 100000), (10 * GIB, 100000)])
def test_effective_override_is_logical_limit_not_physical_reservation(
    tmp_path, sandbox_measurements, quota, monkeypatch, sandboxed
):
    from dataclasses import replace
    from repomap_test_support.resource_run import TestResourceRun
    from repomap_test_support.resource_hygiene_policy import QuotaExceeded
    from repomap_test_support.test_scratch import establish_run

    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path)},
        project="repo-map_dev",
        phase="PR26-STAGING-FIX2",
    )
    from repomap_test_support.resource_run_test_support import admitted_host_signals

    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: sandboxed)
    run = TestResourceRun.start(
        layout,
        profile=HygieneProfile.INTEGRATION,
        quota_override=quota,
        host_signals=None
        if sandboxed
        else admitted_host_signals(free_disk_bytes=200 * GIB, docker_responsive=True),
    )
    assert run is not None
    measured = run.checkpoint("headroom")
    limit = (quota or HygieneProfile.INTEGRATION.quota)[0]
    with monkeypatch.context() as scoped:
        scoped.setattr(
            run.scratch,
            "checkpoint",
            lambda label: replace(measured, allocated_bytes=limit, inode_count=1),
        )
        with pytest.raises(QuotaExceeded):
            run.checkpoint("logical_limit")
    assert run.close()["current_run_teardown_complete"] is True


@pytest.mark.usefixtures("isolate_test_resource_run_process_state")
@pytest.mark.parametrize("suite", ["int", "staging"])
@pytest.mark.parametrize("failure", [None, "pressure", "statvfs", "mount"])
def test_runner_admission_releases_or_cleans_exact_owned_state(
    tmp_path, monkeypatch, sandbox_measurements, suite, failure, capsys
):
    import run_tests
    from repomap_test_support import resource_run
    from repomap_test_support.test_scratch import establish_run

    layout = establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path)},
        project="repo-map_dev",
        phase="PR26-STAGING-FIX2",
    )
    transient = layout.tmp / "setup"
    transient.write_text("owned")
    monkeypatch.setattr(run_tests, "establish_test_scratch", lambda args: layout)
    monkeypatch.setattr(run_tests, "integration_sandbox_dispatch", lambda *args: None)
    monkeypatch.setattr(run_tests, "start_runwide_docker_boundary", lambda *args: None)
    released: list[bool] = []

    def _fake_run_selected_suites(*args: object, **kwargs: object) -> int:
        released.append(True)
        return 0

    monkeypatch.setattr(
        run_tests, "run_selected_suites", _fake_run_selected_suites
    )
    if failure == "pressure":
        sandbox_measurements["/sandbox-scratch"] = (GIB - 1, 8 * GIB)
    elif failure in {"statvfs", "mount"}:

        def unavailable(*args, **kwargs):
            raise PermissionError("private measurement details")

        if failure == "statvfs":
            original_statvfs = capacity.os.statvfs

            def failed_root(path):
                return unavailable() if str(path) == "/" else original_statvfs(path)

            monkeypatch.setattr(capacity.os, "statvfs", failed_root)
        else:
            # Exercise the real mount reader through admission's binding boundary.
            monkeypatch.setattr(capacity, "read_binding", lambda: capacity.root_mount())
            original_open = Path.open

            def mount_open(path, *args, **kwargs):
                if str(path) == "/proc/self/mountinfo":
                    return unavailable()
                return original_open(path, *args, **kwargs)

            monkeypatch.setattr(Path, "open", mount_open)
    argv = ["--suite", suite]
    if suite == "staging":
        argv += [
            "--hygiene-profile",
            "exhaustive",
            "--declared-complete-gates",
            "1",
            "--operator-attest-exclusive",
        ]
    prior_owner = resource_run.active_resource_run()
    assert run_tests.main(argv) == (2 if failure else 0)
    assert bool(released) is (failure is None)
    assert not transient.exists()
    assert resource_run.active_resource_run() is (prior_owner if failure else None)
    if failure:
        assert not (layout.run_root / "resource-ledger.json").exists()
    error_text = capsys.readouterr().err
    assert "private measurement details" not in error_text
    if failure:
        assert "test hygiene admission failed" in error_text


def test_authenticated_sandbox_does_not_use_scratch_as_host_reserve(monkeypatch):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    monkeypatch.setattr(capacity, "read_binding", lambda: {})
    monkeypatch.setattr(
        admission.os,
        "statvfs",
        lambda path: SimpleNamespace(
            f_bavail={
                "/sandbox-scratch": 8 * GIB,
                "/sandbox-scratch/test-scratch": 8 * GIB,
                "/var/lib/docker": 4 * GIB,
            }.get(str(path), 20 * GIB),
            f_blocks={"/sandbox-scratch": 8 * GIB, "/var/lib/docker": 4 * GIB}.get(
                str(path), 40 * GIB
            ),
            f_frsize=1,
        ),
    )
    monkeypatch.setattr(
        admission,
        "read_memory_pressure_reading",
        lambda: (admission.MemoryPressure.NORMAL, 50),
    )
    monkeypatch.setattr(admission, "read_docker_responsive", lambda: True)
    signals = admission.collect_host_signals(
        Path("/sandbox-scratch/test-scratch"),
        profile=HygieneProfile.EXHAUSTIVE,
        operator_attested_exclusive=True,
        declared_complete_gates=1,
    )
    assert signals.free_disk_bytes == 20 * GIB
    assert admission.decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals
    ).admitted


@pytest.mark.parametrize("free,admitted", [(10 * GIB - 1, False), (10 * GIB, True)])
def test_backing_floor_is_independent_of_scratch(monkeypatch, free, admitted):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    monkeypatch.setattr(capacity, "read_binding", lambda: {})
    monkeypatch.setattr(
        capacity,
        "space",
        lambda path: (
            (free, 20 * GIB)
            if path == "/"
            else (8 * GIB, 8 * GIB)
            if path == "/sandbox-scratch"
            else (4 * GIB, 4 * GIB)
        ),
    )
    monkeypatch.setattr(
        admission,
        "read_memory_pressure_reading",
        lambda: (admission.MemoryPressure.NORMAL, 50),
    )
    monkeypatch.setattr(admission, "read_docker_responsive", lambda: True)
    signals = admission.collect_host_signals(
        Path("/sandbox-scratch/test-scratch"),
        profile=HygieneProfile.EXHAUSTIVE,
        operator_attested_exclusive=True,
        declared_complete_gates=1,
    )
    decision = admission.decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals
    )
    assert decision.admitted is admitted
    if not admitted:
        assert decision.reason == "free_disk_reserve"


def test_missing_binding_never_falls_back_or_accepts_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    monkeypatch.setattr(capacity, "BINDING_PATH", tmp_path / "absent")
    monkeypatch.setenv("REPOMAP_TEST_FREE_DISK_BYTES", str(200 * GIB))
    monkeypatch.setenv("REPOMAP_TEST_SANDBOX_CAPACITY", str(200 * GIB))
    monkeypatch.setattr(
        admission.os, "statvfs", lambda path: pytest.fail("must not measure fallback")
    )
    with pytest.raises(RuntimeError, match="missing_or_malformed_binding"):
        admission.collect_host_signals(tmp_path, profile=HygieneProfile.EXHAUSTIVE)
