"""Explicit synthetic vectors for mechanical SQL proof; no model worker claim."""

from __future__ import annotations

import math

from common_lore_index.storage.semantic_candidates import EmbeddingEntry, EmbeddingProfile
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_experiment_evaluator import SealedComponent
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_output import GeneratedEnrichmentArtifact
from retrieval_semantic_generator_output_receipt import QueryEmbedding


SUPPLIER_IDENTITY = digest_json({"fixture":"synthetic_axis_384d_functional_only","version":1})
SYNTHETIC_PROFILE = EmbeddingProfile("synthetic-axis-functional-fixture","1","test-supplier","1",384).validate()
QUERY_VECTOR = (1.0,) + (0.0,) * 383


def synthetic_vector_supply(inputs: PublicGenerationInput) -> SealedComponent:
    """Replace only the model boundary; all entry identities come from current IO."""
    inputs.require_current()
    count = len(inputs.documents)
    if not 1 <= count <= 500:
        raise ExperimentRefusal("functional_documents_required")
    entries = []
    for ordinal, document in enumerate(inputs.documents,1):
        angle = ordinal * math.pi / (2 * (count + 1))
        vector = (math.cos(angle),math.sin(angle)) + (0.0,) * 382
        representation = document.representation
        entries.append(EmbeddingEntry(
            representation.canonical_key, representation.source_binding_id,
            vector, representation.input_digest,
        ))
    queries = tuple(QueryEmbedding(
        decision.task_id, decision.task_sha256, decision.state, decision.reason,
        QUERY_VECTOR if decision.record_id is not None else None,
    ) for decision in inputs.query_decisions)
    artifact = GeneratedEnrichmentArtifact(
        input_identity=inputs.input_identity,
        representation_report_identity=inputs.representation_report_identity,
        artifact_profile_identity=SUPPLIER_IDENTITY,
        component_receipt_identity=SUPPLIER_IDENTITY,
        worker_report_identity=SUPPLIER_IDENTITY,
        worker_declaration_identity=SUPPLIER_IDENTITY,
        worker_terminal_identity=SUPPLIER_IDENTITY,
        worker_source_manifest_identity=SUPPLIER_IDENTITY,
        worker_sources_archive_identity=SUPPLIER_IDENTITY,
        controller_admission_identity=SUPPLIER_IDENTITY,
        publication_identity=digest_json(inputs.provenance.to_dict()),
        profile=SYNTHETIC_PROFILE, entries=tuple(entries), queries=queries,
        complete_generation=True, partial_publication_coverage=inputs.partial_publication_coverage,
        truncated_record_ids=(),
    )
    # These empty maps intentionally assert no worker receipt, measured cost or
    # sealed worker counts. The fixture identity above is never an admission.
    return SealedComponent(artifact, {}, {}, {})


__all__ = ["QUERY_VECTOR","SUPPLIER_IDENTITY","SYNTHETIC_PROFILE","synthetic_vector_supply"]
