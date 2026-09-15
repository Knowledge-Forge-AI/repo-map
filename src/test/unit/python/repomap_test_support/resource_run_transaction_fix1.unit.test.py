"""TEST-HYGIENE3A-FIX1 transactional start regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support import resource_run
from repomap_test_support import resource_index
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.resource_run_test_support import admitted_host_signals
from repomap_test_support.test_scratch import establish_run

pytestmark = pytest.mark.usefixtures("isolate_test_resource_run_process_state")


def _layout(tmp_path: Path):
    return establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path)},
        project="repo-map_dev",
        phase="TEST-HYGIENE3A-FIX1",
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "ledger_creation",
        "scratch_registration",
        "configuration_write",
        "retained_registration",
        "entry_quota_checkpoint",
    ],
)
def test_post_admission_setup_failure_is_closed_without_reservation(
    tmp_path: Path, monkeypatch, boundary: str
):
    layout = _layout(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {boundary}")

    if boundary == "ledger_creation":
        monkeypatch.setattr(resource_run.ResourceLedger, "create", fail)
    elif boundary == "scratch_registration":
        monkeypatch.setattr(resource_run.ScratchRunOwner, "register_layout", fail)
    elif boundary == "configuration_write":
        monkeypatch.setattr(resource_run, "write_private_json", fail)
    elif boundary == "retained_registration":
        monkeypatch.setattr(resource_run.TestResourceRun, "retain_evidence", fail)
    else:
        monkeypatch.setattr(resource_run.TestResourceRun, "_apply_quota", fail)

    with pytest.raises(RuntimeError, match="injected"):
        TestResourceRun.start(
            layout, host_signals=admitted_host_signals(), now_seconds=100
        )

    records = layout.scratch_root / ".index" / layout.project / "runs"
    assert (records / f"{layout.run_root.name}.admitted.json").is_file()
    close_path = records / f"{layout.run_root.name}.closed.json"
    assert close_path.is_file()
    close = json.loads(close_path.read_text())
    assert close["terminal_outcome"] == "failed"
    assert close["retained_evidence_bytes"] == close["allocated_bytes"]
    assert (layout.run_root / "admission-abort.json").is_file()
    assert all(not path.exists() for path in layout.directories())


def test_admission_lock_release_failure_preserves_lock_for_maintenance_recovery(
    tmp_path: Path, monkeypatch
):
    layout = _layout(tmp_path)

    def fail_release(self, token):
        raise resource_index.IndexError("injected lock release failure")

    monkeypatch.setattr(resource_index.AdvisoryIndex, "_release_lock", fail_release)

    with pytest.raises(
        resource_run.ResourceRunError,
        match="admission lock failure rollback failed",
    ):
        TestResourceRun.start(
            layout, host_signals=admitted_host_signals(), now_seconds=100
        )

    records = layout.scratch_root / ".index" / layout.project / "runs"
    assert (records / f"{layout.run_root.name}.admitted.json").is_file()
    assert not (records / f"{layout.run_root.name}.closed.json").exists()
    assert (layout.scratch_root / ".index" / layout.project / "admission.lock").is_file()


def test_environment_publication_failure_does_not_publish_active_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    active_before = resource_run.active_resource_run()

    class RefusingEnvironment(dict[str, str]):
        def __setitem__(self, key: str, value: str) -> None:
            if key == resource_run.ENV_RESOURCE_LEDGER:
                raise OSError("injected ledger environment failure")
            super().__setitem__(key, value)

    monkeypatch.setattr(
        resource_run.os, "environ", RefusingEnvironment(resource_run.os.environ)
    )
    with pytest.raises(OSError, match="injected ledger environment failure"):
        TestResourceRun.start(
            layout, host_signals=admitted_host_signals(), now_seconds=100
        )

    assert resource_run.active_resource_run() is active_before
