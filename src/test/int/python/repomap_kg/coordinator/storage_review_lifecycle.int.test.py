from __future__ import annotations

from datetime import timedelta

from psycopg import sql

from src.test.int.python.repomap_kg.coordinator.storage_review_fixtures import (
    StorageReviewIntegrationBase,
)


class ControlStoreReviewLifecycleIntegrationTests(StorageReviewIntegrationBase):
    def test_success_requires_committed_publication_and_closes_attempt(self):
        claim = self._claimed_job()
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="reconciliation_required",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
            )
        )
        self.assertFalse(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="reconciliation_required",
                new_state="succeeded",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="committed",
            )
        )
        self.store.record_publication_marker(
            claim,
            **self._publication_marker(),
        )
        with self.assertRaisesRegex(ValueError, "succeeded.*committed"):
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="reconciliation_required",
                new_state="succeeded",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
            )
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="reconciliation_required",
                new_state="succeeded",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="committed",
            )
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT is_current, finished_at IS NOT NULL, publication_state "
                    "FROM job_attempts WHERE job_id = %s AND attempt = %s",
                    (claim.job_id, claim.attempt),
                )
                self.assertEqual(cursor.fetchone(), (False, True, "committed"))

    def test_success_rejects_nonmatching_committed_publication_markers(self):
        mismatches = (
            ("graph_id", "synthetic-other"),
            ("source_generation", "sg1:other"),
            ("config_generation", "cg1:other"),
            ("extractor_generation", "eg1:other"),
            ("canonicalizer_generation", "kg1:other"),
            ("outcome", "conflicting"),
        )
        for index, (field, value) in enumerate(mismatches):
            with self.subTest(field=field):
                claim = self._claimed_job(f"synthetic-mismatch-{index}")
                self.assertTrue(
                    self.store.compare_and_set_state(
                        claim.job_id,
                        expected_state="claimed",
                        new_state="reconciliation_required",
                        attempt=claim.attempt,
                        instance_id=claim.instance_id,
                        fencing_epoch=claim.fencing_epoch,
                    )
                )
                self.store.record_publication_marker(
                    claim, **self._publication_marker()
                )
                with self._connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                "UPDATE synthetic_publication_markers "
                                "SET {} = %s WHERE job_id = %s AND attempt = %s"
                            ).format(sql.Identifier(field)),
                            (value, claim.job_id, claim.attempt),
                        )

                self.assertFalse(
                    self.store.compare_and_set_state(
                        claim.job_id,
                        expected_state="reconciliation_required",
                        new_state="succeeded",
                        attempt=claim.attempt,
                        instance_id=claim.instance_id,
                        fencing_epoch=claim.fencing_epoch,
                        publication_state="committed",
                    )
                )

    def test_publication_state_changes_update_current_attempt_atomically(self):
        claim = self._claimed_job()

        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="starting",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="transaction_started",
            )
        )
        self._assert_publication_state_parity(claim, "transaction_started")

        self.assertTrue(
            self.store.mark_reconciliation_required(
                claim,
                expected_state="starting",
                category="publication_unknown",
            )
        )
        self._assert_publication_state_parity(claim, "commit_unknown")

    def test_retry_preserves_closing_attempt_publication_evidence(self):
        claim = self._claimed_job()
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="starting",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="prepared",
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

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT j.publication_state, a.publication_state, "
                    "a.is_current, a.finished_at IS NOT NULL "
                    "FROM jobs AS j JOIN job_attempts AS a ON a.job_id = j.job_id "
                    "WHERE j.job_id = %s AND a.attempt = %s",
                    (claim.job_id, claim.attempt),
                )
                self.assertEqual(
                    cursor.fetchone(),
                    ("not_started", "prepared", False, True),
                )

    def test_retry_rejects_commit_unknown(self):
        claim = self._claimed_job()
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="reconciliation_required",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="commit_unknown",
            )
        )
        with self.assertRaisesRegex(ValueError, "commit_unknown"):
            self.store.schedule_retry(
                claim,
                expected_state="reconciliation_required",
                delay=timedelta(seconds=0),
                category="transient",
            )

    def test_cleanup_apply_deletes_only_safe_unleased_terminal_jobs(self):
        deletable = self._terminal_job("synthetic-delete", release=True)
        leased = self._terminal_job("synthetic-leased", release=False)
        active = self.store.submit(self._request(graph_id="synthetic-active", key="active"))

        deleted = self.store.cleanup_terminal(
            timedelta(seconds=0), limit=10, dry_run=False
        )

        self.assertEqual(deleted, (deletable,))
        with self.assertRaises(KeyError):
            self.store.status(deletable)
        self.assertEqual(self.store.status(leased).state, "failed")
        self.assertEqual(self.store.status(active.job_id).state, "queued")

    def test_reconciliation_classifies_persisted_marker_and_termination_evidence(self):
        absent = self._claimed_job("synthetic-reconcile-absent")
        self.assertTrue(
            self.store.mark_reconciliation_required(
                absent,
                expected_state="claimed",
                category="publication_unknown",
            )
        )
        self.assertEqual(
            self.store.reconcile_publication(absent),
            "reconciliation_required",
        )
        self.assertTrue(
            self.store.mark_attempt_terminated(
                absent, process_cleanup_proved=True
            )
        )
        self.assertEqual(
            self.store.reconcile_publication(absent),
            "reconciliation_required",
        )

        committed = self._claimed_job("synthetic-reconcile-committed")
        self.assertTrue(
            self.store.mark_reconciliation_required(
                committed,
                expected_state="claimed",
                category="publication_unknown",
            )
        )
        marker = self._publication_marker()
        self.store.record_publication_marker(committed, **marker)
        self.assertTrue(
            self.store.mark_attempt_terminated(
                committed, process_cleanup_proved=True
            )
        )
        self.assertEqual(
            self.store.reconcile_publication(committed), "succeeded"
        )

        conflicting = self._claimed_job("synthetic-reconcile-conflict")
        self.assertTrue(
            self.store.mark_reconciliation_required(
                conflicting,
                expected_state="claimed",
                category="publication_unknown",
            )
        )
        self.store.record_publication_marker(
            conflicting, **{**marker, "outcome": "conflicting"}
        )
        self.assertTrue(
            self.store.mark_attempt_terminated(
                conflicting, process_cleanup_proved=True
            )
        )
        self.assertEqual(
            self.store.reconcile_publication(conflicting), "quarantined"
        )
        with self.assertRaisesRegex(ValueError, "graph intent is paused"):
            self.store.coalesce_automatic(
                self._request(
                    graph_id=conflicting.graph_id,
                    key="blocked-after-conflict",
                    priority="automatic",
                )
            )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT paused FROM coalescing_state WHERE graph_id = %s",
                    (conflicting.graph_id,),
                )
                self.assertEqual(cursor.fetchone(), (True,))

    def test_cleanup_refusal_preserves_evidence_until_terminal_reconciliation(self):
        claim = self._claimed_job("synthetic-cleanup-reconciled")
        self.assertTrue(self.store.mark_reconciliation_required(
            claim, expected_state="claimed", category="publication_unknown",
        ))
        self.store.record_publication_marker(claim, **self._publication_marker())
        self.assertEqual(self.store.reconcile_publication(claim), "reconciliation_required")
        self.assertEqual(self.store.cleanup_terminal(
            timedelta(seconds=0), limit=10, dry_run=False,
        ), ())
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_current, finished_at IS NOT NULL, publication_state "
                "FROM job_attempts WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            )
            self.assertEqual(cursor.fetchone(), (True, False, "commit_unknown"))
            cursor.execute(
                "SELECT outcome FROM synthetic_publication_markers "
                "WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            )
            self.assertEqual(cursor.fetchone(), ("committed",))
        self.assertFalse(self.store.release_graph_lease(
            claim.graph_id, claim.job_id, claim.attempt,
            claim.instance_id, claim.fencing_epoch,
            reconciler_instance_id=claim.instance_id,
            reconciler_epoch=claim.fencing_epoch + 1,
        ))
        self.assertEqual(self.store.cleanup_terminal(
            timedelta(seconds=0), limit=10, dry_run=False,
        ), ())
        self.assertTrue(self.store.mark_attempt_terminated(
            claim, process_cleanup_proved=True,
        ))
        self.assertEqual(self.store.reconcile_publication(claim), "succeeded")
        self.assertEqual(self.store.cleanup_terminal(
            timedelta(seconds=0), limit=10, dry_run=False,
        ), (claim.job_id,))
        with self._connect() as connection, connection.cursor() as cursor:
            for table in ("jobs", "job_attempts", "synthetic_publication_markers", "graph_leases"):
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {} WHERE job_id = %s").format(
                        sql.Identifier(table),
                    ),
                    (claim.job_id,),
                )
                self.assertEqual(cursor.fetchone(), (0,), table)
        self.assertEqual(self.store.cleanup_terminal(
            timedelta(seconds=0), limit=10, dry_run=False,
        ), ())
