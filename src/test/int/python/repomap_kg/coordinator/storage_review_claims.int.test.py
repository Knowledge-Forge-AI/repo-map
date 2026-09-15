from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import psycopg

from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.storage import (
    ControlStoreError,
    SingletonActiveError,
)
from src.test.int.python.repomap_kg.coordinator.storage_review_fixtures import (
    StorageReviewIntegrationBase,
)


class ControlStoreReviewClaimsIntegrationTests(StorageReviewIntegrationBase):
    def test_live_singleton_reacquire_is_rejected_for_same_instance_id(self):
        self.store.initialize_schema()
        self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        with self.assertRaises(SingletonActiveError):
            self.store.acquire_singleton("instance-a", timedelta(seconds=30))

    def test_release_requires_current_reconciler_and_safe_terminal_state(self):
        claim = self._claimed_job()
        self.assertFalse(
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
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="reconciliation_required",
                new_state="failed",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
                publication_state="rolled_back",
            )
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE coordinator_instances "
                    "SET expires_at = now() - interval '1 second'"
                )
        next_epoch = self.store.acquire_singleton(
            "instance-b", timedelta(seconds=30)
        )
        self.assertTrue(
            self.store.release_graph_lease(
                claim.graph_id,
                claim.job_id,
                claim.attempt,
                claim.instance_id,
                claim.fencing_epoch,
                reconciler_instance_id="instance-b",
                reconciler_epoch=next_epoch,
            )
        )

    def test_unexpected_claim_uniqueness_is_not_swallowed(self):
        self.store.initialize_schema()
        self.store.acquire_singleton("instance-a", timedelta(seconds=30))
        with patch.object(
            self.store,
            "_claim_once",
            side_effect=psycopg.errors.UniqueViolation("unexpected unique"),
        ):
            with self.assertRaisesRegex(
                ControlStoreError, "unexpected control-store uniqueness violation"
            ):
                self.store.claim_next(
                    "instance-a", 1, timedelta(seconds=30)
                )

    def test_claim_limits_and_retry_policy_fail_closed(self):
        self.store.initialize_schema()
        epoch = self.store.acquire_singleton(
            "instance-a", timedelta(seconds=30)
        )
        manual = self.store.submit(self._request(key="manual-limit"))
        self.assertIsNone(
            self.store.claim_next(
                "instance-a",
                epoch,
                timedelta(seconds=30),
                automatic_only=True,
            )
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET current_attempt = %s WHERE job_id = %s",
                    (DEFAULT_LIMITS.max_retry_attempts, manual.job_id),
                )
        self.assertIsNone(
            self.store.claim_next(
                "instance-a", epoch, timedelta(seconds=30)
            )
        )

        retry_job = self.store.submit(
            self._request(graph_id="synthetic-retry", key="retry")
        )
        claim = self.store.claim_next(
            "instance-a", epoch, timedelta(seconds=30)
        )
        assert claim is not None
        self.assertEqual(claim.job_id, retry_job.job_id)
        self.assertTrue(
            self.store.compare_and_set_state(
                claim.job_id,
                expected_state="claimed",
                new_state="starting",
                attempt=claim.attempt,
                instance_id=claim.instance_id,
                fencing_epoch=claim.fencing_epoch,
            )
        )
        with self.assertRaisesRegex(ValueError, "retry is not permitted"):
            self.store.schedule_retry(
                claim,
                expected_state="starting",
                delay=timedelta(0),
                category="permanent",
            )

    def test_replacement_singleton_reconciles_stale_attempt_owner_tuple(self):
        claim = self._claimed_job("synthetic-takeover-reconcile")
        self.assertTrue(
            self.store.mark_reconciliation_required(
                claim,
                expected_state="claimed",
                category="publication_unknown",
            )
        )
        self.store.record_publication_marker(
            claim, **self._publication_marker()
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE coordinator_instances "
                    "SET expires_at = now() - interval '1 second'"
                )
        replacement_epoch = self.store.acquire_singleton(
            "instance-b", timedelta(seconds=30)
        )
        self.assertTrue(
            self.store.mark_attempt_terminated(
                claim,
                process_cleanup_proved=True,
                reconciler_instance_id="instance-b",
                reconciler_epoch=replacement_epoch,
            )
        )
        self.assertEqual(
            self.store.reconcile_publication(
                claim,
                reconciler_instance_id="instance-b",
                reconciler_epoch=replacement_epoch,
            ),
            "succeeded",
        )
