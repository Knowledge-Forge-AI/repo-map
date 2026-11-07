"""Model-independent canonical-node-v1 representation, digest, and provenance validation (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, ResolvedBindingPolicy
from common_lore_index.storage.publication import RunPublicationReceipt
from retrieval_semantic_primitives import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    ClaimedNodeRepresentation,
    ExcludedNodeRepresentation,
    VerifiedNodeRepresentation,
    canonical_node_v1_digest,
    encode_canonical_node_v1_bytes,
)
from retrieval_semantic_provenance import (
    CANONICAL_NODE_REPRESENTATION_VERSION,
    MAX_PUBLIC_STRING_LENGTH,
    MAX_REPRESENTATION_RECORDS,
    REPRESENTATION_POLICY_VERSION,
    W5_FOUNDATION_SCHEMA_VERSION,
    AcceptedStoreReadback,
    PublicationReadbackAdapter,
    RepresentationValidationError,
    VerifiedPublicationPin,
    _check_selected_bindings,
    _require,
    _validate_representation_string,
    freeze_jsonable,
    is_sanitized_public_string,
    validate_relative_path,
    verify_publication_provenance,
    verify_publication_provenance_from_adapter,
)
from retrieval_semantic_record_validation import (
    normalize_accepted_evidence,
    normalize_accepted_node,
    normalize_claimed_representation,
)

_SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class RepresentationValidationReport:
    status: str
    refusal_code: str | None
    provenance: VerifiedPublicationPin
    verified_entries: tuple[VerifiedNodeRepresentation, ...]
    excluded_entries: tuple[ExcludedNodeRepresentation, ...]
    total_eligible_count: int
    partial_coverage: bool
    truncated: bool
    coverage_ceiling: int = MAX_REPRESENTATION_RECORDS

    @property
    def representations(self) -> tuple[VerifiedNodeRepresentation, ...]:
        return self.verified_entries

    @property
    def excluded(self) -> tuple[ExcludedNodeRepresentation, ...]:
        return self.excluded_entries

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": W5_FOUNDATION_SCHEMA_VERSION,
            "policy_version": REPRESENTATION_POLICY_VERSION,
            "representation_version": CANONICAL_NODE_REPRESENTATION_VERSION,
            "input_digest_validation": "independent_accepted_node_recomputation",
            "status": self.status,
            "refusal_code": self.refusal_code,
            "provenance": self.provenance.to_dict(),
            "verified_entries": [e.to_dict() for e in self.verified_entries],
            "excluded_entries": [e.to_dict() for e in self.excluded_entries],
            "verified_count": len(self.verified_entries),
            "total_eligible_count": self.total_eligible_count,
            "partial_coverage": self.partial_coverage,
            "truncated": self.truncated,
            "coverage_ceiling": self.coverage_ceiling,
        }


def _parse_evidence_metadata(
    ev: AcceptedEvidenceRecord, snapshots: Mapping[str, tuple[int, str]], markers: tuple[str, ...]
) -> tuple[str, str, str] | None:
    raw_meta = ev.metadata_json
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except ValueError:
            return None
    if not isinstance(raw_meta, Mapping):
        return None
    b_id, snap_id, rel_path = raw_meta.get("binding_id"), raw_meta.get("snapshot_id"), raw_meta.get("source_relative_path")
    if type(b_id) is not str or type(snap_id) is not str or type(rel_path) is not str:
        return None
    if snapshots.get(b_id, (0, ""))[1] != snap_id:
        return None
    try:
        validate_relative_path(rel_path, "source_relative_path")
        _validate_representation_string(rel_path, "source_relative_path", private_markers=markers)
        _validate_representation_string(ev.evidence_key, "evidence_key", private_markers=markers)
    except (ValueError, RepresentationValidationError):
        return None
    if ev.path is not None and (
        type(ev.path) is not str or ev.path.startswith("/withheld/") or not is_sanitized_public_string(ev.path, private_markers=markers)
    ):
        return None
    return b_id, snap_id, rel_path


def validate_canonical_node_representations(
    provenance: VerifiedPublicationPin,
    *,
    accepted_nodes: Sequence[Any],
    accepted_evidence: Sequence[Any],
    claimed_entries: Sequence[Any] | None = None,
    selected_binding_ids: Sequence[str] | None = None,
    max_records: int = MAX_REPRESENTATION_RECORDS,
    private_markers: Sequence[str] = (),
) -> RepresentationValidationReport:
    """Validate canonical-node-v1 representations against independently accepted nodes and evidence."""
    _require(isinstance(provenance, VerifiedPublicationPin), "unverified_publication_pin", "VerifiedPublicationPin required")
    _require(type(max_records) is int and 1 <= max_records <= MAX_REPRESENTATION_RECORDS, "invalid_max_records", "invalid max_records")
    snapshots = provenance.snapshot_by_binding()
    sel_err = _check_selected_bindings(selected_binding_ids, provenance.denied_bindings, snapshots)
    if sel_err is not None:
        return RepresentationValidationReport("refused", sel_err, provenance, (), (), 0, False, False, max_records)
    try:
        provenance.revalidate_current()
    except RepresentationValidationError as exc:
        return RepresentationValidationReport("refused", exc.code, provenance, (), (), 0, False, False, max_records)
    markers = tuple(str(m) for m in private_markers if m)
    selected_filter = frozenset(selected_binding_ids) if selected_binding_ids is not None else provenance.admitted_public_bindings
    nodes_by_key: dict[str, AcceptedNodeRecord] = {}
    for raw_n in accepted_nodes:
        try:
            node = normalize_accepted_node(raw_n)
        except RepresentationValidationError as exc:
            return RepresentationValidationReport("refused", exc.code, provenance, (), (), 0, False, False, max_records)
        _require(node.canonical_key not in nodes_by_key, "duplicate_accepted_node", f"duplicate key {node.canonical_key!r}")
        nodes_by_key[node.canonical_key] = node
    ev_by_node: dict[str, list[AcceptedEvidenceRecord]] = {}
    for raw_e in accepted_evidence:
        try:
            ev = normalize_accepted_evidence(raw_e)
        except RepresentationValidationError as exc:
            return RepresentationValidationReport("refused", exc.code, provenance, (), (), 0, False, False, max_records)
        ev_by_node.setdefault(ev.canonical_key, []).append(ev)
    eligible_by_pair: dict[tuple[str, str], VerifiedNodeRepresentation] = {}
    excluded: list[ExcludedNodeRepresentation] = []
    for c_key in sorted(nodes_by_key):
        node = nodes_by_key[c_key]
        if node.graph_key_version != 1 or node.last_seen_run_id != provenance.run_id:
            excluded.append(ExcludedNodeRepresentation(c_key, None, "stale_or_unsupported_node", "inactive node"))
            continue
        try:
            rep_bytes = encode_canonical_node_v1_bytes(node.canonical_key, node.kind, node.display_name, private_markers=markers)
        except RepresentationValidationError as exc:
            excluded.append(ExcludedNodeRepresentation(c_key, None, exc.code, exc.detail))
            continue
        digest = "sha256:" + hashlib.sha256(rep_bytes).hexdigest()
        all_evs = [e for e in ev_by_node.get(c_key, ()) if e.run_id == provenance.run_id and e.graph_key_version == 1]
        node_evs = [e for e in all_evs if e.link_kind not in {"inferred", "inferred_from_edge"}]
        if not all_evs or not node_evs:
            reason_code = "inferred_only_evidence_excluded" if all_evs else "missing_accepted_evidence"
            excluded.append(ExcludedNodeRepresentation(c_key, None, reason_code, "no observed evidence"))
            continue
        if any(isinstance(e.path, str) and e.path.startswith("/withheld/") for e in node_evs):
            excluded.append(ExcludedNodeRepresentation(c_key, None, "withheld_evidence_path", "withheld path"))
            continue
        parsed_by_binding: dict[str, list[tuple[str, str]]] = {}
        has_malformed = has_denied = False
        for ev in node_evs:
            parsed = _parse_evidence_metadata(ev, snapshots, markers)
            if parsed is None:
                has_malformed = True
                break
            b_id, _snap_id, rel_path = parsed
            if b_id in provenance.denied_bindings or b_id not in provenance.admitted_public_bindings:
                has_denied = True
            parsed_by_binding.setdefault(b_id, []).append((rel_path, ev.evidence_key))
        if has_malformed:
            excluded.append(ExcludedNodeRepresentation(c_key, None, "withheld_or_malformed_evidence", "malformed evidence"))
        elif has_denied and any(b in provenance.admitted_public_bindings for b in parsed_by_binding):
            excluded.append(ExcludedNodeRepresentation(c_key, None, "mixed_or_unverifiable_provenance", "mixed provenance"))
        elif has_denied:
            for b_id in sorted(parsed_by_binding):
                excluded.append(ExcludedNodeRepresentation(c_key, b_id, provenance.denied_bindings.get(b_id, "binding_privacy_not_authorized"), "denied binding"))
        else:
            for b_id in sorted(parsed_by_binding):
                if b_id not in selected_filter:
                    excluded.append(ExcludedNodeRepresentation(c_key, b_id, "binding_not_selected", "outside selected scope"))
                else:
                    rev, snap_id = snapshots[b_id]
                    pairs = parsed_by_binding[b_id]
                    eligible_by_pair[(c_key, b_id)] = VerifiedNodeRepresentation(
                        c_key, node.kind, node.display_name, b_id, snap_id, rev,
                        tuple(sorted({p for p, _ in pairs})), tuple(sorted({ek for _, ek in pairs})), len(rep_bytes), digest,
                    )
    if claimed_entries is not None:
        return _validate_claimed_batch(provenance, claimed_entries, eligible_by_pair, excluded, snapshots, selected_filter, max_records)
    ordered = [eligible_by_pair[k] for k in sorted(eligible_by_pair, key=lambda i: (i[0].encode("utf-8"), i[1].encode("utf-8")))]
    capped = tuple(ordered[:max_records])
    truncated = len(capped) < len(ordered)
    return RepresentationValidationReport("ok", None, provenance, capped, tuple(excluded), len(ordered), truncated or bool(excluded), truncated, max_records)


def build_and_validate_node_representations(
    *,
    graph_id: str,
    repository_identity: str,
    backend: str,
    accepted_publication: Mapping[str, Any],
    receipt: RunPublicationReceipt,
    policy: BodyProjectionPolicy | Mapping[str, ResolvedBindingPolicy],
    accepted_nodes: Sequence[Any],
    accepted_evidence: Sequence[Any],
    claimed_entries: Sequence[Any] | None = None,
    selected_binding_ids: Sequence[str] | None = None,
    max_records: int = MAX_REPRESENTATION_RECORDS,
    private_markers: Sequence[str] = (),
    readback_adapter: PublicationReadbackAdapter | None = None,
    **extra_kwargs: Any,
) -> RepresentationValidationReport:
    """Verify publication provenance and validate canonical-node-v1 representations in one call."""
    pin = verify_publication_provenance(
        graph_id=graph_id, repository_identity=repository_identity, backend=backend,
        accepted_publication=accepted_publication, receipt=receipt, policy=policy,
        selected_binding_ids=selected_binding_ids, readback_adapter=readback_adapter, **extra_kwargs,
    )
    return validate_canonical_node_representations(
        pin, accepted_nodes=accepted_nodes, accepted_evidence=accepted_evidence,
        claimed_entries=claimed_entries, selected_binding_ids=selected_binding_ids,
        max_records=max_records, private_markers=private_markers,
    )


def _validate_claimed_batch(
    provenance: VerifiedPublicationPin,
    claimed_entries: Sequence[Any],
    eligible_by_pair: Mapping[tuple[str, str], VerifiedNodeRepresentation],
    excluded: Sequence[ExcludedNodeRepresentation],
    snapshots: Mapping[str, tuple[int, str]],
    selected_filter: frozenset[str],
    max_records: int,
) -> RepresentationValidationReport:
    def refuse(code: str) -> RepresentationValidationReport:
        return RepresentationValidationReport("refused", code, provenance, (), tuple(excluded), len(eligible_by_pair), True, False, max_records)

    if not isinstance(claimed_entries, (list, tuple)) or not 1 <= len(claimed_entries) <= max_records:
        return refuse("invalid_batch_size")
    seen_identities: set[tuple[str, str]] = set()
    verified_batch: list[VerifiedNodeRepresentation] = []
    for raw_claim in claimed_entries:
        try:
            claim = normalize_claimed_representation(raw_claim)
        except RepresentationValidationError as exc:
            return refuse(exc.code)
        pair = (claim.canonical_key, claim.source_binding_id)
        for bad, code in (
            (type(claim.canonical_key) is not str or type(claim.source_binding_id) is not str, "invalid_claim_identity"),
            (type(claim.input_digest) is not str or _SHA256_DIGEST_RE.fullmatch(claim.input_digest) is None, "invalid_input_digest_format"),
            (claim.source_binding_id in provenance.denied_bindings, provenance.denied_bindings.get(claim.source_binding_id, "binding_privacy_not_authorized")),
            (claim.source_binding_id not in snapshots, "unknown_source_binding"),
            (claim.source_binding_id not in selected_filter, "out_of_scope_binding"),
            (pair in seen_identities, "duplicate_representation_identity"),
        ):
            if bad:
                return refuse(code)
        seen_identities.add(pair)
        accepted_rep = eligible_by_pair.get(pair)
        if accepted_rep is None:
            return refuse("unaccepted_or_excluded_node_provenance")
        for bad, code in (
            (claim.snapshot_id is not None and claim.snapshot_id != accepted_rep.snapshot_id, "snapshot_id_mismatch"),
            (claim.claimed_kind is not None and claim.claimed_kind != accepted_rep.kind, "accepted_node_field_mismatch"),
            (claim.claimed_display_name is not None and claim.claimed_display_name != accepted_rep.display_name, "accepted_node_field_mismatch"),
            (claim.input_digest != accepted_rep.input_digest, "representation_digest_mismatch"),
        ):
            if bad:
                return refuse(code)
        verified_batch.append(accepted_rep)
    total_eligible = len(eligible_by_pair)
    truncated = len(verified_batch) < total_eligible
    return RepresentationValidationReport("ok", None, provenance, tuple(verified_batch), tuple(excluded), total_eligible, truncated or bool(excluded), truncated, max_records)


__all__ = [
    "CANONICAL_NODE_REPRESENTATION_VERSION", "MAX_PUBLIC_STRING_LENGTH", "MAX_REPRESENTATION_RECORDS",
    "REPRESENTATION_POLICY_VERSION", "W5_FOUNDATION_SCHEMA_VERSION", "AcceptedEvidenceRecord",
    "AcceptedNodeRecord", "AcceptedStoreReadback", "ClaimedNodeRepresentation",
    "ExcludedNodeRepresentation", "PublicationReadbackAdapter", "RepresentationValidationError",
    "RepresentationValidationReport", "VerifiedNodeRepresentation", "VerifiedPublicationPin",
    "_require", "_validate_representation_string", "build_and_validate_node_representations",
    "canonical_node_v1_digest", "encode_canonical_node_v1_bytes", "freeze_jsonable",
    "is_sanitized_public_string", "validate_canonical_node_representations",
    "validate_relative_path", "verify_publication_provenance", "verify_publication_provenance_from_adapter",
]
