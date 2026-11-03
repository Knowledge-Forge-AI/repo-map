"""Publication, query-identity, and invocation-scope helpers for W5 ANN."""

from __future__ import annotations

import hashlib
import json

from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, checked_identity
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_ann_models import HnswEvaluationError, HnswSourceScope


def match_candidate_publication(
    candidate: CandidatePublication, pin: VerifiedPublicationPin
) -> None:
    """Require a live PostgreSQL candidate publication to match the full pin."""
    if not isinstance(pin, VerifiedPublicationPin):
        raise HnswEvaluationError("unverified_publication_pin", "VerifiedPublicationPin is required")
    if pin.backend != "postgresql":
        raise HnswEvaluationError("hnsw_postgresql_required", "HNSW requires a PostgreSQL publication")
    if type(pin.run_id) is not int or pin.run_id <= 0 or type(pin.generation) is not int or pin.generation <= 0:
        raise HnswEvaluationError("invalid_publication_pin", "publication run and generation are invalid")
    try:
        current = pin.revalidate_current()
    except Exception as exc:
        code = getattr(exc, "code", "stale_publication_receipt")
        if type(code) is not str or not code.replace("_", "").isalnum():
            code = "stale_publication_receipt"
        raise HnswEvaluationError(code, "publication pin is not current") from exc
    if not isinstance(current, VerifiedPublicationPin):
        raise HnswEvaluationError("invalid_publication_readback", "publication revalidation returned an invalid pin")
    if (
        current.graph_id, current.repository_identity, current.backend, current.run_id,
        current.generation, current.receipt, current.receipt_identity,
        current.admitted_public_bindings, dict(current.denied_bindings),
    ) != (
        pin.graph_id, pin.repository_identity, pin.backend, pin.run_id,
        pin.generation, pin.receipt, pin.receipt_identity,
        pin.admitted_public_bindings, dict(pin.denied_bindings),
    ):
        raise HnswEvaluationError("publication_pin_changed", "publication pin changed during revalidation")
    try:
        candidate.validate()
    except Exception as exc:
        raise HnswEvaluationError("invalid_candidate_publication", "candidate publication is invalid") from exc
    publication = candidate.publication
    if candidate.repository_identity != pin.repository_identity:
        raise HnswEvaluationError("repository_identity_mismatch", "candidate repository differs from publication pin")
    if publication.run_id != pin.run_id:
        raise HnswEvaluationError("stale_publication_receipt", "candidate run differs from publication pin")
    if publication.receipt != pin.receipt or candidate.receipt_identity != pin.receipt_identity:
        raise HnswEvaluationError("publication_receipt_mismatch", "candidate receipt differs from publication pin")
    if publication.receipt.generations != pin.receipt.generations:
        raise HnswEvaluationError("generation_mismatch", "candidate generations differ from publication pin")
    if publication.receipt.portable is None or pin.receipt.portable is None:
        raise HnswEvaluationError("portable_receipt_required", "complete portable receipt is required")
    if publication.receipt.portable.snapshot_vector != pin.receipt.portable.snapshot_vector:
        raise HnswEvaluationError("snapshot_vector_mismatch", "candidate snapshot vector differs from publication pin")


def candidate_query_digest(query: CandidateQuery, source_scope: HnswSourceScope) -> str:
    """Return the canonical digest for every query and public scope input."""
    pairs = tuple(source_scope)
    try:
        unique = len(set(pairs))
    except TypeError as exc:
        raise ValueError("HNSW query scope pair is unhashable") from exc
    if not pairs or unique != len(pairs):
        raise ValueError("HNSW query scope must contain unique source pairs")
    if query.source_binding_id is None or len(pairs) != 1 or pairs[0][0] != query.source_binding_id:
        raise ValueError("HNSW query scope must bind the selected source")
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("HNSW query scope pair is malformed")
        checked_identity(pair[0])
        checked_identity(pair[1])
    payload = {
        "repository_identity": query.publication.repository_identity,
        "run_id": int(query.publication.publication.run_id),
        "receipt_identity": query.publication.receipt_identity,
        "profile_identity": query.profile.identity,
        "rebuild_id": query.rebuild_id,
        "vector": list(query.vector),
        "selected": query.selected,
        "limit": query.limit,
        "evidence_limit": query.evidence_limit,
        "kind": query.kind,
        "path": query.path,
        "source_binding_id": query.source_binding_id,
        "source_scope": [list(pair) for pair in pairs],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def index_name(query_digest: str, rebuild_id: str, attempt_identity: str, owner_identity: str) -> str:
    identity = "|".join((query_digest, rebuild_id, attempt_identity, owner_identity)).encode("utf-8")
    return "repomap_w5_hnsw384_" + hashlib.sha256(identity).hexdigest()[:32]
