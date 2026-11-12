"""Pure public-text fixture using the real mixed-v1 binding identities.

This helper returns only ``ProjectionInputs`` and its validated policy.  It does
not create tasks, pins, worker responses, model output, or acceptance claims;
the caller must load the unchanged registered task objects and create a fresh
verified pin through its readback adapter.  All sealed identities below come
from the maintained manifest, bundle, receipt, and in-memory artifact-store
factories; none are repaired with dataclass replacement after construction.
Its caller ``SyntheticStudy`` deliberately replaces the accepted reference
run/generation for its synthetic generation before maintained provenance
verification, so the result is never an actual refreshed generation; the
functional driver uses genuine Local/PostgreSQL publications instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.store import InMemoryArtifactStore
from common_lore_index.graph.multi_source import (
    GraphCandidate,
    GraphSourceBinding,
    SnapshotManifestEntry,
    SourceDefinition,
    SourceKind,
    SourceSnapshot,
    graph_source_binding_id,
    multi_source_configuration_id,
    source_selection_policy_id,
)
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, ResolvedBindingPolicy
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference, ProjectionInputs
from common_lore_index.storage.authority import AttemptNumber, JobId
from common_lore_index.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from common_lore_index.storage.staging_family_contracts import PrivacyClassification
from common_lore_index.storage.staging_family_rows import StageFamily


GRAPH_ID = "mixed-v1"
CORE_BINDING = graph_source_binding_id(GRAPH_ID, "core")
COMPANION_BINDING = graph_source_binding_id(GRAPH_ID, "companion")
FEEDS_BINDING = graph_source_binding_id(GRAPH_ID, "feeds")
MAILBOX_BINDING = graph_source_binding_id(GRAPH_ID, "mailbox")
PUBLIC_BINDINGS = (CORE_BINDING, COMPANION_BINDING)

_JOB_ID = "job-registered-public-text"
_SOURCE_GENERATION = "sg1:registered-public-text"
_CONFIG_GENERATION = "cg1:registered-public-text"
_EXTRACTOR_GENERATION = "eg1:registered-public-text"
_CANONICALIZER_GENERATION = "kg1:registered-public-text"


def _source_snapshot(alias: str, body: bytes | None, *, rel_path: str, executable: bool) -> SourceSnapshot:
    private = alias == "mailbox"
    role = "source" if alias == "core" else alias
    retention = "full-authorized" if alias in {"core", "companion"} else "metadata-only"
    binding = GraphSourceBinding.create(
        graph_id=GRAPH_ID,
        alias=alias,
        source_definition=SourceDefinition.create(f"mixed-v1-{alias}", SourceKind.FOLDER),
        revision=1,
        logical_root=alias,
        privacy_policy="private-memory" if private else "public-dev",
        evidence_retention_policy=retention,
        extractor_profile="default",
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared" if alias in {"core", "companion"} else "isolated",
        role=role,
        input_name=alias,
    )
    entries = () if body is None else (
        SnapshotManifestEntry(rel_path, hashlib.sha256(body).hexdigest(), len(body), executable),
    )
    return SourceSnapshot.create(
        binding,
        manifest_entries=entries,
        git_commit=None,
        git_tree=None if entries else "0" * 40,
        ignore_policy_id="ignore1:registered-public-text",
        metadata_identity=f"meta1:registered-public-text-{alias}",
    )


def _manifest_binding(snapshot: SourceSnapshot) -> ManifestBinding:
    binding = snapshot.binding
    return ManifestBinding(
        binding_id=binding.binding_id,
        revision=binding.revision,
        snapshot_id=snapshot.snapshot_id,
        source_definition_id=binding.source_definition.source_definition_id,
        source_kind="local-directory",
        acquisition_method="sealed-local-copy",
        selection_policy_id=binding.selection_policy_id,
        ignore_policy_id=snapshot.ignore_policy_id,
        privacy_policy=binding.privacy_policy,
        role=binding.role,
        input_name=binding.input_name,
        alias=binding.alias,
        logical_root=binding.logical_root,
        evidence_retention_policy=binding.evidence_retention_policy,
        extractor_profile=binding.extractor_profile,
        resolution_policy=binding.resolution_policy,
        repository_scope=binding.alias,
    )


def _raw_reference(store: InMemoryArtifactStore, body: bytes, media_type: str):
    return store.put(
        body,
        media_type=media_type,
        record_format="raw-source-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )


def _families(core_path: str, companion_path: str, core_body: bytes, companion_body: bytes,
              core_snapshot: str, companion_snapshot: str) -> dict[StageFamily, tuple[dict[str, object], ...]]:
    core_key = "python.function:pkg.alpha:boundary_fn"
    companion_key = "shell.function:scripts.deploy:deploy_main"
    rows: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: () for family in PUBLICATION_FAMILIES
    }
    rows["raw_observations"] = (
        {
            "source_ordinal": 0, "schema_version": 1, "kind": "python.function",
            "source_id": "registered-core-boundary", "path": f"core/{core_path}",
            "payload_json": {},
            "payload_hash": "sha256:" + hashlib.sha256(core_body).hexdigest(),
            "stage_id": "stage-unassigned",
        },
        {
            "source_ordinal": 1, "schema_version": 1, "kind": "shell.function",
            "source_id": "registered-companion-deploy", "path": f"companion/{companion_path}",
            "payload_json": {},
            "payload_hash": "sha256:" + hashlib.sha256(companion_body).hexdigest(),
            "stage_id": "stage-unassigned",
        },
    )
    rows["canonical_nodes"] = (
        {
            "family_ordinal": 0, "graph_key_version": 1, "canonical_key": core_key,
            "kind": "Function", "display_name": "boundary_fn", "metadata_json": {},
            "confidence": "extracted", "conflict": False, "stage_id": "stage-unassigned",
        },
        {
            "family_ordinal": 1, "graph_key_version": 1, "canonical_key": companion_key,
            "kind": "Function", "display_name": "deploy_main", "metadata_json": {},
            "confidence": "extracted", "conflict": False, "stage_id": "stage-unassigned",
        },
    )
    rows["canonical_evidence"] = (
        {
            "family_ordinal": 0, "graph_key_version": 1, "evidence_key": "ev1:alpha80",
            "raw_observation_ordinal": 0, "stage_id": "stage-unassigned", "raw_kind": "python.function",
            "path": f"core/{core_path}", "start_line": 80, "end_line": 81, "confidence": "extracted",
            "metadata_json": {"binding_id": CORE_BINDING, "snapshot_id": core_snapshot,
                              "source_relative_path": core_path},
        },
        {
            "family_ordinal": 1, "graph_key_version": 1, "evidence_key": "ev1:registered-companion",
            "raw_observation_ordinal": 1, "stage_id": "stage-unassigned", "raw_kind": "shell.function",
            "path": f"companion/{companion_path}", "start_line": 1, "end_line": 2,
            "confidence": "extracted",
            "metadata_json": {"binding_id": COMPANION_BINDING, "snapshot_id": companion_snapshot,
                              "source_relative_path": companion_path},
        },
    )
    rows["canonical_node_evidence"] = (
        {"canonical_key": core_key, "stage_id": "stage-unassigned", "family_ordinal": 0,
         "graph_key_version": 1, "evidence_key": "ev1:alpha80", "link_kind": "defined_by"},
        {"canonical_key": companion_key, "stage_id": "stage-unassigned", "family_ordinal": 1,
         "graph_key_version": 1, "evidence_key": "ev1:registered-companion", "link_kind": "defined_by"},
    )
    return rows


def _policy() -> BodyProjectionPolicy:
    return BodyProjectionPolicy(
        graph_id=GRAPH_ID,
        selected_binding_ids=frozenset(PUBLIC_BINDINGS),
        bindings={
            CORE_BINDING: ResolvedBindingPolicy(
                CORE_BINDING, "core", "source", "folder", "public-dev", "public-dev",
                "public-dev", "public-dev", "full-authorized", "full-authorized",
            ),
            COMPANION_BINDING: ResolvedBindingPolicy(
                COMPANION_BINDING, "companion", "companion", "folder", "public-dev", "public-dev",
                "public-dev", "public-dev", "full-authorized", "full-authorized",
            ),
            FEEDS_BINDING: ResolvedBindingPolicy(
                FEEDS_BINDING, "feeds", "feeds", "folder", "public-dev", "public-dev",
                "public-dev", "public-dev", "metadata-only", "metadata-only",
            ),
            MAILBOX_BINDING: ResolvedBindingPolicy(
                MAILBOX_BINDING, "mailbox", "mailbox", "folder", "private-memory", "private-memory",
                "private-memory", "private-memory", "metadata-only", "metadata-only",
            ),
        },
    ).validate()


def build_registered_fixture_projection(spool_dir: Path) -> tuple[ProjectionInputs, BodyProjectionPolicy]:
    """Build a pure, public core+companion projection for registered task callers."""
    if not isinstance(spool_dir, Path) or spool_dir.is_symlink():
        raise ValueError("spool_dir must be a non-symlink Path")
    spool_dir.mkdir(parents=True, exist_ok=True)
    store = InMemoryArtifactStore()
    core_path, companion_path = "pkg/alpha.py", "scripts/deploy.sh"
    lines = [f"line {index:03d}: ordinary code\n" for index in range(1, 80)]
    lines.extend(("line 080: BOUNDARY_START_TOKEN\n", "line 081: BOUNDARY_END_TOKEN\n"))
    core_body = "".join(lines).encode("utf-8")
    companion_body = b"#!/bin/sh\nmain() { printf '%s\\n' registered-companion; }\n"
    snapshots = (
        _source_snapshot("core", core_body, rel_path=core_path, executable=False),
        _source_snapshot("companion", companion_body, rel_path=companion_path, executable=True),
        _source_snapshot("feeds", None, rel_path="feed.xml", executable=False),
        _source_snapshot("mailbox", None, rel_path="private.eml", executable=False),
    )
    core, companion, feeds, mailbox = snapshots
    bindings = tuple(_manifest_binding(snapshot) for snapshot in snapshots)
    candidate = GraphCandidate.create(
        GRAPH_ID,
        snapshots,
        configuration_identity=multi_source_configuration_id(
            GRAPH_ID, tuple(snapshot.binding for snapshot in snapshots)
        ),
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:registered-public-text",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
    )
    core_ref = _raw_reference(store, core_body, "text/x-python")
    companion_ref = _raw_reference(store, companion_body, "text/x-shellscript")
    manifest = PortableSnapshotManifest.create(
        graph_id=GRAPH_ID,
        bindings=bindings,
        entries=(
            ManifestArtifact(CORE_BINDING, core_path, core_ref, False),
            ManifestArtifact(COMPANION_BINDING, companion_path, companion_ref, True),
        ),
        source_generation=_SOURCE_GENERATION, config_generation=_CONFIG_GENERATION,
        extractor_generation=_EXTRACTOR_GENERATION, canonicalizer_generation=_CANONICALIZER_GENERATION,
        extractor_capability_identity="cap1:python-static-v1", resolver_identity="resolver1:registered-public-text",
        canonicalizer_identity="canon1:graph-key-v1-binding-path", semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
    )
    families = _families(
        core_path, companion_path, core_body, companion_body,
        core.snapshot_id, companion.snapshot_id,
    )
    bundle = PublicationBundle.create(
        request_id=_JOB_ID, job_id=_JOB_ID, attempt=1, graph_id=GRAPH_ID,
        candidate_id=candidate.candidate_id, snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector, source_generation=manifest.source_generation,
        config_generation=manifest.config_generation, extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity,
        resolver_identity=manifest.resolver_identity, canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity, quality_rule_identity=manifest.quality_rule_identity,
        privacy=manifest.effective_privacy, families=families, row_stage_contract="stage-unassigned-v1",
    )
    bundle_ref = store.put(
        bundle.canonical_bytes(), media_type="application/json", record_format="publication-bundle-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    extraction = ExtractionReceipt.create(
        request_id=_JOB_ID, job_id=_JOB_ID, attempt=1, graph_id=GRAPH_ID,
        worker_capability_identity="worker1:registered-public-text", contract_version="1.0",
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        snapshot_manifest_id=manifest.manifest_id, snapshot_vector=manifest.snapshot_vector,
        resolver_identity=manifest.resolver_identity, extractor_capability_identity=manifest.extractor_capability_identity,
        canonicalizer_identity=manifest.canonicalizer_identity, semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity, outcome="completed", cancellation="not-requested",
        bundle_reference=bundle_ref, bundle_id=bundle.bundle_id, family_counts=bundle.family_counts,
        diagnostic_category=None, diagnostic_summary=(), producer_identity="worker1:registered-public-text",
        attestation_class="untrusted-worker",
    )
    receipt_ref = store.put(
        extraction.canonical_bytes(), media_type="application/json", record_format="extraction-receipt-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    portable = PortablePublicationBinding(
        route="portable-worker-v1", snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector, extraction_receipt_id=extraction.receipt_id,
        publication_bundle_id=bundle.bundle_id, candidate_id=bundle.candidate_id,
        resolver_identity=bundle.resolver_identity, canonicalizer_identity=bundle.canonicalizer_identity,
        semantic_contract_identity=bundle.semantic_contract_identity, quality_rule_identity=bundle.quality_rule_identity,
        protocol_version="1.0", worker_capability_identity="worker1:registered-public-text",
        stage_id="stage-unassigned", execution_mode="direct", singleton_fencing_epoch=1,
        graph_lease_fencing_epoch=1,
        family_receipts={item.family: {"count": item.record_count, "byte_length": item.byte_length,
                                       "digest": item.content_digest} for item in bundle.family_summaries},
    ).validate()
    receipt = RunPublicationReceipt(
        attempt=RunPublicationAttempt(JobId(_JOB_ID), AttemptNumber(1)),
        generations=RunPublicationGenerations(
            manifest.source_generation, manifest.config_generation,
            manifest.extractor_generation, manifest.canonicalizer_generation,
        ),
        portable=portable,
    ).validate()
    accepted = AcceptedPublicationReference(
        graph_id=GRAPH_ID, repository_id="repo1:mixed-v1", backend="sqlite",
        run_id=1, publication_bundle_id=bundle.bundle_id, job_id=_JOB_ID, attempt=1,
        accepted_generation=1, snapshot_manifest_id=manifest.manifest_id,
        extraction_receipt_id=extraction.receipt_id, trusted_caller=True,
    ).validate()
    policy = _policy()
    return ProjectionInputs(
        accepted, receipt, manifest, bundle, store,
        manifest_reference=store.put(
            manifest.canonical_bytes(), media_type="application/json",
            record_format="portable-snapshot-manifest-v1", privacy=PrivacyClassification.PUBLIC,
        ),
        bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        extraction_receipt=extraction, spool_dir=spool_dir,
    ), policy


__all__ = [
    "COMPANION_BINDING", "CORE_BINDING", "FEEDS_BINDING", "GRAPH_ID", "MAILBOX_BINDING",
    "PUBLIC_BINDINGS", "build_registered_fixture_projection",
]
