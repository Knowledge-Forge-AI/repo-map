"""Unit tests for coordinator control startup recovery and reconciliation claims."""

from __future__ import annotations

from typing import Any, cast
import unittest
from unittest.mock import MagicMock

from repomap_kg.coordinator._control_startup import (
    reconciliation_claims,
    recover_abandoned_attempts,
)
from repomap_kg.coordinator._control_types import JobClaim


def _connection_factory(cursor: MagicMock) -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    return MagicMock(return_value=connection)


class ControlStartupRecoveryUnitTests(unittest.TestCase):
    """Test branch paths in recover_abandoned_attempts."""

    def test_limit_validation(self):
        for invalid in (0, -1, "10", False, True, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    recover_abandoned_attempts(
                        connect=MagicMock(),
                        instance_id="inst-1",
                        fencing_epoch=1,
                        limit=cast(Any, invalid),
                    )

    def test_raises_when_replacement_is_not_live_owner(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None  # No matching coordinator instance

        fake_connect = _connection_factory(cursor)

        with self.assertRaises(RuntimeError) as caught:
            recover_abandoned_attempts(
                connect=fake_connect,
                instance_id="inst-1",
                fencing_epoch=1,
                limit=10,
            )
        self.assertIn("replacement coordinator is not the live owner", str(caught.exception))

    def test_recovers_attempts_classifying_not_started_vs_commit_unknown(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)  # Live owner exists
        cursor.fetchall.return_value = [
            {"job_id": "job-1", "current_attempt": 1, "publication_state": "not_started"},
            {"job_id": "job-2", "current_attempt": 2, "publication_state": "prepared"},
        ]
        cursor.rowcount = 1

        fake_connect = _connection_factory(cursor)

        recovered = recover_abandoned_attempts(
            connect=fake_connect,
            instance_id="inst-1",
            fencing_epoch=1,
            limit=5,
        )
        self.assertEqual(recovered, 2)
        # Verify executed updates
        exec_calls = cursor.execute.call_args_list
        # Check job updates
        pub_states = [call[0][1][0] for call in exec_calls if len(call[0]) > 1 and len(call[0][1]) == 3]
        self.assertIn("not_started", pub_states)
        self.assertIn("commit_unknown", pub_states)

    def test_raises_when_job_fencing_update_fails(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            {"job_id": "job-1", "current_attempt": 1, "publication_state": "not_started"},
        ]
        cursor.rowcount = 0  # Failed update

        fake_connect = _connection_factory(cursor)

        with self.assertRaises(RuntimeError) as caught:
            recover_abandoned_attempts(
                connect=fake_connect,
                instance_id="inst-1",
                fencing_epoch=1,
                limit=5,
            )
        self.assertIn("abandoned job fencing failed", str(caught.exception))

    def test_raises_when_attempt_closure_update_fails(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = [
            {"job_id": "job-1", "current_attempt": 1, "publication_state": "not_started"},
        ]
        # First rowcount 1 (job updated), second rowcount 0 (attempt failed)
        type(cursor).rowcount = unittest.mock.PropertyMock(side_effect=[1, 0])

        fake_connect = _connection_factory(cursor)

        with self.assertRaises(RuntimeError) as caught:
            recover_abandoned_attempts(
                connect=fake_connect,
                instance_id="inst-1",
                fencing_epoch=1,
                limit=5,
            )
        self.assertIn("abandoned attempt closure failed", str(caught.exception))


class ReconciliationClaimsUnitTests(unittest.TestCase):
    """Test branch paths in reconciliation_claims."""

    def test_limit_validation(self):
        for invalid in (0, -5, "10", False, True, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    reconciliation_claims(connect=MagicMock(), limit=cast(Any, invalid))

    def test_reconciliation_claims_retrieval(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {
                "job_id": "job-10",
                "graph_id": "graph-a",
                "current_attempt": 1,
                "priority_class": "default",
                "source_generation": "sg1",
                "config_generation": "cg1",
                "extractor_generation": "eg1",
                "canonicalizer_generation": "kg1",
                "coordinator_instance_id": "inst-1",
                "fencing_epoch": 2,
            }
        ]

        fake_connect = _connection_factory(cursor)

        claims = reconciliation_claims(connect=fake_connect, limit=10)
        self.assertEqual(len(claims), 1)
        self.assertIsInstance(claims[0], JobClaim)
        self.assertEqual(claims[0].job_id, "job-10")
        self.assertEqual(claims[0].fencing_epoch, 2)


if __name__ == "__main__":
    unittest.main()
