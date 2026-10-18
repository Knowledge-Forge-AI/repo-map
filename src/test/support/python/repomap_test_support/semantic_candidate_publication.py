"""Real seven-family publication fixture for optional vector boundary tests."""

from __future__ import annotations

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.staged_ingestion import build_staged_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.semantic_candidate_fixtures import BINDING, SNAPSHOT


def candidate_bundle(*, job_id: str = "candidate-publication", revision: int = 1) -> PublicationBundle:
    observations = tuple(
        RawObservation(
            kind="file", source_id=f"{BINDING}:src/{name}.py", path=f"src/{name}.py",
            confidence="extracted", extractor="public-fixture", extractor_version="1",
            metadata={"language": "python", "role": "source", "binding_id": BINDING,
                      "snapshot_id": SNAPSHOT, "binding_revision": revision},
        ) for name in ("a", "b", "c")
    )
    prepared = build_staged_rows(observations, repository_name="candidate-fixture", stage_id="stage-unassigned")
    try:
        families = {family: tuple(dict(row) for row in prepared.family_rows[family])
                    for family in PUBLICATION_FAMILIES}
    finally:
        prepared.close()
    return PublicationBundle.create(
        request_id=job_id, job_id=job_id, attempt=1, graph_id="candidate-fixture",
        candidate_id="cand1:" + str(revision) * 64,
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=((BINDING, revision, SNAPSHOT),),
        source_generation="sg1:fixture" + str(revision), config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        extractor_capability_identity="cap1:public-fixture", resolver_identity="resolver1:fixture",
        canonicalizer_identity="canon1:fixture", semantic_contract_identity="semantic1:fixture",
        quality_rule_identity="quality1:fixture", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families, row_stage_contract="stage-unassigned-v1",
    )
