"""Connected recovery keeps uncertainty when an external authority refuses closure."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator._restart_fencing import FencingContentionError
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.startup_recovery import recover_startup
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture,
    _refresh_harness,
    _req_norm,
)


@pytest.mark.parametrize("boundary", [
    "reader-contention", "closer-error", "prover-unavailable", "prover-refused",
    "prover-contention", "prover-error", "file-refused", "legacy-unavailable",
    "legacy-contention", "legacy-error",
])
def test_recovery_refusals_preserve_current_attempt_and_evidence(boundary: str) -> None:
    with _refresh_harness() as (store, directory, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, directory, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(lambda cl, **kw: resolver.install_graph_publication_fence(cl, **kw))
        epoch = store.acquire_singleton("prior", timedelta(seconds=300))
        submitted = store.submit(_req_norm("refusal", sg, cg, eg, kg))
        claim = store.claim_next("prior", epoch, timedelta(seconds=300))
        assert claim is not None and claim.job_id == submitted.job_id
        for expected, target in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(
                claim.job_id, expected_state=expected, new_state=target, attempt=claim.attempt,
                instance_id=claim.instance_id, fencing_epoch=epoch,
            )
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        legacy = boundary.startswith("legacy")
        with connect() as conn:
            conn.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (claim.job_id,))
            if legacy:
                conn.execute("UPDATE graph_leases SET graph_lease_fencing_epoch = 0 WHERE job_id = %s", (claim.job_id,))
                conn.execute("UPDATE job_attempts SET graph_lease_fencing_epoch = 0 WHERE job_id = %s", (claim.job_id,))
                claim = replace(claim, graph_lease_fencing_epoch=0)
        _publication_phase.initialize(directory, claim)
        initial, = directory.glob("publication-*.initial.json")
        before = initial.read_bytes()
        assert store.stop_singleton("prior", epoch)
        replacement = store.acquire_singleton("replacement", timedelta(seconds=300))

        class BoundaryStore:
            """Delegate durable operations while injecting one external refusal."""

            def __getattr__(self, name: str) -> Any:
                if name == "quarantine_legacy_attempt" and legacy:
                    if boundary == "legacy-unavailable":
                        raise AttributeError(name)
                    def quarantine(*args, **kwargs):
                        if boundary == "legacy-contention":
                            raise FencingContentionError("fixture contention")
                        raise KeyError("fixture corrupt response")
                    return quarantine
                if name == "close_unpublished_reconciliation":
                    if boundary.startswith("prover") or boundary == "file-refused":
                        raise AttributeError(name)
                    if boundary == "closer-error":
                        def close(*args, **kwargs):
                            raise OSError("fixture evidence unavailable")
                        return close
                if name == "prove_worker_fenced":
                    if boundary == "prover-unavailable":
                        raise AttributeError(name)
                    if boundary == "prover-refused":
                        return lambda *args, **kw: None
                    if boundary in {"prover-contention", "prover-error"}:
                        def prove(*args, **kwargs):
                            if boundary == "prover-contention":
                                raise FencingContentionError("fixture contention")
                            raise KeyError("fixture corrupt authority")
                        return prove
                return getattr(store, name)

        def reader(_: object):
            if boundary == "reader-contention":
                raise FencingContentionError("fixture storage contention")
            return None

        def closer(attempt: object, proof: object) -> bool:
            return _publication_phase.close_unpublished(directory, attempt, proof=cast(Any, proof))

        if boundary == "file-refused":
            _publication_phase.before_publication(directory, claim)
        report = recover_startup(
            cast(Any, BoundaryStore()), reader, instance_id="replacement", fencing_epoch=replacement,
            limit=10, publication_closer=None if boundary == "reader-contention" else closer,
        )
        assert (report.scanned, report.resolved, report.pending) == (1, 0, 1)
        expected_errors = {"closer-error": ("OSError",), "prover-error": ("KeyError",), "legacy-error": ("KeyError",)}
        assert report.unexpected == expected_errors.get(boundary, ())
        # Reader contention is an OSError: unavailable, without a closure refusal.
        refused = boundary in {"prover-refused", "prover-contention", "file-refused", "legacy-contention"}
        assert report.refused == int(refused)
        assert report.unavailable == int(boundary == "reader-contention")
        assert report.route_changed == 0
        assert report.residuals == 0
        assert initial.read_bytes() == before
        assert _publication_phase.publication_state(directory, claim) == "commit_unknown"
        with connect() as conn:
            assert conn.execute("SELECT state, publication_state FROM jobs WHERE job_id = %s", (claim.job_id,)).fetchone() == ("reconciliation_required", "commit_unknown")
            assert conn.execute("SELECT is_current, finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s", (claim.job_id,)).fetchone() == (True, True)
            assert conn.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,)).fetchone() == (1,)
        assert store.stop_singleton("replacement", replacement)
