"""Publication provenance, store-adapter readback, and binding privacy verification for W5 (ADR 0137)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from common_lore_index.retrieval.context_identity import normalize_accepted_publication
from common_lore_index.retrieval.projection_policy import (
    ALLOWED_BINDING_PRIVACY, ALLOWED_GRAPH_PRIVACY, BodyProjectionPolicy, ExclusionReason, ResolvedBindingPolicy,
)
from common_lore_index.retrieval.publication_binding import (
    CorrespondenceRefusal, ProjectionInputs, check_correspondence,
)
from common_lore_index.storage.publication import RunPublicationReceipt
from common_lore_index.storage.semantic_candidates import checked_identity, digest_json
from retrieval_semantic_primitives import (
    CANONICAL_NODE_REPRESENTATION_VERSION, MAX_JSON_COLLECTION_ITEMS, MAX_JSON_DEPTH, MAX_PUBLIC_STRING_LENGTH,
    MAX_REPRESENTATION_RECORDS, REPRESENTATION_POLICY_VERSION, W5_FOUNDATION_SCHEMA_VERSION,
    RepresentationValidationError, _guard, _require, _validate_representation_string, freeze_jsonable,
    is_sanitized_public_string, validate_relative_path,
)

_PROVENANCE_TOKEN = object()


@dataclass(frozen=True)
class AcceptedStoreReadback:
    """Immutable snapshot returned by an in-process store readback adapter."""

    graph_id: str
    repository_identity: str
    backend: str
    accepted_publication: Mapping[str, Any]
    receipt: RunPublicationReceipt
    projection_inputs: ProjectionInputs | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_publication", freeze_jsonable(self.accepted_publication))


PublicationReadbackAdapter = Callable[[], AcceptedStoreReadback]


@dataclass(frozen=True)
class VerifiedPublicationPin:
    """Publication and receipt pin bound to an in-process store readback adapter for live revalidation."""

    graph_id: str
    repository_identity: str
    backend: str
    run_id: int
    generation: int
    receipt: RunPublicationReceipt
    receipt_identity: str
    admitted_public_bindings: frozenset[str]
    denied_bindings: Mapping[str, str]
    policy_digest: str
    _readback_adapter: PublicationReadbackAdapter | None = field(default=None, repr=False, compare=False)
    _token: object = field(default=None, repr=False, compare=False)
    _factory_seal: tuple[int, int, str] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require(
            self._token is _PROVENANCE_TOKEN and callable(self._readback_adapter),
            "unverified_publication_pin",
            "VerifiedPublicationPin must be constructed via verify_publication_provenance with a readback_adapter",
        )

    def revalidate_current(self) -> VerifiedPublicationPin:
        """Re-invoke the bound store readback adapter and refuse if the live publication has advanced or drifted."""
        _require(callable(self._readback_adapter), "missing_independent_readback_state", "missing readback_adapter")
        assert self._readback_adapter is not None
        live = self._readback_adapter()
        _require(isinstance(live, AcceptedStoreReadback), "invalid_store_readback", "expected AcceptedStoreReadback")
        _require(live.graph_id == self.graph_id, "readback_graph_id_mismatch", "live graph_id mismatch")
        _require(
            live.repository_identity == self.repository_identity,
            "readback_repository_identity_mismatch",
            "live repository_identity mismatch",
        )
        _require(live.backend == self.backend, "readback_backend_mismatch", "live backend mismatch")
        live_norm, live_receipt = _validate_publication_and_receipt_pair(live.accepted_publication, live.receipt)
        if live.projection_inputs is not None:
            _verify_projection_inputs(live.projection_inputs, live, live_norm, live_receipt)
        if live_norm["run_id"] != self.run_id or live_norm["generation"] != self.generation:
            raise RepresentationValidationError("stale_publication_receipt", "live store publication has advanced")
        _require(
            live_receipt == self.receipt and str(digest_json(live_receipt.to_mapping())) == self.receipt_identity,
            "stale_publication_receipt",
            "live store receipt disagrees with pinned receipt",
        )
        return self

    def is_factory_issued(self) -> bool:
        """Check this exact factory-issued object's fields, not a copied dataclass."""
        try:
            return self._factory_seal == (
                id(self), id(self._readback_adapter), str(digest_json(self.to_dict())),
            )
        except (AssertionError, AttributeError, TypeError, ValueError):
            return False

    @property
    def graph_candidate_id(self) -> str:
        assert self.receipt.portable is not None
        return self.receipt.portable.candidate_id

    @property
    def snapshot_vector(self) -> tuple[tuple[str, int, str], ...]:
        assert self.receipt.portable is not None
        return tuple(self.receipt.portable.snapshot_vector)

    @property
    def publication_bundle_id(self) -> str:
        assert self.receipt.portable is not None
        return self.receipt.portable.publication_bundle_id

    @property
    def snapshot_manifest_id(self) -> str:
        assert self.receipt.portable is not None
        return self.receipt.portable.snapshot_manifest_id

    @property
    def extraction_receipt_id(self) -> str:
        assert self.receipt.portable is not None
        return self.receipt.portable.extraction_receipt_id

    def snapshot_by_binding(self) -> dict[str, tuple[int, str]]:
        assert self.receipt.portable is not None
        return {b_id: (rev, snap) for b_id, rev, snap in self.receipt.portable.snapshot_vector}

    def to_dict(self) -> dict[str, Any]:
        assert self.receipt.portable is not None
        p = self.receipt.portable
        gens = self.receipt.generations
        return {
            "graph_id": self.graph_id,
            "repository_identity": self.repository_identity,
            "backend": self.backend,
            "run_id": self.run_id,
            "generation": self.generation,
            "publication_bundle_id": p.publication_bundle_id,
            "snapshot_manifest_id": p.snapshot_manifest_id,
            "extraction_receipt_id": p.extraction_receipt_id,
            "graph_candidate_id": p.candidate_id,
            "job_id": str(self.receipt.attempt.job_id),
            "attempt": int(self.receipt.attempt.attempt),
            "generations": dict(zip(gens.field_names(), (str(v) for v in gens.values()), strict=True)),
            "receipt_identity": self.receipt_identity,
            "snapshot_vector": [[b, r, s] for b, r, s in p.snapshot_vector],
            "admitted_public_bindings": sorted(self.admitted_public_bindings),
            "denied_bindings": dict(sorted(self.denied_bindings.items())),
            "policy_digest": self.policy_digest,
        }


def _classify_binding_metadata_privacy(bp: ResolvedBindingPolicy) -> str | None:
    bp.validate()
    if "inherit" in {
        bp.original_graph_privacy,
        bp.resolved_graph_privacy,
        bp.original_binding_privacy,
        bp.resolved_binding_privacy,
        bp.original_evidence_retention,
        bp.resolved_evidence_retention,
    }:
        return str(ExclusionReason.UNRESOLVED_INHERIT_POLICY.value)
    if bp.original_graph_privacy != ALLOWED_GRAPH_PRIVACY or bp.resolved_graph_privacy != ALLOWED_GRAPH_PRIVACY:
        return str(ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value)
    if bp.original_binding_privacy != ALLOWED_BINDING_PRIVACY or bp.resolved_binding_privacy != ALLOWED_BINDING_PRIVACY:
        return str(ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value)
    return None


def _check_selected_bindings(
    selected: Sequence[str] | None,
    denied: Mapping[str, str],
    valid_bindings: set[str] | Mapping[str, Any],
) -> str | None:
    if selected is None:
        return None
    if not isinstance(selected, (list, tuple, frozenset, set)) or not selected:
        return "empty_selected_bindings"
    for b_id in selected:
        if type(b_id) is not str or not b_id.strip():
            return "invalid_binding_id"
        if b_id in denied or b_id not in valid_bindings:
            return denied.get(b_id, "unknown_source_binding")
    return None


def _validate_complete_accepted_publication(raw_pub: Any) -> dict[str, Any]:
    """Validate that an accepted_publication mapping has all required pin, candidate, generation, and vector fields."""
    frozen_pub = freeze_jsonable(raw_pub)
    _require(isinstance(frozen_pub, Mapping), "invalid_accepted_publication", "must be a mapping")
    assert isinstance(frozen_pub, Mapping)
    normalized = _guard(
        lambda: normalize_accepted_publication(frozen_pub, require_pin=True, require_vector=True),
        "malformed_accepted_publication",
    )
    cand_id = frozen_pub.get("graph_candidate_id")
    _require(type(cand_id) is str and bool(cand_id.strip()), "malformed_accepted_publication", "graph_candidate_id required")
    for gen_field in ("source_generation", "config_generation", "extractor_generation", "canonicalizer_generation"):
        gen_val = frozen_pub.get(gen_field)
        _require(type(gen_val) is str and bool(gen_val.strip()), "malformed_accepted_publication", f"{gen_field} required")
        normalized[gen_field] = gen_val
    normalized["graph_candidate_id"] = cand_id
    return normalized


def _validate_publication_and_receipt_pair(
    raw_pub: Any, receipt: Any
) -> tuple[dict[str, Any], RunPublicationReceipt]:
    normalized = _validate_complete_accepted_publication(raw_pub)
    _require(isinstance(receipt, RunPublicationReceipt), "invalid_receipt", "RunPublicationReceipt required")
    validated_receipt = _guard(receipt.validate, "invalid_receipt")
    _require(validated_receipt.portable is not None, "missing_portable_receipt", "receipt.portable required")
    assert validated_receipt.portable is not None
    portable = validated_receipt.portable
    for k, a, b in (
        ("job_id", normalized["job_id"], str(validated_receipt.attempt.job_id)),
        ("attempt", normalized["attempt"], int(validated_receipt.attempt.attempt)),
        ("publication_bundle_id", normalized["publication_bundle_id"], portable.publication_bundle_id),
        ("snapshot_manifest_id", normalized["snapshot_manifest_id"], portable.snapshot_manifest_id),
        ("extraction_receipt_id", normalized["extraction_receipt_id"], portable.extraction_receipt_id),
        ("candidate_id", normalized["graph_candidate_id"], portable.candidate_id),
    ):
        _require(a == b, f"{k}_mismatch", f"{k} mismatch")
    _require(tuple(normalized["snapshot_vector"]) == tuple(portable.snapshot_vector), "snapshot_vector_mismatch", "snapshot_vector mismatch")
    rec_gens = validated_receipt.generations
    for gen_field, rec_gen_val in zip(rec_gens.field_names(), (str(v) for v in rec_gens.values()), strict=True):
        _require(normalized[gen_field] == rec_gen_val, "generation_mismatch", f"{gen_field} mismatch")
    return normalized, validated_receipt


def _verify_projection_inputs(
    proj_inputs: ProjectionInputs,
    live: AcceptedStoreReadback,
    normalized: Mapping[str, Any],
    validated_receipt: RunPublicationReceipt,
) -> None:
    try:
        checked = check_correspondence(proj_inputs)
    except CorrespondenceRefusal as exc:
        raise RepresentationValidationError(exc.code.value, exc.detail) from exc
    _require(proj_inputs.receipt == validated_receipt, "corpus_state_mismatch", "projection_inputs receipt mismatch")
    _require(
        checked.graph_id == live.graph_id
        and checked.repository_id == live.repository_identity
        and checked.backend == live.backend
        and type(checked.run_id) is int and checked.run_id == normalized["run_id"]
        and checked.publication_bundle_id == normalized["publication_bundle_id"]
        and checked.job_id == normalized["job_id"]
        and type(checked.attempt) is int and checked.attempt == normalized["attempt"]
        and checked.snapshot_manifest_id == normalized["snapshot_manifest_id"]
        and checked.extraction_receipt_id == normalized["extraction_receipt_id"]
        and checked.accepted_generation == normalized["generation"],
        "accepted_reference_mismatch",
        "store projection_inputs AcceptedPublicationReference disagrees with accepted_publication",
    )


def verify_publication_provenance(
    *,
    graph_id: str,
    repository_identity: str,
    backend: str,
    accepted_publication: Mapping[str, Any],
    receipt: RunPublicationReceipt,
    policy: BodyProjectionPolicy | Mapping[str, ResolvedBindingPolicy],
    selected_binding_ids: Sequence[str] | None = None,
    readback_adapter: PublicationReadbackAdapter | None = None,
    **extra_kwargs: Any,
) -> VerifiedPublicationPin:
    """Verify accepted publication, portable receipt, binding privacy, and live store readback correspondence."""
    _require("trusted" not in extra_kwargs and "trusted_caller" not in extra_kwargs, "caller_trusted_escape_forbidden", "trusted=True escape forbidden")
    _require("accepted_reference" not in extra_kwargs and "corpus_state" not in extra_kwargs, "caller_readback_object_forbidden", "pass readback_adapter")
    _require(not extra_kwargs, "unexpected_provenance_arguments", f"unexpected: {sorted(extra_kwargs)}")
    _require(type(graph_id) is str and bool(graph_id.strip()), "invalid_graph_id", "invalid graph_id")
    _require(backend in {"postgresql", "sqlite"}, "invalid_backend", f"unsupported backend: {backend!r}")
    _guard(lambda: checked_identity(repository_identity), "invalid_repository_identity")
    _require(repository_identity.startswith("repo1:"), "invalid_repository_identity", "must start with repo1:")

    if isinstance(policy, BodyProjectionPolicy):
        policy.validate()
        _require(policy.graph_id == graph_id, "policy_graph_mismatch", "policy.graph_id mismatch")
        binding_map = dict(policy.bindings)
        policy_digest = str(policy.policy_digest())
    elif isinstance(policy, Mapping):
        binding_map = {k: v.validate() for k, v in policy.items() if type(k) is str and isinstance(v, ResolvedBindingPolicy)}
        _require(len(binding_map) == len(policy), "invalid_policy", "all bindings must be str -> ResolvedBindingPolicy")
        policy_digest = str(digest_json({k: v.to_dict() for k, v in sorted(binding_map.items())}))
    else:
        raise RepresentationValidationError("invalid_policy", "policy must be BodyProjectionPolicy or Mapping")

    policy_denied = {b_id: str(r) for b_id, bp in sorted(binding_map.items()) if (r := _classify_binding_metadata_privacy(bp)) is not None}
    early_sel_err = _check_selected_bindings(selected_binding_ids, policy_denied, set(binding_map))
    _require(early_sel_err is None, early_sel_err or "", "selected_binding_ids refused by policy before readback")
    _require(callable(readback_adapter), "missing_independent_readback_state", "callable readback_adapter required")
    assert readback_adapter is not None

    normalized, validated_receipt = _validate_publication_and_receipt_pair(accepted_publication, receipt)
    live = readback_adapter()
    _require(isinstance(live, AcceptedStoreReadback), "invalid_store_readback", "expected AcceptedStoreReadback")
    _require(live.graph_id == graph_id, "readback_graph_id_mismatch", "store readback graph_id mismatch")
    _require(live.repository_identity == repository_identity, "readback_repository_identity_mismatch", "store readback repository_identity mismatch")
    _require(live.backend == backend, "readback_backend_mismatch", "store readback backend mismatch")
    live_norm, live_receipt = _validate_publication_and_receipt_pair(live.accepted_publication, live.receipt)
    if live.projection_inputs is not None:
        _verify_projection_inputs(live.projection_inputs, live, live_norm, live_receipt)
    _require(
        live_norm["run_id"] == normalized["run_id"] and live_norm["generation"] == normalized["generation"],
        "stale_publication_receipt", "caller publication disagrees with current store run/generation",
    )
    _require(live_receipt == validated_receipt and live_norm == normalized, "readback_correspondence_mismatch", "readback mismatch")

    assert validated_receipt.portable is not None
    vector_bindings = {b_id for b_id, _, _ in validated_receipt.portable.snapshot_vector}
    admitted_public: set[str] = set()
    denied: dict[str, str] = dict(policy_denied)
    for b_id in sorted(vector_bindings | set(binding_map)):
        if b_id in denied:
            continue
        if binding_map.get(b_id) is None:
            denied[b_id] = str(ExclusionReason.UNRESOLVED_INHERIT_POLICY.value)
        elif b_id in vector_bindings:
            admitted_public.add(b_id)
    sel_err = _check_selected_bindings(selected_binding_ids, denied, vector_bindings)
    _require(sel_err is None, sel_err or "", "selected_binding_ids refused")
    pin = VerifiedPublicationPin(
        graph_id, repository_identity, backend, normalized["run_id"], normalized["generation"],
        validated_receipt, str(digest_json(validated_receipt.to_mapping())), frozenset(admitted_public),
        MappingProxyType(denied), policy_digest, readback_adapter, _PROVENANCE_TOKEN,
    )
    object.__setattr__(pin, "_factory_seal", (id(pin), id(readback_adapter), str(digest_json(pin.to_dict()))))
    return pin


def verify_publication_provenance_from_adapter(
    readback_adapter: PublicationReadbackAdapter,
    *,
    policy: BodyProjectionPolicy | Mapping[str, ResolvedBindingPolicy],
    selected_binding_ids: Sequence[str] | None = None,
) -> VerifiedPublicationPin:
    """Invoke a trusted store readback adapter and verify its current publication, receipt, and policy."""
    _require(callable(readback_adapter), "missing_independent_readback_state", "callable readback_adapter required")
    live = readback_adapter()
    _require(isinstance(live, AcceptedStoreReadback), "invalid_store_readback", "expected AcceptedStoreReadback")
    return verify_publication_provenance(
        graph_id=live.graph_id, repository_identity=live.repository_identity, backend=live.backend,
        accepted_publication=live.accepted_publication, receipt=live.receipt, policy=policy,
        selected_binding_ids=selected_binding_ids, readback_adapter=readback_adapter,
    )


__all__ = [
    "CANONICAL_NODE_REPRESENTATION_VERSION", "MAX_JSON_COLLECTION_ITEMS", "MAX_JSON_DEPTH",
    "MAX_PUBLIC_STRING_LENGTH", "MAX_REPRESENTATION_RECORDS", "REPRESENTATION_POLICY_VERSION",
    "W5_FOUNDATION_SCHEMA_VERSION", "AcceptedStoreReadback", "PublicationReadbackAdapter",
    "RepresentationValidationError", "VerifiedPublicationPin", "_check_selected_bindings",
    "_guard", "_require", "_validate_complete_accepted_publication", "_validate_representation_string",
    "freeze_jsonable", "is_sanitized_public_string", "validate_relative_path",
    "verify_publication_provenance", "verify_publication_provenance_from_adapter",
]
