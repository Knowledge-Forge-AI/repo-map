from __future__ import annotations

import pytest

from repomap_kg.artifacts import (
    MemoryArtifactStore,
    PublicationBundle,
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.observations.raw import ObservationValidationError, RawObservation
from repomap_kg.storage.portable_ingestion import prepare_portable_bundle_rows
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily


VECTOR = (("bind1:" + "1" * 64, 1, "snap1:" + "2" * 64),)
FAMILIES: dict[StageFamily, tuple[dict[str, object], ...]] = {
    "files": ({
        "family_ordinal": 0, "path": "entry::flake.nix", "language": "nix", "role": "source",
        "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False,
        "generated": False, "metadata_json": {"binding_id": VECTOR[0][0], "snapshot_id": VECTOR[0][2]},
    },),
    "raw_observations": ({
        "source_ordinal": 0, "schema_version": 1, "kind": "nix.input_reference", "source_id": "obs1",
        "path": "entry::flake.nix",
        "payload_json": {
            "candidate_id": "cand1:" + "3" * 64, "resolution_outcome": "ambiguous",
            "resolution_evidence_class": "bounded-unknown", "source_binding_id": VECTOR[0][0],
        },
        "payload_hash": "sha256:" + "b" * 64,
    },),
    "canonical_nodes": ({
        "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::flake.nix",
        "kind": "File", "display_name": "flake.nix", "metadata_json": {"source_binding_id": VECTOR[0][0]},
        "confidence": "exact", "conflict": False,
    },),
    "canonical_edges": (),
    "canonical_evidence": ({
        "family_ordinal": 0, "graph_key_version": 1, "evidence_key": "evidence:1",
        "raw_observation_ordinal": 0, "raw_schema_version": 1, "raw_kind": "nix.input_reference",
        "raw_source_id": "obs1", "path": "entry::flake.nix", "start_line": 1, "end_line": 1,
        "extractor": "nix-static", "extractor_version": "1", "confidence": "exact",
        "metadata_json": {"source_binding_id": VECTOR[0][0]},
    },),
    "canonical_node_evidence": ({
        "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::flake.nix",
        "evidence_key": "evidence:1", "link_kind": "supports",
    },),
    "canonical_edge_evidence": (),
}


def bundle(
    *,
    families: dict[StageFamily, tuple[dict[str, object], ...]] = FAMILIES,
    quality: str = "quality1:default",
    row_stage_contract: str = "legacy-absent-v1",
) -> PublicationBundle:
    return PublicationBundle.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id="cand1:" + "3" * 64, snapshot_manifest_id="snapmanifest1:" + "4" * 64,
        snapshot_vector=VECTOR, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity=quality, privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families, row_stage_contract=row_stage_contract,
    )


def receipt(bundle_ref: object, value: PublicationBundle) -> ExtractionReceipt:
    from repomap_kg.artifacts.references import ArtifactReference

    assert isinstance(bundle_ref, ArtifactReference)
    return ExtractionReceipt.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        source_generation=value.source_generation, config_generation=value.config_generation,
        extractor_generation=value.extractor_generation,
        canonicalizer_generation=value.canonicalizer_generation,
        snapshot_manifest_id=value.snapshot_manifest_id,
        snapshot_vector=value.snapshot_vector, resolver_identity=value.resolver_identity,
        extractor_capability_identity=value.extractor_capability_identity,
        canonicalizer_identity=value.canonicalizer_identity,
        semantic_contract_identity=value.semantic_contract_identity,
        quality_rule_identity=value.quality_rule_identity, outcome="completed",
        cancellation="not-requested", bundle_reference=bundle_ref,
        bundle_id=value.bundle_id, family_counts=value.family_counts,
        diagnostic_category=None, diagnostic_summary=(),
        producer_identity="producer1:conformance-python",
        attestation_class="untrusted-self-assertion",
    )


def put_bundle(store: MemoryArtifactStore, value: PublicationBundle):
    return store.put(
        value.canonical_bytes(),
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1",
        privacy=value.privacy,
    )


def put_receipt(store: MemoryArtifactStore, value: ExtractionReceipt):
    return store.put(
        value.canonical_bytes(),
        media_type="application/x-repomap-extraction-receipt-v1+json",
        record_format="canonical-json-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )


def test_bundle_bytes_are_order_independent_and_round_trip_all_families() -> None:
    value = bundle()
    reordered = {name: tuple(reversed(rows)) for name, rows in reversed(tuple(FAMILIES.items()))}
    second = bundle(families=reordered)

    assert value.canonical_bytes() == second.canonical_bytes()
    assert value.bundle_id == second.bundle_id
    assert PublicationBundle.from_bytes(value.canonical_bytes()) == value
    raw_list = PublicationBundle.from_bytes(value.canonical_bytes()).families["raw_observations"]
    assert len(raw_list) > 0
    raw = raw_list[0]
    raw_payload = raw.get("payload_json")
    assert isinstance(raw_payload, dict)
    assert raw_payload["resolution_outcome"] == "ambiguous"
    assert raw_payload["source_binding_id"] == VECTOR[0][0]


def test_bundle_identity_changes_for_each_semantic_role_and_schema() -> None:
    value = bundle()

    assert bundle(quality="quality1:strict").bundle_id != value.bundle_id
    assert value.with_schema_version_for_test(2).bundle_id != value.bundle_id


def test_bundle_stage_identity_is_non_authoritative_and_smuggling_fails_closed() -> None:
    portable_families: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: tuple({"stage_id": "stage-unassigned", **row} for row in rows)
        for family, rows in FAMILIES.items()
    }
    value = bundle(
        families=portable_families,
        row_stage_contract="stage-unassigned-v1",
    )
    store = MemoryArtifactStore()
    bundle_ref = put_bundle(store, value)
    receipt_ref = put_receipt(store, receipt(bundle_ref, value))
    validator = PublisherBundleValidator()

    accepted = validator.validate_bundle(
        store=store,
        bundle_reference=bundle_ref,
        receipt_reference=receipt_ref,
        expectation=PublicationExpectation.from_bundle(value, mutating_owner_count=1),
    )
    assert accepted.semantic_authority_valid

    smuggled_families: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: tuple(
            ({**row, "stage_id": "publisher-selected-stage"} if rows else row)
            for row in rows
        )
        for family, rows in portable_families.items()
    }
    smuggled = bundle(
        families=smuggled_families,
        row_stage_contract="stage-unassigned-v1",
    )
    smuggled_ref = put_bundle(store, smuggled)
    smuggled_receipt_ref = put_receipt(store, receipt(smuggled_ref, smuggled))
    with pytest.raises(ValueError, match="stage identity"):
        validator.validate_bundle(
            store=store,
            bundle_reference=smuggled_ref,
            receipt_reference=smuggled_receipt_ref,
            expectation=PublicationExpectation.from_bundle(smuggled, mutating_owner_count=1),
        )


def test_publisher_projects_one_generated_stage_across_all_seven_families() -> None:
    portable_families: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: tuple({"stage_id": "stage-unassigned", **row} for row in rows)
        for family, rows in FAMILIES.items()
    }
    value = bundle(
        families=portable_families,
        row_stage_contract="stage-unassigned-v1",
    )

    prepared = prepare_portable_bundle_rows(
        value,
        stage_id="stage-publisher-owned",
    )

    assert tuple(prepared.family_rows) == tuple(FAMILIES)
    assert prepared.row_counts == value.family_counts
    assert prepared.files == value.family_counts["files"]
    for family, rows in prepared.family_rows.items():
        assert all(row["stage_id"] == "stage-publisher-owned" for row in rows), family
    assert all(checksum.row_count == value.family_counts[family] for family, checksum in prepared.checksums.items())


def test_portable_preparation_refuses_legacy_mixed_or_unvalidated_stage_contracts() -> None:
    with pytest.raises(ValueError, match="current portable stage contract"):
        prepare_portable_bundle_rows(
            bundle(row_stage_contract="legacy-absent-v1"),
            stage_id="stage-publisher-owned",
        )


def test_bundle_stage_rule_has_explicit_current_and_legacy_decoders() -> None:
    legacy = bundle(row_stage_contract="legacy-absent-v1")
    current_families: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: tuple({"stage_id": "stage-unassigned", **row} for row in rows)
        for family, rows in FAMILIES.items()
    }
    current = bundle(
        families=current_families,
        row_stage_contract="stage-unassigned-v1",
    )

    assert legacy.row_stage_contract == "legacy-absent-v1"
    assert current.row_stage_contract == "stage-unassigned-v1"
    assert PublicationBundle.from_bytes(legacy.canonical_bytes()) == legacy
    assert PublicationBundle.from_bytes(current.canonical_bytes()) == current

    mixed = bundle(
        families={
            family: tuple(
                ({**row, "stage_id": "stage-unassigned"} if index % 2 else row)
                for index, row in enumerate(rows)
            )
            for family, rows in FAMILIES.items()
        },
        row_stage_contract="stage-unassigned-v1",
    )
    store = MemoryArtifactStore()
    mixed_ref = put_bundle(store, mixed)
    mixed_receipt_ref = put_receipt(store, receipt(mixed_ref, mixed))
    with pytest.raises(ValueError, match="stage representation"):
        PublisherBundleValidator().validate_bundle(
            store=store,
            bundle_reference=mixed_ref,
            receipt_reference=mixed_receipt_ref,
            expectation=PublicationExpectation.from_bundle(mixed, mutating_owner_count=1),
        )


@pytest.mark.parametrize("mutation", ["truncated", "duplicate", "unknown-family", "partial"])
def test_bundle_rejects_corrupt_duplicate_unknown_or_partial_frames(mutation: str) -> None:
    data = bundle().canonical_bytes()
    changed = PublicationBundle.malformed_for_test(data, mutation)

    with pytest.raises(ValueError):
        PublicationBundle.from_bytes(changed)


def test_database_independent_portable_bundle_creation_and_observation_confidence() -> None:
    with pytest.raises(
        ObservationValidationError,
        match="confidence must be one of: extracted, heuristic, manual, unknown",
    ):
        RawObservation(
            kind="file",
            source_id="main.py",
            path="main.py",
            confidence="exact",
            extractor="fixture",
            extractor_version="1",
            metadata={"language": "python", "role": "source"},
        )

    prepared = build_staged_rows(
        (
            RawObservation(
                kind="file",
                source_id="main.py",
                path="main.py",
                confidence="extracted",
                extractor="fixture",
                extractor_version="1",
                metadata={"language": "python", "role": "source"},
            ),
        ),
        repository_name="portable-fixture",
        stage_id="stage-unassigned",
    )
    try:
        families: dict[StageFamily, tuple[dict[str, object], ...]] = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()

    created_bundle = PublicationBundle.create(
        request_id="job-str-pub5",
        job_id="job-str-pub5",
        attempt=1,
        graph_id="portable-fixture",
        candidate_id="cand1:" + "1" * 64,
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=(("bind1:" + "3" * 64, 1, "snap1:" + "4" * 64),),
        source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )
    assert created_bundle.bundle_id.startswith("bundle1:")
    assert created_bundle.candidate_id.startswith("cand1:")
    assert len(created_bundle.families["files"]) == 1
    assert created_bundle.families["files"][0]["path"] == "main.py"


def test_bundle_rejects_missing_header() -> None:
    b = bundle()
    valid_bytes = b.canonical_bytes()
    lines = valid_bytes.splitlines(keepends=True)

    with pytest.raises(ValueError, match="framing is invalid"):
        PublicationBundle.from_bytes(b"".join(lines[1:]))
