from __future__ import annotations

import unittest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.staging import STAGING_FAMILIES
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    build_staged_rows,
    stage_id_for_authority,
)


class Scale8StagedIngestionUnitTests(unittest.TestCase):
    def test_row_families_are_complete_and_checksums_ignore_stage_identity(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={"language": "markdown", "role": "documentation"},
            )
        ]

        first = build_staged_rows(
            observations,
            repository_name="fixture",
            stage_id="stage-first",
        )
        second = build_staged_rows(
            observations,
            repository_name="fixture",
            stage_id="stage-second",
        )

        self.assertEqual(tuple(first.family_rows), STAGING_FAMILIES)
        self.assertEqual(first.row_counts["files"], 1)
        self.assertEqual(first.row_counts["raw_observations"], 1)
        self.assertEqual(first.files, 1)
        self.assertEqual(tuple(first.privacy_classifications), STAGING_FAMILIES)
        self.assertNotIn(
            PrivacyClassification.PUBLIC,
            first.privacy_classifications.values(),
        )
        self.assertEqual(first.checksums, second.checksums)
        self.assertEqual(first.normalized_byte_counts, second.normalized_byte_counts)
        self.assertEqual(
            {row["stage_id"] for row in first.family_rows["files"]},
            {"stage-first"},
        )
        self.assertEqual(
            {row["stage_id"] for row in second.family_rows["files"]},
            {"stage-second"},
        )

    def test_coordinator_authority_round_trips_exact_fencing_and_receipt(self):
        authority = IngestionAuthority(
            operation_id=OperationId("job-scale8"),
            attempt=AttemptNumber(3),
            execution_mode="coordinator",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
            job_id=JobId("job-scale8"),
            coordinator_instance_id="coord-scale8",
            singleton_fencing_epoch=11,
            graph_lease_fencing_epoch=11,
        )

        owner = authority.owner(repository_id=7)
        receipt = authority.receipt()

        self.assertEqual(owner.job_id, "job-scale8")
        self.assertEqual(owner.coordinator_instance_id, "coord-scale8")
        self.assertEqual(owner.singleton_fencing_epoch, 11)
        self.assertEqual(owner.graph_lease_fencing_epoch, 11)
        self.assertEqual(receipt.attempt.job_id, "job-scale8")
        self.assertEqual(receipt.attempt.attempt, 3)
        self.assertEqual(
            receipt.generations.values(),
            (
                "sg1:source",
                "cg1:config",
                "eg1:extractor",
                "kg1:canonicalizer",
            ),
        )

    def test_duplicate_proposals_remain_available_for_set_based_validation(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "markdown",
                    "role": "documentation",
                    "content_hash": "a" * 64,
                },
            ),
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="manual",
                extractor="manual-review",
                extractor_version="0.2.0",
                metadata={
                    "language": "markdown",
                    "role": "source",
                    "content_hash": "b" * 64,
                },
            ),
        ]

        prepared = build_staged_rows(
            observations,
            repository_name="fixture",
            stage_id="stage-duplicates",
        )

        self.assertEqual(prepared.row_counts["files"], 2)
        self.assertEqual(prepared.row_counts["raw_observations"], 2)
        self.assertEqual(prepared.checksums["files"].row_count, 2)

    def test_stage_identity_is_stable_for_one_operation_attempt(self):
        authority = IngestionAuthority(
            operation_id=OperationId("job-scale8"),
            attempt=AttemptNumber(3),
            execution_mode="coordinator",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
            job_id=JobId("job-scale8"),
            coordinator_instance_id="coord-scale8",
            singleton_fencing_epoch=11,
            graph_lease_fencing_epoch=11,
        )

        self.assertEqual(
            stage_id_for_authority(authority),
            stage_id_for_authority(authority),
        )


if __name__ == "__main__":
    unittest.main()
