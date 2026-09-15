"""Unit tests for the pure publication fixture builder."""

from __future__ import annotations

import json
import unittest

from repomap_test_support.publication_fixtures import (
    PublicationFixture,
    json_checksums,
    json_family_manifest,
    json_row_counts,
)


class PublicationFixtureUnitTests(unittest.TestCase):
    """Verify deterministic fixture and SQL generation."""

    def test_default_publication_fixture_attributes(self) -> None:
        fixture = PublicationFixture(stage_id="stage-1", job_id="job-1", attempt=2, run_id=3)
        self.assertEqual(fixture.resolved_coordinator_instance_id, "coord-job-1")
        self.assertEqual(fixture.resolved_source_generation, "sg1:job-1")
        self.assertEqual(fixture.resolved_config_generation, "cg1:job-1")
        self.assertEqual(fixture.resolved_extractor_generation, "eg1:job-1")
        self.assertEqual(fixture.resolved_canonicalizer_generation, "kg1:job-1")

        owner = fixture.owner
        self.assertEqual(owner.repository_id, 1)
        self.assertEqual(owner.operation_id, "job-1")
        self.assertEqual(owner.job_id, "job-1")
        self.assertEqual(owner.attempt, 2)
        self.assertEqual(owner.coordinator_instance_id, "coord-job-1")
        self.assertEqual(owner.singleton_fencing_epoch, 9)
        self.assertEqual(owner.graph_lease_fencing_epoch, 9)

        receipt = fixture.receipt
        self.assertEqual(receipt.attempt.job_id, "job-1")
        self.assertEqual(receipt.attempt.attempt, 2)
        self.assertEqual(receipt.generations.source_generation, "sg1:job-1")
        self.assertIsNone(receipt.portable)

        handoff = fixture.handoff
        self.assertEqual(handoff.merge.stage_id, "stage-1")
        self.assertEqual(handoff.merge.run_id, 3)
        self.assertEqual(handoff.merge.owner, owner)
        self.assertEqual(handoff.receipt, receipt)

    def test_stage_seed_sql_contains_exact_owner_fields(self) -> None:
        fixture = PublicationFixture(
            stage_id="stage-alpha",
            job_id="job-alpha",
            attempt=1,
            run_id=1,
            singleton_epoch=12,
            graph_fence_epoch=14,
        )
        sql = fixture.stage_seed_sql(
            files=3,
            state="commit_unknown",
            merge_status="unknown",
            publication_reconciliation_state="required",
        )
        self.assertIn("'stage-alpha'", sql)
        self.assertIn("'coord-job-alpha'", sql)
        self.assertIn("'sg1:job-alpha'", sql)
        self.assertIn("12", sql)
        self.assertIn("14", sql)
        self.assertIn("'commit_unknown'", sql)
        self.assertIn("'unknown'", sql)
        self.assertIn("'required'", sql)
        self.assertIn('"files":3', sql)

    def test_run_seed_sql_running_and_complete(self) -> None:
        fixture = PublicationFixture(stage_id="stage-beta", job_id="job-beta", attempt=1, run_id=42)
        running_sql = fixture.run_seed_sql(status="running", with_receipt=False)
        self.assertIn("VALUES (42, 1, 'running');", running_sql)
        self.assertNotIn("publication_job_id", running_sql)

        complete_sql = fixture.run_seed_sql(status="complete", with_receipt=True)
        self.assertIn("VALUES (42, 1, 'complete', 'job-beta', 1, 'sg1:job-beta'", complete_sql)

    def test_run_seed_sql_with_portable_binding(self) -> None:
        fixture = PublicationFixture(
            stage_id="stage-portable",
            job_id="job-port",
            singleton_epoch=7,
            graph_fence_epoch=9,
        )
        binding = fixture.create_portable_binding(
            snapshot_manifest_id="snapmanifest1:" + "a" * 64,
            snapshot_vector=(("bind1:" + "b" * 64, 1, "snap1:" + "c" * 64),),
            extraction_receipt_id="receipt1:" + "d" * 64,
            publication_bundle_id="bundle1:" + "e" * 64,
            candidate_id="cand1:" + "f" * 64,
            resolver_identity="resolver1:test",
            canonicalizer_identity="canon1:test",
            semantic_contract_identity="semantic1:test",
            quality_rule_identity="quality1:test",
            worker_capability_identity="cap1:test",
        )
        self.assertEqual(binding.stage_id, fixture.stage_id)
        self.assertEqual(binding.execution_mode, fixture.execution_mode)
        self.assertEqual(binding.singleton_fencing_epoch, fixture.singleton_epoch)
        self.assertEqual(binding.graph_lease_fencing_epoch, fixture.graph_fence_epoch)

        fixture_with_binding = PublicationFixture(
            stage_id="stage-portable",
            job_id="job-port",
            singleton_epoch=7,
            graph_fence_epoch=9,
            portable_binding=binding,
        )
        complete_sql = fixture_with_binding.run_seed_sql(status="complete", with_receipt=True)
        self.assertIn("'portable-worker-v1'", complete_sql)
        self.assertIn("snapmanifest1:" + "a" * 64, complete_sql)
        self.assertIn("bundle1:" + "e" * 64, complete_sql)
        self.assertIn("cand1:" + "f" * 64, complete_sql)

    def test_mismatched_portable_binding_raises_value_error(self) -> None:
        fixture = PublicationFixture(stage_id="stage-1", singleton_epoch=10, graph_fence_epoch=10)
        binding = fixture.create_portable_binding()
        with self.assertRaises(ValueError):
            PublicationFixture(stage_id="stage-diff", singleton_epoch=10, graph_fence_epoch=10, portable_binding=binding)
        with self.assertRaises(ValueError):
            PublicationFixture(stage_id="stage-1", singleton_epoch=9, graph_fence_epoch=10, portable_binding=binding)

    def test_authority_seed_sql(self) -> None:
        fixture = PublicationFixture(
            stage_id="stage-auth",
            job_id="job-auth",
            attempt=3,
            run_id=5,
            singleton_epoch=10,
            graph_fence_epoch=11,
        )
        auth_sql = fixture.authority_seed_sql()
        self.assertIn("INSERT INTO graph_publication_authority", auth_sql)
        self.assertIn("10, 11, 'job-auth', 3, 'coord-job-auth'", auth_sql)
        self.assertIn("'stage-auth', 5", auth_sql)

    def test_custom_overrides(self) -> None:
        fixture = PublicationFixture(
            stage_id="stage-custom",
            job_id="job-custom",
            coordinator_instance_id="coord-override",
            source_generation="sg1:override",
            config_generation="cg1:override",
            extractor_generation="eg1:override",
            canonicalizer_generation="kg1:override",
        )
        self.assertEqual(fixture.resolved_coordinator_instance_id, "coord-override")
        self.assertEqual(fixture.owner.coordinator_instance_id, "coord-override")
        self.assertEqual(fixture.owner.source_generation, "sg1:override")
        self.assertEqual(fixture.receipt.generations.source_generation, "sg1:override")

    def test_json_helpers(self) -> None:
        counts = json.loads(json_row_counts(files=5))
        self.assertEqual(len(counts), 7)
        self.assertEqual(counts["files"], 5)
        self.assertEqual(counts["canonical_nodes"], 0)

        checksums = json.loads(json_checksums())
        self.assertEqual(len(checksums), 7)
        self.assertEqual(checksums["files"]["stable_key_digest"], "0" * 64)

        manifest = json.loads(json_family_manifest())
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(len(manifest["families"]), 7)


if __name__ == "__main__":
    unittest.main()
