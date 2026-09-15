"""TEST-HYGIENE1 facade tests for one exact test-resource run."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support import resource_run
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile, QuotaExceeded
from repomap_test_support.resource_interruption import operator_marker_path
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_run import ResourceRunError, TestResourceRun
from repomap_test_support.resource_run_test_support import admitted_host_signals
from repomap_test_support.resource_scratch import ScratchAccountingError
from repomap_test_support.test_scratch import establish_run

pytestmark = pytest.mark.usefixtures("isolate_test_resource_run_process_state")


def _layout(tmp_path: Path):
    return establish_run(
        {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path)},
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )


def test_allocating_layout_starts_one_private_ledger(tmp_path):
    layout = _layout(tmp_path)

    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())

    assert run is not None
    assert run.ledger.path == layout.run_root / "resource-ledger.json"
    assert run.ledger.path.stat().st_mode & 0o777 == 0o600


def test_inherited_layout_does_not_compete_for_lifecycle(tmp_path):
    owner = _layout(tmp_path)
    borrower = establish_run(
        {
            "REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path),
            "REPOMAP_TEST_RUN_ROOT": str(owner.run_root),
        },
        project="repo-map_dev",
        phase="TEST-HYGIENE1",
    )

    assert TestResourceRun.start(borrower) is None
    assert not (owner.run_root / "resource-ledger.json").exists()


@pytest.mark.parametrize("profile", [HygieneProfile.INTEGRATION, HygieneProfile.EXHAUSTIVE])
def test_sandbox_headroom_refusal_still_allows_exact_cleanup(tmp_path, monkeypatch, profile):
    import test_sandbox
    import test_sandbox_capacity as capacity

    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, profile=profile, host_signals=admitted_host_signals(
            docker_responsive=True, operator_attested_exclusive=True
        ),
    )
    assert run is not None
    transient = layout.tmp / "transient"
    transient.write_bytes(b"owned")
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    monkeypatch.setattr(capacity, "space", lambda path: (0, 8 * GIB))
    with pytest.raises(RuntimeError, match="scratch_headroom_insufficient"):
        with run.bounded_subprocess("workload"):
            pytest.fail("capacity refusal must prevent workload release")
    assert run.close()["current_run_teardown_complete"] is True
    assert not transient.exists()


@pytest.mark.parametrize("primary", [ValueError, KeyboardInterrupt])
@pytest.mark.parametrize("measurement_failure", [False, True])
def test_secondary_capacity_failure_preserves_primary_workload_error(
    tmp_path, monkeypatch, primary, measurement_failure
):
    import test_sandbox
    import test_sandbox_capacity as capacity

    run = TestResourceRun.start(_layout(tmp_path), host_signals=admitted_host_signals())
    assert run is not None
    with pytest.raises(primary, match="primary workload") as caught:
        with run.bounded_subprocess("workload"):
            monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
            if measurement_failure:
                original_statvfs = capacity.os.statvfs

                def unavailable(path):
                    if str(path) == "/sandbox-scratch":
                        raise PermissionError("private measurement details")
                    return original_statvfs(path)

                monkeypatch.setattr(capacity.os, "statvfs", unavailable)
            else:
                monkeypatch.setattr(capacity, "space", lambda path: (0, 8 * GIB))
            raise primary("primary workload")
    assert caught.value.__notes__ == ["secondary resource checkpoint failed"]
    assert run.close()["current_run_teardown_complete"] is True


def test_close_removes_transient_scratch_and_keeps_bounded_ledger(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())
    assert run is not None
    (layout.tmp / "temporary.bin").write_bytes(b"temporary")

    projection = run.close()

    assert projection["scratch_transient_bytes_remaining"] == 0
    assert projection["scratch_unknown_owned_bytes"] == 0
    assert layout.manifest.exists()
    assert run.ledger.path.exists()
    assert projection["pre_existing_objects_mutated"] == "unobserved"
    assert projection["foreign_scratch_runs_mutated"] == "unobserved"
    assert projection["current_run_cleanup_outcome"] == "cleanup_complete"
    assert projection["retained_evidence_outcome"] == "evidence_retained"


def test_nested_report_is_retained_by_its_top_level_evidence_owner(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())
    assert run is not None
    evidence = layout.run_root / "evidence"
    report = evidence / "test-report" / "unit" / "latest"
    report.mkdir(parents=True)
    (report / "index.html").write_text("public-safe")
    run.retain_evidence(evidence, reason="report_source")

    projection = run.close()

    assert projection["scratch_unknown_owned_bytes"] == 0
    assert (report / "index.html").is_file()


def test_subprocess_checkpoints_record_before_and_after(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())
    assert run is not None

    with run.bounded_subprocess("focused-unit"):
        (layout.logs / "bounded.log").write_text("public-safe")

    payload = run.ledger.path.read_text()
    assert "before_focused-unit" in payload
    assert "after_focused-unit" in payload


def test_checkpoint_counts_unsafe_test_links_but_close_removes_them(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())
    assert run is not None
    dangling = layout.pytest_basetemp / "dangling"
    dangling.symlink_to(layout.pytest_basetemp / "missing")
    escape = layout.pytest_basetemp / "escape"
    escape.symlink_to(tmp_path, target_is_directory=True)

    checkpoint = run.scratch.checkpoint("unsafe-test-links")
    projection = run.close()

    assert checkpoint.unsafe_link_count == 2
    assert projection["scratch_transient_bytes_remaining"] == 0


def test_integration_run_writes_immutable_admission_and_close_records(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout,
        profile=HygieneProfile.INTEGRATION,
        host_signals=admitted_host_signals(
            free_disk_bytes=100 * GIB, docker_responsive=True
        ),
        now_seconds=100,
    )
    assert run is not None
    admission = run.index.records_path / f"{layout.run_root.name}.admitted.json"
    assert admission.is_file()

    projection = run.close(now_seconds=200)
    close = run.index.records_path / f"{layout.run_root.name}.closed.json"

    assert admission.stat().st_mode & 0o777 == 0o600
    assert close.stat().st_mode & 0o777 == 0o600
    assert projection["terminal_outcome"] == "passed"
    assert projection["retention_class"] == "successful-evidence"
    assert projection["current_run_teardown_complete"] is True
    assert projection["host_restoration_proved"] is False


def test_report_source_stays_pending_at_run_close(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, host_signals=admitted_host_signals(), now_seconds=100
    )
    assert run is not None
    report = layout.run_root / "operational-source.txt"
    report.write_text("public-safe")
    run.retain_evidence(report, reason="report_source")

    projection = run.close(now_seconds=200)

    assert projection["retention_class"] == "report-source-pending-append"
    assert report.is_file()


def test_synthetic_quota_refusal_preserves_evidence_and_tears_down(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout,
        host_signals=admitted_host_signals(),
        now_seconds=100,
        quota_override=(1, 1),
    )
    assert run is not None
    evidence = layout.run_root / "diagnostic.txt"
    evidence.write_text("preserve")
    run.retain_evidence(evidence, reason="failure_evidence")

    with pytest.raises(QuotaExceeded, match="quota_exceeded"):
        run.checkpoint("synthetic_refusal")
    projection = run.close(now_seconds=200)

    assert evidence.is_file()
    assert projection["terminal_outcome"] == "quota_exceeded"
    assert projection["scratch_transient_bytes_remaining"] == 0
    assert projection["scratch_unknown_owned_bytes"] == 0


def test_quota_measurement_includes_checkpoint_evidence(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, host_signals=admitted_host_signals(), now_seconds=100
    )
    assert run is not None

    before = run.scratch.measure_current()
    observed = run.checkpoint("exact_checkpoint_accounting")

    assert observed.allocated_bytes >= before.allocated_bytes
    assert observed.apparent_bytes > before.apparent_bytes


def test_explicit_operator_marker_changes_terminal_classification(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, host_signals=admitted_host_signals(), now_seconds=100
    )
    assert run is not None
    marker = operator_marker_path(
        layout.scratch_root,
        project=layout.project,
        run_id=layout.run_root.name,
    )
    write_private_json_exclusive(
        marker,
        {
            "schema": "repomap-test-operator-interruption-v1",
            "project": layout.project,
            "phase": layout.phase,
            "run_id": layout.run_root.name,
            "operator_attributed": True,
            "observed_at_seconds": 150,
        },
    )

    projection = run.close(now_seconds=200)

    assert projection["terminal_outcome"] == "operator_interrupted"
    assert projection["retention_class"] == "failed-evidence"


def test_unattributed_state_change_remains_distinct(tmp_path):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, host_signals=admitted_host_signals(), now_seconds=100
    )
    assert run is not None

    assert run.observe_state_change().value == "external_unattributed_mutation"
    projection = run.close(now_seconds=200)

    assert projection["terminal_outcome"] == "external_unattributed_mutation"


def test_cleanup_failure_uses_closed_failure_category(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    run = TestResourceRun.start(
        layout, host_signals=admitted_host_signals(), now_seconds=100
    )
    assert run is not None

    def fail_cleanup(*, record_boundaries):
        raise ScratchAccountingError("private detail")

    monkeypatch.setattr(run.scratch, "cleanup_transient", fail_cleanup)
    with pytest.raises(ResourceRunError, match="^current_run_cleanup_failed$"):
        run.close(now_seconds=200)


def test_explicit_signals_never_observe_the_ambient_host(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("ambient host signals were collected")

    monkeypatch.setattr(resource_run, "collect_host_signals", refuse)

    layout = _layout(tmp_path)
    run = TestResourceRun.start(layout, host_signals=admitted_host_signals())

    assert run is not None
    assert run.ledger.path == layout.run_root / "resource-ledger.json"
