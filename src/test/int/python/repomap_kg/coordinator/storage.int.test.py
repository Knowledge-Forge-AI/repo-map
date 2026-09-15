from __future__ import annotations

import hashlib
import unittest
from datetime import timedelta

import psycopg

from repomap_kg.coordinator import JobRequest, normalize_request
from repomap_kg.coordinator.storage import (
    CONTROL_SCHEMA_VERSION,
    ControlSchemaError,
    ControlStore,
    JobClaim,
)
from repomap_kg.coordinator._control_schema import (
    ControlSchemaStatus,
    discover_control_migrations,
    migration_text,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


EXPECTED_TABLES = {
    "coalescing_state", "coordinator_instances", "graph_leases", "job_attempts",
    "jobs", "synthetic_publication_markers", "repomap_control_schema_migrations",
}


class ControlStoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        require_postgres_binaries()
        self.postgres_context = temporary_postgres()
        self.postgres = self.postgres_context.__enter__()
        self.store = ControlStore(self._connect)

    def tearDown(self):
        self.postgres_context.__exit__(None, None, None)

    def _connect(self):
        return psycopg.connect(
            host=self.postgres.host,
            port=self.postgres.port,
            user=self.postgres.user,
            dbname=self.postgres.database,
            password=self.postgres.password,
        )

    def _claim(
        self, instance_id: str, epoch: int, lease: timedelta = timedelta(seconds=30)
    ) -> JobClaim:
        claim = self.store.claim_next(instance_id, epoch, lease)
        assert claim is not None
        return claim

    def test_schema_is_isolated_versioned_and_idempotent(self):
        self.store.initialize_schema()
        self.store.initialize_schema()

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    "SELECT obj_description('jobs'::regclass, 'pg_class')"
                )
                version = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
                columns = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    "SELECT ordinal, changeset_id, migration_path, checksum "
                    "FROM repomap_control_schema_migrations ORDER BY ordinal"
                )
                ledger = cursor.fetchall()

        self.assertEqual(tables, EXPECTED_TABLES)
        self.assertEqual(version, f"repomap-control-schema:{CONTROL_SCHEMA_VERSION}")
        prohibited = {
            "root_path", "database_name", "connection_string", "credential", "command",
            "sql", "source_text", "graph_payload", "raw_observation", "backup_receipt",
        }
        self.assertTrue(prohibited.isdisjoint(columns))
        self.assertEqual(ledger, [
            (m.ordinal, m.changeset_id, m.relative_path, m.checksum)
            for m in discover_control_migrations()
        ])

    def test_preledger_adoption_requires_backup_and_exact_catalog(self):
        with self._connect() as connection:
            connection.execute(migration_text())
        self.assertEqual(self.store.schema_readiness().status, ControlSchemaStatus.PRELEDGER)
        manifest = self.store.schema_manifest()
        with self.assertRaisesRegex(ControlSchemaError, "verified backup"):
            self.store.adopt_preledger_schema(expected_manifest=manifest, backup_verified=False)
        with self.assertRaisesRegex(ControlSchemaError, "unsupported pre-ledger"):
            self.store.adopt_preledger_schema(expected_manifest=("different",), backup_verified=True)
        self.store.adopt_preledger_schema(expected_manifest=manifest, backup_verified=True)
        self.assertEqual(self.store.schema_readiness().status, ControlSchemaStatus.CURRENT)

    def test_schema_failure_rolls_back_every_control_table(self):
        with self.assertRaises(psycopg.Error):
            self.store.initialize_schema(migration_sql="CREATE TABLE jobs(id integer); SELECT 1 / 0;")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

    def test_incompatible_schema_version_is_rejected(self):
        self.store.initialize_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("COMMENT ON TABLE jobs IS 'repomap-control-schema:999'")
        with self.assertRaisesRegex(ControlSchemaError, "incompatible control schema"):
            self.store.check_schema_version()

    def test_submit_replays_identical_request_and_rejects_conflict(self):
        self.store.initialize_schema()
        first = self.store.submit(self._request(request_id="request-1"))
        replay = self.store.submit(self._request(request_id="request-1"))
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.job_id, first.job_id)
        with self.assertRaisesRegex(ValueError, "idempotency conflict"):
            self.store.submit(self._request(request_id="request-2"))

    def test_claims_are_ordered_and_exclude_same_graph(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        first = self.store.submit(self._request(graph_id="synthetic-a", key="one"))
        second = self.store.submit(self._request(graph_id="synthetic-a", key="two"))
        third = self.store.submit(self._request(graph_id="synthetic-b", key="three"))
        claim_one = self._claim("instance-a", epoch)
        claim_two = self._claim("instance-a", epoch)

        self.assertEqual(claim_one.job_id, first.job_id)
        self.assertEqual(claim_one.attempt, 1)
        self.assertEqual(claim_two.job_id, third.job_id)
        self.assertNotEqual(claim_two.job_id, second.job_id)
        self.assertNotEqual(claim_one.graph_lease_fencing_epoch, epoch)
        self.assertLess(claim_one.graph_lease_fencing_epoch, claim_two.graph_lease_fencing_epoch)
        self.assertEqual(self.store.status(second.job_id).state, "queued")

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM job_attempts WHERE is_current")
            attempts = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM graph_leases")
            leases = cursor.fetchone()[0]
        self.assertEqual((attempts, leases), (2, 2))

    def test_claim_skips_a_locked_older_row(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        older = self.store.submit(self._request(graph_id="synthetic-a", key="one"))
        newer = self.store.submit(self._request(graph_id="synthetic-b", key="two"))
        with self._connect() as lock_connection, lock_connection.cursor() as cursor:
            cursor.execute("SELECT job_id FROM jobs WHERE job_id = %s FOR UPDATE", (older.job_id,))
            claim = self._claim("instance-a", epoch)
        self.assertEqual(claim.job_id, newer.job_id)

    def test_schema_constraints_reject_unknown_kind_and_state(self):
        self.store.initialize_schema()
        submitted = self.store.submit(self._request())
        with self._connect() as connection:
            with self.assertRaises(psycopg.errors.CheckViolation), connection.transaction(), connection.cursor() as cursor:
                cursor.execute("UPDATE jobs SET job_kind = 'drop_database' WHERE job_id = %s", (submitted.job_id,))
            with self.assertRaises(psycopg.errors.CheckViolation), connection.transaction(), connection.cursor() as cursor:
                cursor.execute("UPDATE jobs SET state = 'unknown' WHERE job_id = %s", (submitted.job_id,))

    def test_singleton_takeover_fences_stale_owner_and_release_is_conditional(self):
        self.store.initialize_schema()
        epoch_one = self.store.acquire_singleton(
            "instance-a", timedelta(seconds=30)
        )
        submitted = self.store.submit(self._request())
        claim = self._claim("instance-a", epoch_one)
        self.assertEqual(claim.job_id, submitted.job_id)

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
        epoch_two = self.store.acquire_singleton("instance-b", timedelta(seconds=30))
        self.assertGreater(epoch_two, epoch_one)
        self.assertFalse(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="starting",
                attempt=claim.attempt,
                instance_id="instance-a",
                fencing_epoch=epoch_one,
            )
        )
        self.assertFalse(
            self.store.release_graph_lease(
                claim.graph_id,
                claim.job_id,
                claim.attempt,
                "instance-a",
                epoch_one,
                reconciler_instance_id="instance-b",
                reconciler_epoch=epoch_two,
            )
        )

    def test_singleton_takeover_recovers_safely_unpublished_attempt(self):
        self.store.initialize_schema()
        epoch_one = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = self.store.submit(self._request())
        claim = self._claim("instance-a", epoch_one)
        self.assertEqual(claim.job_id, submitted.job_id)

        with self._connect() as connection:
            connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
        epoch_two = self.store.acquire_singleton("instance-b", timedelta(seconds=30))

        self.assertEqual(self.store.recover_abandoned_attempts("instance-b", epoch_two, 1000), 1)
        recovered = self.store.reconciliation_claims(1000)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(
            (recovered[0].job_id, recovered[0].attempt, recovered[0].instance_id, recovered[0].fencing_epoch),
            (claim.job_id, claim.attempt, claim.instance_id, claim.fencing_epoch),
        )
        self.assertEqual(
            self.store.reconcile_publication(
                claim,
                reconciler_instance_id="instance-b",
                reconciler_epoch=epoch_two,
            ),
            "queued",
        )
        status = self.store.status(submitted.job_id)
        self.assertEqual((status.state, status.attempt), ("queued", 1))
        with self._connect() as connection:
            attempt = connection.execute(
                "SELECT is_current, finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s AND attempt = 1",
                (submitted.job_id,),
            ).fetchone()
            lease_count = connection.execute(
                "SELECT count(*) FROM graph_leases WHERE job_id = %s",
                (submitted.job_id,),
            ).fetchone()[0]
        self.assertEqual(attempt, (False, True))
        self.assertEqual(lease_count, 0)

    def test_fenced_heartbeat_progress_cancellation_and_reconciliation(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = self.store.submit(self._request())
        claim = self._claim("instance-a", epoch)

        self.assertTrue(
            self.store.heartbeat_attempt(
                claim, timedelta(seconds=30), phase="discovery", completed=2, total=5
            )
        )
        status = self.store.status(submitted.job_id)
        self.assertEqual((status.phase, status.completed, status.total), ("discovery", 2, 5))
        self.assertEqual(self.store.request_cancellation(submitted.job_id), "cancel_requested")
        self.assertTrue(
            self.store.mark_reconciliation_required(
                claim, expected_state="cancel_requested", category="publication_unknown"
            )
        )

    def test_publication_markers_are_idempotent_and_cleanup_has_dry_run(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = self.store.submit(self._request())
        claim = self._claim("instance-a", epoch)
        marker = {
            "run_identity": "run-1",
            "source_generation": self._request().source_generation,
            "config_generation": self._request().config_generation,
            "extractor_generation": "eg1:synthetic",
            "canonicalizer_generation": "kg1:synthetic",
            "outcome": "committed",
        }
        self.assertTrue(self.store.record_publication_marker(claim, **marker))
        self.assertFalse(self.store.record_publication_marker(claim, **marker))
        with self.assertRaisesRegex(ValueError, "publication marker conflict"):
            self.store.record_publication_marker(
                claim, **{**marker, "run_identity": "run-2"}
            )
        self.assertTrue(
            self.store.compare_and_set_state(
                submitted.job_id,
                expected_state="claimed",
                new_state="reconciliation_required",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
            )
        )
        self.assertTrue(
            self.store.compare_and_set_state(
                submitted.job_id,
                expected_state="reconciliation_required",
                new_state="succeeded",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="committed",
            )
        )
        self.assertTrue(
            self.store.release_graph_lease(
                claim.graph_id,
                claim.job_id,
                claim.attempt,
                claim.instance_id,
                claim.fencing_epoch,
                reconciler_instance_id=claim.instance_id,
                reconciler_epoch=claim.fencing_epoch,
            )
        )
        dry_run = self.store.cleanup_terminal(timedelta(seconds=0), limit=10, dry_run=True)
        self.assertEqual(dry_run, (submitted.job_id,))
        self.assertEqual(self.store.status(submitted.job_id).state, "succeeded")

    def test_safe_retry_closes_attempt_and_releases_matching_lease(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = self.store.submit(self._request())
        claim = self._claim("instance-a", epoch)
        self.assertTrue(
            self.store.compare_and_set_state(
                submitted.job_id,
                expected_state="claimed",
                new_state="starting",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
            )
        )
        self.assertTrue(
            self.store.schedule_retry(
                claim,
                expected_state="starting",
                delay=timedelta(seconds=0),
                category="transient",
            )
        )
        second_claim = self._claim("instance-a", epoch)
        self.assertEqual((second_claim.job_id, second_claim.attempt), (submitted.job_id, 2))

    @staticmethod
    def _request(
        *,
        graph_id: str = "synthetic-a",
        key: str = "same-key",
        request_id: str = "request-1",
    ) -> JobRequest:
        return normalize_request(
            {
                "schema_version": 1,
                "job_kind": "refresh_graph",
                "graph_id": graph_id,
                "request_id": request_id,
                "idempotency_key": key,
                "priority": "manual",
                "operation_options": {"reason": "operator-request"},
            },
            source_generation="sg1:" + hashlib.sha256(b"source").hexdigest(),
            config_generation="cg1:" + hashlib.sha256(b"config").hexdigest(),
        )
