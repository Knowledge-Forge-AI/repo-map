from __future__ import annotations

import hashlib
import unittest
from datetime import timedelta
import psycopg

from repomap_kg.coordinator import JobRequest, normalize_request
from repomap_kg.coordinator.storage import ControlStore, SingletonActiveError
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


class StorageReviewIntegrationBase(unittest.TestCase):
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


    def _claimed_job(self, graph_id: str = "synthetic-a"):
        self.store.initialize_schema()
        try:
            epoch = self.store.acquire_singleton(
                "instance-a", timedelta(seconds=30)
            )
        except SingletonActiveError:
            epoch = 1
        self.store.submit(self._request(graph_id=graph_id, key=graph_id))
        return self.store.claim_next(
            "instance-a", epoch, timedelta(seconds=30)
        )


    def _terminal_job(self, graph_id: str, *, release: bool) -> str:
        claim = self._claimed_job(graph_id)
        self.store.compare_and_set_state(
            claim.job_id,
            expected_state="claimed",
            new_state="reconciliation_required",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
        )
        self.store.compare_and_set_state(
            claim.job_id,
            expected_state="reconciliation_required",
            new_state="failed",
            attempt=claim.attempt,
            instance_id=claim.instance_id,
            fencing_epoch=claim.fencing_epoch,
            publication_state="rolled_back",
        )
        if release:
            self.store.release_graph_lease(
                claim.graph_id,
                claim.job_id,
                claim.attempt,
                claim.instance_id,
                claim.fencing_epoch,
                reconciler_instance_id=claim.instance_id,
                reconciler_epoch=claim.fencing_epoch,
            )
        return claim.job_id


    def _assert_publication_state_parity(self, claim, expected: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT j.publication_state, a.publication_state "
                    "FROM jobs AS j JOIN job_attempts AS a "
                    "ON a.job_id = j.job_id AND a.attempt = j.current_attempt "
                    "WHERE j.job_id = %s AND a.is_current",
                    (claim.job_id,),
                )
                self.assertEqual(cursor.fetchone(), (expected, expected))


    def _publication_marker(self) -> dict[str, str]:
        request = self._request()
        return {
            "run_identity": "run-1",
            "source_generation": request.source_generation,
            "config_generation": request.config_generation,
            "extractor_generation": "eg1:synthetic",
            "canonicalizer_generation": "kg1:synthetic",
            "outcome": "committed",
        }


    @staticmethod
    def _request(
        *,
        graph_id: str = "synthetic-a",
        key: str = "key",
        priority: str = "manual",
        source_seed: bytes = b"source",
    ) -> JobRequest:
        return normalize_request(
            {
                "schema_version": 1,
                "job_kind": "refresh_graph",
                "graph_id": graph_id,
                "request_id": f"request-{key}",
                "idempotency_key": key,
                "priority": priority,
                "operation_options": {"reason": "operator-request"},
            },
            source_generation="sg1:" + hashlib.sha256(source_seed).hexdigest(),
            config_generation="cg1:" + hashlib.sha256(b"config").hexdigest(),
        )

