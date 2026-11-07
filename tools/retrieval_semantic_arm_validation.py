"""Per-arm provenance, QueryEnvelope, and candidate validation for W5 RRF fusion (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from common_lore_index.retrieval.context_identity import ContextIdentityError, normalize_accepted_publication
from common_lore_index.retrieval.query_contracts import CapabilityState, QueryEnvelope
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_representation import (
    RepresentationValidationError,
    VerifiedPublicationPin,
    _require,
    _validate_representation_string,
    canonical_node_v1_digest,
    freeze_jsonable,
    validate_relative_path,
    verify_publication_provenance,
)

MAX_ARM_CANDIDATES = 500


@dataclass(frozen=True)
class FileIdentityTuple:
    """Canonical file-level fusion identity (binding_id, snapshot_id, source_relative_path)."""
    binding_id: str
    snapshot_id: str
    source_relative_path: str

    def validate(self, *, private_markers: Sequence[str] = ()) -> FileIdentityTuple:
        m = tuple(str(x) for x in private_markers if x)
        for val, name in ((self.binding_id, "binding_id"), (self.snapshot_id, "snapshot_id"), (self.source_relative_path, "source_relative_path")):
            _validate_representation_string(val, name, private_markers=m)
        try:
            validate_relative_path(self.source_relative_path, "source_relative_path")
        except ValueError as exc:
            raise RepresentationValidationError("invalid_relative_path", str(exc)) from exc
        return self

    def utf8_sort_key(self) -> tuple[bytes, bytes, bytes]:
        return (self.binding_id.encode("utf-8"), self.snapshot_id.encode("utf-8"), self.source_relative_path.encode("utf-8"))

    def file_key(self) -> tuple[str, str]:
        return (self.binding_id, self.source_relative_path)

    def to_dict(self) -> dict[str, str]:
        return {"binding_id": self.binding_id, "snapshot_id": self.snapshot_id, "source_relative_path": self.source_relative_path}


@dataclass(frozen=True)
class VectorCandidateInput:
    """Candidate node hit from a vector arm before evidence-to-file projection."""
    canonical_key: str
    source_binding_id: str
    raw_rank: int
    evidence: Sequence[Any]
    input_digest: str | None = None
    kind: str | None = None
    display_name: str | None = None
    cosine_distance: float | None = None


@dataclass(frozen=True)
class AdmittedArmObservation:
    """Single-arm retrieval observation paired with its independently verified publication pin."""
    arm_id: str
    mode: str
    verified_pin: VerifiedPublicationPin | None = None
    execution_state: ExecutionState = ExecutionState.COMPLETED
    envelope: QueryEnvelope | None = None
    vector_candidates: Sequence[Any] | None = None
    raw_file_hits: Sequence[tuple[FileIdentityTuple, int, str]] | None = None
    refusal_code: str | None = None
    unavailable_reason: str | None = None
    failure_reason: str | None = None
    selected_binding_ids: Sequence[str] | None = None
    provenance_inputs: Mapping[str, Any] | None = None
    observed_accepted_publication: Mapping[str, Any] | None = None
    incomplete: bool = False
    truncated: bool = False


def _resolve_arm_pin(arm: AdmittedArmObservation) -> VerifiedPublicationPin:
    if arm.provenance_inputs is not None:
        return verify_publication_provenance(**dict(arm.provenance_inputs))
    _require(isinstance(arm.verified_pin, VerifiedPublicationPin), "missing_verified_provenance", f"arm {arm.arm_id!r} lacks verified_pin")
    assert arm.verified_pin is not None
    return arm.verified_pin.revalidate_current()


def _pins_match(a: VerifiedPublicationPin, b: VerifiedPublicationPin) -> str | None:
    if (a.graph_id, a.repository_identity, a.backend) != (b.graph_id, b.repository_identity, b.backend):
        return "cross_arm_identity_mismatch"
    if (
        a.run_id, a.generation, a.publication_bundle_id, a.snapshot_manifest_id,
        a.extraction_receipt_id, a.graph_candidate_id, a.receipt_identity,
    ) != (
        b.run_id, b.generation, b.publication_bundle_id, b.snapshot_manifest_id,
        b.extraction_receipt_id, b.graph_candidate_id, b.receipt_identity,
    ):
        return "cross_arm_publication_mismatch"
    if a.snapshot_vector != b.snapshot_vector or a.admitted_public_bindings != b.admitted_public_bindings or dict(a.denied_bindings) != dict(b.denied_bindings):
        return "cross_arm_snapshot_mismatch"
    return None


def _verify_observed_accepted_publication(pub: Any, pin: VerifiedPublicationPin) -> str | None:
    if pub is None:
        return None
    if not isinstance(pub, Mapping):
        return "invalid_observed_accepted_publication"
    if not pub:
        return "incomplete_observed_accepted_publication"
    try:
        frozen = freeze_jsonable(pub)
    except RepresentationValidationError:
        return "invalid_observed_accepted_publication"
    assert isinstance(frozen, Mapping)
    raw_run = frozen.get("run_id", frozen.get("accepted_run_id"))
    if type(raw_run) is int and raw_run != pin.run_id:
        return "stale_publication_receipt"
    raw_gen = frozen.get("generation")
    if type(raw_gen) is int and raw_gen != pin.generation:
        return "observed_generation_mismatch"
    raw_bundle = frozen.get("publication_bundle_id")
    if type(raw_run) is not int or raw_run < 1 or type(raw_gen) is not int or raw_gen < 1 or type(raw_bundle) is not str or not raw_bundle.strip():
        return "incomplete_observed_accepted_publication"
    if raw_bundle != pin.publication_bundle_id:
        return "observed_publication_bundle_id_mismatch"
    ctx_keys = set(frozen) - {"run_id", "accepted_run_id", "generation", "publication_bundle_id", "repository_id"}
    if not ctx_keys:
        return None
    try:
        norm = normalize_accepted_publication(frozen, require_pin=True, require_vector=True)
    except (ContextIdentityError, TypeError, ValueError):
        return "incomplete_observed_accepted_publication"
    cand_id = frozen.get("graph_candidate_id") or frozen.get("candidate_id")
    if type(cand_id) is not str or not cand_id.strip():
        return "incomplete_observed_accepted_publication"
    for key, actual, expected in (
        ("snapshot_manifest_id", norm["snapshot_manifest_id"], pin.snapshot_manifest_id),
        ("extraction_receipt_id", norm["extraction_receipt_id"], pin.extraction_receipt_id),
        ("graph_candidate_id", cand_id, pin.graph_candidate_id),
        ("job_id", norm["job_id"], str(pin.receipt.attempt.job_id)),
        ("attempt", norm["attempt"], int(pin.receipt.attempt.attempt)),
    ):
        if actual != expected:
            return f"observed_{key}_mismatch"
    if tuple(norm["snapshot_vector"]) != pin.snapshot_vector:
        return "observed_snapshot_vector_mismatch"
    for g_field in ("source_generation", "config_generation", "extractor_generation", "canonicalizer_generation"):
        if g_field in frozen and frozen[g_field] != str(getattr(pin.receipt.generations, g_field)):
            return "observed_generation_vector_mismatch"
    return None


def _strict_envelope_pin_error(
    env: QueryEnvelope,
    pin: VerifiedPublicationPin,
    provenance: Mapping[str, Any],
) -> str | None:
    """Require the real lexical envelope's publication identity before credit."""
    scope = env.scope
    if not isinstance(scope.publication_bundle_id, str) or not scope.publication_bundle_id:
        return "envelope_publication_bundle_id_missing"
    if scope.publication_bundle_id != pin.publication_bundle_id:
        return "envelope_publication_bundle_id_mismatch"
    if not isinstance(scope.snapshot_manifest_id, str) or not scope.snapshot_manifest_id:
        return "envelope_snapshot_manifest_id_missing"
    if scope.snapshot_manifest_id != pin.snapshot_manifest_id:
        return "envelope_snapshot_manifest_id_mismatch"

    if "backend" in provenance:
        if type(provenance["backend"]) is not str or provenance["backend"] != scope.backend:
            return "envelope_backend_mismatch"
    if "repository_identity" in provenance:
        repository_identity = provenance["repository_identity"]
        if (
            type(repository_identity) is not str
            or not repository_identity
            or repository_identity != pin.repository_identity
        ):
            return "envelope_repository_identity_mismatch"
    # ``repository_id`` is not a QueryEnvelope contract field; never treat it
    # as an alias for the configured repository_identity.

    run_ids: list[int] = []
    for field in ("accepted_run_id", "run_id"):
        if field not in provenance:
            continue
        value = provenance[field]
        if type(value) is not int or value < 1:
            return "envelope_run_id_invalid"
        run_ids.append(value)
    if not run_ids:
        return "envelope_run_id_missing"
    if len(set(run_ids)) != 1:
        return "envelope_run_id_conflict"
    if run_ids[0] != pin.run_id:
        return "stale_publication_receipt"
    return None


def _verify_envelope_against_pin(
    env: Any, pin: VerifiedPublicationPin
) -> tuple[str | None, ExecutionState | None, str | None, bool, bool]:
    if env is None:
        return None, None, None, False, False
    if not isinstance(env, QueryEnvelope):
        return "invalid_query_envelope", ExecutionState.REFUSED, None, False, False
    try:
        validated = env.validate()
    except (ValueError, TypeError, RepresentationValidationError):
        return "invalid_query_envelope", ExecutionState.REFUSED, None, False, False
    scope = validated.scope
    if scope.graph_id != pin.graph_id:
        return "envelope_graph_id_mismatch", ExecutionState.REFUSED, None, False, False
    if scope.backend != pin.backend:
        return "envelope_backend_mismatch", ExecutionState.REFUSED, None, False, False
    if scope.publication_bundle_id is not None and scope.publication_bundle_id != pin.publication_bundle_id:
        return "envelope_publication_bundle_id_mismatch", ExecutionState.REFUSED, None, False, False
    if scope.snapshot_manifest_id is not None and scope.snapshot_manifest_id != pin.snapshot_manifest_id:
        return "envelope_snapshot_manifest_id_mismatch", ExecutionState.REFUSED, None, False, False
    for b_id in scope.selected_binding_ids:
        if b_id in pin.denied_bindings or b_id not in pin.admitted_public_bindings:
            return pin.denied_bindings.get(b_id, "unknown_source_binding"), ExecutionState.REFUSED, None, False, False
    raw_provenance: object = validated.provenance
    if not isinstance(raw_provenance, Mapping):
        return "invalid_query_envelope", ExecutionState.REFUSED, None, False, False
    prov = raw_provenance
    cap = validated.capability_state
    if cap in {CapabilityState.AVAILABLE, CapabilityState.PARTIAL}:
        strict_error = _strict_envelope_pin_error(validated, pin, prov)
        if strict_error is not None:
            return strict_error, ExecutionState.REFUSED, None, False, False
    for k, expected, err in (
        ("graph_id", pin.graph_id, "envelope_graph_id_mismatch"),
        ("generation", pin.generation, "envelope_generation_mismatch"),
        ("publication_bundle_id", pin.publication_bundle_id, "envelope_publication_bundle_id_mismatch"),
        ("snapshot_manifest_id", pin.snapshot_manifest_id, "envelope_snapshot_manifest_id_mismatch"),
        ("extraction_receipt_id", pin.extraction_receipt_id, "envelope_extraction_receipt_id_mismatch"),
        ("graph_candidate_id", pin.graph_candidate_id, "envelope_graph_candidate_id_mismatch"),
    ):
        if k in prov and (type(prov[k]) is not type(expected) or prov[k] != expected):
            return err, ExecutionState.REFUSED, None, False, False
    if "accepted_publication" in prov:
        obs_err = _verify_observed_accepted_publication(prov["accepted_publication"], pin)
        if obs_err is not None:
            return obs_err, ExecutionState.REFUSED, None, False, False
    if cap == CapabilityState.REFUSED:
        return str(validated.refusal_code or "envelope_refused"), ExecutionState.REFUSED, None, False, False
    if cap == CapabilityState.STALE:
        return "stale_envelope_publication", ExecutionState.REFUSED, None, False, False
    if cap == CapabilityState.FAILED:
        return None, ExecutionState.FAILED, str(prov.get("failure_reason") or "envelope_failed"), True, False
    if cap == CapabilityState.UNAVAILABLE:
        return None, ExecutionState.UNAVAILABLE, str(validated.unavailable_reason or "envelope_unavailable"), True, False
    if cap == CapabilityState.NOT_RUN:
        return None, ExecutionState.NOT_RUN, str(validated.unavailable_reason or "envelope_not_run"), True, False
    env_trunc = bool(prov.get("truncated") or prov.get("has_more") or any("truncat" in o.reason_code or "limit" in o.reason_code for o in validated.omissions))
    env_inc = bool(cap == CapabilityState.PARTIAL or not validated.scope_complete or bool(validated.omissions) or env_trunc)
    return None, ExecutionState.COMPLETED, None, env_inc, env_trunc


def _extract_arm_raw_hits(
    arm: AdmittedArmObservation, pin: VerifiedPublicationPin, markers: tuple[str, ...], *, max_candidates: int = MAX_ARM_CANDIDATES,
) -> tuple[list[tuple[FileIdentityTuple, int, str]], int, bool]:
    snapshots, extracted, inspected, capped_trunc = pin.snapshot_by_binding(), [], 0, False
    selected_filter = frozenset(arm.selected_binding_ids) if arm.selected_binding_ids is not None else pin.admitted_public_bindings
    try:
        if arm.raw_file_hits is not None:
            raw_seq, capped_trunc = arm.raw_file_hits[:max_candidates], len(arm.raw_file_hits) > max_candidates
            for f_tuple, raw_rank, sup_id in raw_seq:
                inspected += 1
                _require(type(raw_rank) is int and raw_rank >= 1, "invalid_raw_rank", "raw_rank must be >= 1")
                _require(isinstance(f_tuple, FileIdentityTuple), "malformed_candidate_input", "expected FileIdentityTuple")
                f_tuple.validate(private_markers=markers)
                if f_tuple.binding_id in pin.denied_bindings:
                    raise RepresentationValidationError(pin.denied_bindings[f_tuple.binding_id], "denied binding in hit")
                _require(f_tuple.binding_id in pin.admitted_public_bindings, "unknown_source_binding", "binding not admitted")
                _require(f_tuple.binding_id in selected_filter, "out_of_scope_binding", "hit binding outside selected scope")
                _require(snapshots[f_tuple.binding_id][1] == f_tuple.snapshot_id, "snapshot_id_mismatch", "snapshot mismatch")
                extracted.append((f_tuple, raw_rank, _validate_representation_string(sup_id, "support_id", private_markers=markers)))
            return extracted, inspected, capped_trunc
        if arm.vector_candidates is not None:
            seen_cands: set[tuple[str, str]] = set()
            vec_seq, capped_trunc = arm.vector_candidates[:max_candidates], len(arm.vector_candidates) > max_candidates
            for raw_cand in vec_seq:
                inspected += 1
                cand = raw_cand if isinstance(raw_cand, VectorCandidateInput) else VectorCandidateInput(
                    raw_cand["canonical_key"], raw_cand["source_binding_id"], raw_cand["raw_rank"],
                    raw_cand.get("evidence", ()), raw_cand.get("input_digest"), raw_cand.get("kind"),
                    raw_cand.get("display_name"), raw_cand.get("cosine_distance"),
                )
                _require(type(cand.raw_rank) is int and cand.raw_rank >= 1, "invalid_raw_rank", "raw_rank must be >= 1")
                c_key = _validate_representation_string(cand.canonical_key, "canonical_key", private_markers=markers)
                b_id = _validate_representation_string(cand.source_binding_id, "source_binding_id", private_markers=markers)
                if b_id in pin.denied_bindings:
                    raise RepresentationValidationError(pin.denied_bindings[b_id], "denied binding in vector candidate")
                _require(b_id in pin.admitted_public_bindings, "unknown_source_binding", "vector binding not admitted")
                _require(b_id in selected_filter, "out_of_scope_binding", "vector candidate outside selected scope")
                _require((c_key, b_id) not in seen_cands, "duplicate_vector_candidate", "duplicate vector candidate")
                seen_cands.add((c_key, b_id))
                if cand.kind is not None and cand.display_name is not None and cand.input_digest is not None:
                    _require(cand.input_digest == canonical_node_v1_digest(c_key, cand.kind, cand.display_name, private_markers=markers), "representation_digest_mismatch", "vector digest mismatch")
                _require(bool(cand.evidence), "malformed_or_withheld_vector_evidence", "vector candidate has no evidence")
                expected_snap = snapshots[b_id][1]
                for ev in cand.evidence:
                    ev_map: Mapping[str, Any] = freeze_jsonable(ev) if isinstance(ev, Mapping) else {"path": getattr(ev, "path", None), "metadata_json": getattr(ev, "metadata_json", None)}
                    ev_path, meta = ev_map.get("path"), ev_map.get("metadata_json")
                    _require(ev_path is None or (type(ev_path) is str and not ev_path.startswith("/withheld/")), "malformed_or_withheld_vector_evidence", "withheld path")
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except ValueError as exc:
                            raise RepresentationValidationError("malformed_or_withheld_vector_evidence", str(exc)) from exc
                    _require(isinstance(meta, Mapping), "malformed_or_withheld_vector_evidence", "missing metadata_json")
                    assert isinstance(meta, Mapping)
                    ev_b, ev_s, ev_p = meta.get("binding_id"), meta.get("snapshot_id"), meta.get("source_relative_path")
                    if type(ev_b) is str and ev_b in pin.denied_bindings:
                        raise RepresentationValidationError(pin.denied_bindings[ev_b], "denied binding in evidence")
                    _require(ev_b == b_id and ev_s == expected_snap and type(ev_p) is str, "malformed_or_withheld_vector_evidence", "evidence provenance mismatch")
                    extracted.append((FileIdentityTuple(b_id, expected_snap, str(ev_p)).validate(private_markers=markers), cand.raw_rank, c_key))
            return extracted, inspected, capped_trunc
        if arm.envelope is not None:
            scope_filter = selected_filter & frozenset(arm.envelope.scope.selected_binding_ids)
            all_hits = tuple(arm.envelope.hits)
            env_hits, capped_trunc = all_hits[:max_candidates], len(all_hits) > max_candidates
            for idx, hit in enumerate(env_hits, start=1):
                inspected += 1
                _require(hit.rank == idx, "non_contiguous_hit_ranks", f"expected rank {idx}, got {hit.rank}")
                loc = hit.locator
                loc_b_id, rel_path = loc.binding_id, loc.source_relative_path
                if loc_b_id in pin.denied_bindings:
                    raise RepresentationValidationError(pin.denied_bindings[loc_b_id], "denied binding in envelope hit")
                _require(loc_b_id in pin.admitted_public_bindings, "unknown_source_binding", "invalid hit binding")
                _require(loc_b_id in scope_filter, "out_of_scope_binding", "hit binding outside selected scope")
                expected_snap = snapshots[loc_b_id][1]
                f_tuple = FileIdentityTuple(loc_b_id, expected_snap, rel_path).validate(private_markers=markers)
                sup_id = str(loc.canonical_key or hit.chunk_id or loc.evidence_key or f"{loc_b_id}:{rel_path}:{hit.rank}")
                extracted.append((f_tuple, hit.rank, _validate_representation_string(sup_id, "support_id", private_markers=markers)))
    except RepresentationValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationValidationError("malformed_candidate_input", str(exc)) from exc
    return extracted, inspected, capped_trunc
