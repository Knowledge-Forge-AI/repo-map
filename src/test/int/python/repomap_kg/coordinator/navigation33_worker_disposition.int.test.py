"""Integration contracts for Order 1: portable worker authority, supervision, and coordinator disposition."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import threading
from typing import Any, Iterator, cast
import unittest

import pytest

from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._control_maintenance import CleanupReport
from repomap_kg.coordinator._control_types import JobClaim, JobStatus
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_materialization import MaterializedWorkspace, _directory_identity, _remove_attempt_root
from repomap_kg.coordinator._portable_worker_launch import _run_portable_worker_command
from repomap_kg.coordinator._protocol_validation import ProtocolError
from repomap_kg.coordinator._refresh_capability import RefreshCapability, create_refresh_capability, load_refresh_capability, remove_refresh_capability
from repomap_kg.coordinator._refresh_capability_io import validate_config_file, validate_private_directory, validate_psql, validate_psql_lexical, validate_search_path
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.coordinator.refresh_adapter import refresh_terminal, run_refresh_worker
from repomap_test_support.run25_portable_workflows import create_run25_test_capability


class _DispositionStoreDouble:
    """Protocol-conforming coordinator store double for terminal disposition contracts."""

    def __init__(self) -> None:
        self.epoch = 1
        self.claim: JobClaim | None = None
        self.state_map: dict[str, str] = {}
        self.fail_reconciliation = self.fail_terminated = self.fail_lease_release = self.fail_schedule_retry = False
        self.rejected_transitions: set[tuple[str, str]] = set()
        self.reconcile_outcome = "reconciled_success"
        self.cleanup_residuals: tuple[str, ...] = ()
        self.reconciliation_records: list[tuple[JobClaim, dict[str, Any]]] = []
        self.terminated_records: list[tuple[JobClaim, dict[str, Any]]] = []
        self.released_leases: list[str] = []

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        del instance_id, ttl
        return self.epoch

    def stop_singleton(self, instance_id: str, epoch: int) -> bool:
        del instance_id, epoch
        return True

    @contextmanager
    def maintenance_activity(self) -> Iterator[None]:
        yield

    def claim_next(self, instance_id: str, epoch: int, ttl: timedelta, *, automatic_only: bool = False) -> JobClaim | None:
        del instance_id, epoch, ttl, automatic_only
        claimed, self.claim = self.claim, None
        return claimed

    def status(self, job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id, graph_id="graph_nav33", state=self.state_map.get(job_id, "running"),
            attempt=1, publication_state="not_started", phase="complete", completed=0, total=None, error_category=None,
        )

    def compare_and_set_state(self, job_id: str, expected_state: str, new_state: str, **kwargs: Any) -> bool:
        del kwargs
        if (expected_state, new_state) in self.rejected_transitions:
            return False
        self.state_map[job_id] = new_state
        return True

    def release_graph_lease(self, graph_id: str, job_id: str, *args: Any, **kwargs: Any) -> bool:
        del graph_id, args, kwargs
        if self.fail_lease_release:
            return False
        self.released_leases.append(job_id)
        return True

    def record_publication_marker(self, claim: JobClaim, **kwargs: Any) -> bool:
        del claim, kwargs
        return True

    def mark_reconciliation_required(self, claim: JobClaim, **kwargs: Any) -> bool:
        if self.fail_reconciliation:
            return False
        self.reconciliation_records.append((claim, kwargs))
        return True

    def mark_attempt_terminated(self, claim: JobClaim, **kwargs: Any) -> bool:
        if self.fail_terminated:
            return False
        self.terminated_records.append((claim, kwargs))
        return True

    def schedule_retry(self, claim: JobClaim, **kwargs: Any) -> bool:
        del claim, kwargs
        return not self.fail_schedule_retry

    def request_cancellation(self, job_id: str) -> str:
        self.state_map[job_id] = "cancel_requested"
        return "cancel_requested"

    def reconcile_publication(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return self.reconcile_outcome

    def cleanup_terminal(self, *args: Any, **kwargs: Any) -> CleanupReport:
        del args, kwargs
        return CleanupReport(deleted_job_ids=(), residuals=self.cleanup_residuals)


def _claim(job_id: str) -> JobClaim:
    return JobClaim(job_id=job_id, graph_id="graph_nav33", attempt=1, instance_id="inst_nav33", fencing_epoch=1)


class Navigation33WorkerDispositionIntegrationTests(unittest.TestCase):
    """Integration contracts for coordinator terminal disposition and worker supervision."""

    def test_committed_marker_and_termination_reconciliation_outcomes(self) -> None:
        """Committed terminal states handle marker recording, termination proof, and ownership loss."""
        store = _DispositionStoreDouble()
        store.claim, store.fail_reconciliation = _claim("job_m1"), True
        coord = SyntheticCoordinator(
            cast(Any, store), "inst_nav33",
            lambda _c, _e: {"status": "succeeded", "publication_state": "committed", "_termination_proved": True},
        )
        coord.startup(lambda: None)
        self.assertEqual(coord.run_once(), "ownership_lost")

        store.fail_reconciliation, store.fail_terminated, store.claim = False, True, _claim("job_m2")
        self.assertEqual(coord.run_once(), "ownership_lost")

        store.fail_terminated = False
        retired: list[str] = []
        coord_ret = SyntheticCoordinator(
            cast(Any, store), "inst_nav33",
            lambda _c, _e: {"status": "succeeded", "publication_state": "committed", "_termination_proved": True},
            publication_retirer=lambda cl: retired.append(cast(Any, cl).job_id),
        )
        coord_ret.startup(lambda: None)
        store.reconcile_outcome, store.claim = "succeeded", _claim("job_m3_ok")
        self.assertEqual(coord_ret.run_once(), "succeeded")
        self.assertEqual(retired, ["job_m3_ok"])

        store.reconcile_outcome, store.claim = "reconciliation_required", _claim("job_m3_pending")
        self.assertEqual(coord_ret.run_once(), "reconciliation_required")
        self.assertEqual(retired, ["job_m3_ok"])

        valid_committed = {
            "status": "succeeded", "publication_state": "committed", "latest_run_identity": "run-1",
            "source_generation": "sg1:a", "config_generation": "cg1:a",
            "extractor_generation": "eg1:a", "canonicalizer_generation": "kg1:a", "_termination_proved": True,
        }
        coord_valid = SyntheticCoordinator(cast(Any, store), "inst_nav33", lambda _c, _e: dict(valid_committed))
        coord_valid.startup(lambda: None)
        store.fail_reconciliation, store.claim = True, _claim("job_m4_rec")
        self.assertEqual(coord_valid.run_once(), "ownership_lost")

        store.fail_reconciliation, store.fail_terminated, store.claim = False, True, _claim("job_m4_term")
        self.assertEqual(coord_valid.run_once(), "ownership_lost")
        for c in (coord, coord_ret, coord_valid):
            c.shutdown()

    def test_unproved_commit_unknown_cancel_and_fallback_disposition_branches(self) -> None:
        """Unproved termination, commit_unknown, cancel-requested failure/cancel, and fallback paths."""
        store = _DispositionStoreDouble()
        mode = "unproved"

        def _runner(cl: JobClaim, event: threading.Event) -> dict[str, object]:
            if mode.startswith("cancel_"):
                store.request_cancellation(cl.job_id)
                event.set()
            if mode == "unproved":
                return {"status": "failed", "publication_state": "not_started", "_termination_proved": False}
            if mode == "commit_unknown":
                return {"status": "failed", "publication_state": "commit_unknown", "_termination_proved": True}
            if mode.startswith("cancel_failed"):
                return {"status": "failed", "publication_state": "not_started", "_termination_proved": True}
            if mode.startswith("cancel_ok"):
                return {"status": "cancelled", "publication_state": "not_started", "_termination_proved": True}
            if mode == "retry_fallthrough":
                return {"status": "failed", "error_category": "transient", "publication_state": "not_started", "_termination_proved": True}
            return {
                "status": "reconciliation_required", "publication_state": "not_started",
                "_termination_proved": True, "_error_category": "worker_crash", "_diagnostic_summary": None,
            }

        retired: list[str] = []
        coord = SyntheticCoordinator(
            cast(Any, store), "inst_nav33", _runner, publication_retirer=lambda cl: retired.append(cast(Any, cl).job_id),
        )
        coord.startup(lambda: None)

        store.fail_reconciliation = True
        store.claim = _claim("job_unproved")
        self.assertEqual(coord.run_once(), "ownership_lost")

        mode = "commit_unknown"
        store.claim = _claim("job_cu_rec")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.fail_reconciliation = False
        store.fail_terminated = True
        store.claim = _claim("job_cu_term")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.fail_terminated = False

        mode = "cancel_failed"
        store.rejected_transitions = {("cancel_requested", "cancelling")}
        store.claim = _claim("job_cf_1")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.rejected_transitions = {("cancelling", "failed")}
        store.claim = _claim("job_cf_2")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.rejected_transitions.clear()
        store.claim = _claim("job_cf_3")
        self.assertEqual(coord.run_once(), "failed")
        self.assertEqual(store.state_map["job_cf_3"], "failed")

        mode = "retry_fallthrough"
        store.fail_schedule_retry = True
        store.rejected_transitions = {("running", "failed")}
        store.claim = _claim("job_rf_1")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.fail_schedule_retry = False
        store.rejected_transitions.clear()

        mode = "cancel_ok"
        store.rejected_transitions = {("cancel_requested", "cancelling")}
        store.claim = _claim("job_co_1")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.rejected_transitions = {("cancelling", "cancelled")}
        store.claim = _claim("job_co_2")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.rejected_transitions.clear()

        mode = "fallback"
        store.fail_reconciliation = True
        store.claim = _claim("job_fb_1")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.fail_reconciliation = False
        store.fail_terminated = True
        store.claim = _claim("job_fb_2")
        self.assertEqual(coord.run_once(), "ownership_lost")
        store.fail_terminated = False
        store.reconcile_outcome = "cancelled"
        store.claim = _claim("job_fb_3")
        self.assertEqual(coord.run_once(), "cancelled")
        self.assertEqual(store.reconciliation_records[-1][1]["diagnostic_summary"], "worker_crash:unproved_termination")
        self.assertIn("job_fb_3", retired)
        coord.shutdown()

    def test_evidence_retirement_residuals_lease_release_and_exception_diagnostics(self) -> None:
        """Retire-evidence errors, residual bounds, lease-release errors, and exception formatting."""
        store = _DispositionStoreDouble()
        should_fail_retirer = False
        error_to_raise: BaseException = FileNotFoundError("missing")

        def _failing_retirer(_claim: object) -> None:
            if should_fail_retirer:
                raise error_to_raise

        coord = SyntheticCoordinator(
            cast(Any, store), "inst_nav33",
            lambda _c, _e: {"status": "failed", "error_category": "permanent", "publication_state": "not_started", "_termination_proved": True},
            publication_retirer=_failing_retirer,
        )

        def _run_once_bounded() -> str:
            out: list[str] = []
            errors: list[BaseException] = []
            def run() -> None:
                try:
                    out.append(coord.run_once())
                except BaseException as error:
                    errors.append(error)
            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(5.0)
            self.assertFalse(t.is_alive(), "SyntheticCoordinator.run_once timed out holding _lock")
            if errors:
                raise errors[0]
            return out[0]

        coord.startup(lambda: None)
        should_fail_retirer, store.claim = True, _claim("job_fnf")
        self.assertEqual(_run_once_bounded(), "failed")
        self.assertEqual(store.state_map["job_fnf"], "failed")
        self.assertEqual(coord.residual_evidence, ("job_fnf:1:not_found",))
        self.assertEqual(store.released_leases, ["job_fnf"])

        error_to_raise, store.claim = OSError("disk_io"), _claim("job_os")
        self.assertEqual(_run_once_bounded(), "failed")
        self.assertEqual(store.state_map["job_os"], "failed")
        self.assertEqual(coord.residual_evidence, ("job_fnf:1:not_found", "job_os:1:os_error"))
        self.assertEqual(store.released_leases, ["job_fnf", "job_os"])

        store.cleanup_residuals = tuple(f"res:{i}:os_error" for i in range(35))
        report = coord.cleanup_terminal(timedelta(seconds=1), limit=10, dry_run=False)
        self.assertEqual((report.residual_count, len(coord.residual_evidence)), (35, 32))
        store.claim = _claim("job_overflow")
        self.assertEqual((_run_once_bounded(), len(coord.residual_evidence)), ("failed", 32))
        self.assertIn("job_overflow", store.released_leases)
        should_fail_retirer, store.fail_lease_release, store.claim = False, True, _claim("job_lease_fail")
        with self.assertRaisesRegex(RuntimeError, "terminal graph lease release failed"):
            coord.run_once()
        coord.shutdown()

        weird_exc_cls = type("Bad-Name!", (Exception,), {})
        store2 = _DispositionStoreDouble()
        store2.fail_reconciliation, store2.claim = True, _claim("job_weird_exc")
        coord2 = SyntheticCoordinator(cast(Any, store2), "inst_nav33", lambda _c, _e: (_ for _ in ()).throw(weird_exc_cls()))
        coord2.startup(lambda: None)
        self.assertEqual(coord2.run_once(), "ownership_lost")
        coord2.shutdown()


def test_portable_and_refresh_worker_startup_refusals_and_materialization(tmp_path: Path) -> None:
    """Portable/refresh workers refuse mismatched capabilities/start frames and clean materialized trees."""
    tmp_path.chmod(0o700)
    store_root, workspace = tmp_path / "store", tmp_path / "workspace"
    store_root.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    cap = create_run25_test_capability(tmp_path, store, workspace, job_id="job-nav33-pw")
    limits = CoordinatorLimits()
    cap_mismatch = create_portable_capability(tmp_path, cap)
    with pytest.raises(ProtocolError, match="identity_mismatch"):
        _run_portable_worker_command(
            cap_mismatch, {"job_id": "wrong-job-id", "attempt": 1}, limits,
            module="repomap_kg.coordinator.portable_worker",
        )
    assert not cap_mismatch.exists()
    cap_path = create_portable_capability(tmp_path, cap)
    res_bad_graph = _run_portable_worker_command(
        cap_path, {"job_id": cap.job_id, "attempt": 1}, limits,
        module="repomap_kg.coordinator.portable_worker", job_graph_id="different-graph",
    )
    assert res_bad_graph.terminal["error_category"] == "identity_mismatch" and res_bad_graph.waited and res_bad_graph.process_group_cleaned and res_bad_graph.cleanup_error is None
    manifest = PortableSnapshotManifest.from_bytes(store.read(cap.manifest_reference))
    nested_entry = replace(manifest.entries[0], source_relative_path="nested/sub/main.py")
    nested_manifest = PortableSnapshotManifest.create(
        graph_id=manifest.graph_id, bindings=manifest.bindings, entries=(nested_entry,),
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity, resolver_identity=manifest.resolver_identity,
        canonicalizer_identity=manifest.canonicalizer_identity, semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity,
    )
    with MaterializedWorkspace(store, nested_manifest, workspace, job_id="job-mat", attempt=1, cancel_check=None) as view:
        assert (view.binding_roots[nested_entry.binding_id] / "nested/sub/main.py").is_file()
    with pytest.raises(RuntimeError, match="cancelled"):
        with MaterializedWorkspace(store, nested_manifest, workspace, job_id="job-mat-c", attempt=1, cancel_check=lambda: (_ for _ in ()).throw(RuntimeError("cancelled"))):
            pass
    with pytest.raises(RuntimeError, match="portable cleanup encountered unexpected node"):
        with MaterializedWorkspace(store, nested_manifest, workspace, job_id="job-mat2", attempt=1, cancel_check=None) as view:
            root_dir = view.binding_roots[nested_entry.binding_id]
            root_dir.chmod(0o700)
            (root_dir / "unexpected_link").symlink_to(root_dir / "nested/sub/main.py")
    _remove_attempt_root(tmp_path / "nonexistent_attempt_root")
    f_not_dir = tmp_path / "not_a_dir.txt"
    f_not_dir.write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not an owned directory"):
        _directory_identity(f_not_dir)
    psql_bin, cfg_file = tmp_path / "psql", tmp_path / "repomap.rp.toml"
    psql_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    psql_bin.chmod(0o700)
    cfg_file.write_text("schema_version = 1\n", encoding="utf-8")
    cfg_file.chmod(0o600)
    for fn, arg in (
        (validate_private_directory, Path("rel")), (validate_private_directory, tmp_path / "no_dir"),
        (validate_config_file, Path("rel.toml")), (validate_config_file, tmp_path / "no.toml"),
        (validate_psql, Path("rel_psql")), (validate_psql_lexical, Path("rel_psql")),
        (validate_search_path, (tmp_path / "no_dir",)), (validate_search_path, (f_not_dir,)),
    ):
        with pytest.raises((ValueError, RuntimeError)):
            cast(Any, fn)(arg)
    ref_cap = RefreshCapability(
        schema_version=1, job_id="job-ref", attempt=1, graph_id="g1", config_path=cfg_file, psql_path=psql_bin,
        postgres_user="repomap", postgres_password="pw", executable_search_path=(tmp_path,),
        postgres_host="127.0.0.1", postgres_port=5432, postgres_route_kind="configured",
        source_generation="sg1:" + "a" * 64, config_generation="cg1:" + "b" * 64,
        extractor_generation="eg1:v1", canonicalizer_generation="kg1:v1",
        coordinator_instance_id="inst-1", singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
    )
    for bad_res in (object(), type("Res", (), {"result": "success", "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:01Z", "run_id": True})()):
        with pytest.raises(ValueError, match="invalid refresh result"):
            refresh_terminal(ref_cap, bad_res)
    ref_cap_path = create_refresh_capability(tmp_path, ref_cap)
    assert load_refresh_capability(ref_cap_path).job_id == "job-ref"
    with pytest.raises(ProtocolError, match="identity_mismatch"):
        run_refresh_worker(
            ref_cap_path, {"job_id": "mismatch-ref", "attempt": 1}, limits,
            job_context={"graph_id": "g1", "source_generation": ref_cap.source_generation, "config_generation": ref_cap.config_generation},
        )
    remove_refresh_capability(tmp_path / "nonexistent_ref.json")
