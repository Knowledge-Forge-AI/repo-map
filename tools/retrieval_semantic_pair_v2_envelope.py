"""Closed, public-safe QueryEnvelope projections for the W5 V2 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import digest_bytes, refuse


_MODES = frozenset({
    "exact_identity", "current_literal_enumeration", "literal_captured_text",
    "ranked_discovery", "graph_investigation", "semantic_discovery",
})
_BACKENDS = frozenset({"sqlite", "postgresql", "captured_reference", "native_filesystem"})
_CAPABILITIES = frozenset({"available", "partial", "refused", "stale", "unavailable", "failed", "not_run"})
_SURFACES = frozenset({"captured_text", "stored_metadata", "graph_topology", "direct_handoff", "none"})
_EXECUTION_STATES = frozenset({"completed", "failed", "unavailable", "refused", "not_run"})
_PUBLIC_REASONS = frozenset({
    "backend_unsupported", "capability_not_admitted", "artifact_store_expired", "projection_absent",
    "external_tool_unavailable", "unsupported_semantic_query_mode", "index_not_selected",
    "hnsw_index_not_selected", "query_not_admitted", "source_scope_refused",
    "admitted_exact_query_not_executed", "admitted_hybrid_query_not_executed",
    "admitted_hnsw_execution_failed",
    "fixture_not_run", "not_run", "timeout", "withheld",
})


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _token(value: object, code: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not value or len(value) > 256:
        raise refuse(code)
    if any(ord(char) < 32 for char in value) or any(char in "/\\" for char in value):
        raise refuse(code)
    return value


def _digest_or_token(value: object, code: str) -> str | None:
    if value is None:
        return None
    text = _token(value, code)
    if text is None:
        return None
    if text.startswith("sha256:") and len(text) == 71:
        if all(char in "0123456789abcdef" for char in text[7:]):
            return text
        raise refuse(code)
    return text


def _required_digest(value: object, code: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise refuse(code)
    if any(char not in "0123456789abcdef" for char in value[7:]):
        raise refuse(code)
    return value


def _reason(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise refuse("pair_v2_reason_type")
    return value if value in _PUBLIC_REASONS else "withheld"


def _mode(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise refuse("pair_v2_mode_type")
    if value not in _MODES:
        raise refuse("pair_v2_mode_value")
    return value


def _state(value: object, allowed: frozenset[str], code: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise refuse(code)
    if value not in allowed:
        raise refuse(code)
    return value


def _fallback(envelope: Mapping[str, object]) -> dict[str, object] | None:
    raw = envelope.get("fallback")
    if raw is None:
        return None
    fallback = _mapping(raw, "pair_v2_fallback")
    if fallback.get("caller_selected") is not True:
        raise refuse("pair_v2_fallback_caller")
    return {
        "caller_selected": True,
        "from_mode": _mode(fallback.get("from_mode")),
        "to_mode": _mode(fallback.get("to_mode")),
        "reason_code": _reason(fallback.get("reason_code")),
    }


def _source_prefix(value: object) -> dict[str, object]:
    if value is None:
        return {"status": "not_recorded", "sha256": None}
    if type(value) is not str or not value or len(value) > 1024 or any(ord(char) < 32 for char in value):
        raise refuse("pair_v2_scope_path")
    return {"status": "withheld", "sha256": digest_bytes(value.encode("utf-8"))}


def _scope(envelope: Mapping[str, object]) -> dict[str, object] | None:
    raw_scope = envelope.get("scope")
    if raw_scope is None:
        return None
    scope = _mapping(raw_scope, "pair_v2_scope")
    selected = scope.get("selected_binding_ids")
    if selected is None:
        selected_count = None
        selected_digest = None
    elif type(selected) is list and all(type(item) is str and item for item in selected):
        if len(set(selected)) != len(selected):
            raise refuse("pair_v2_scope_bindings")
        selected_count = len(selected)
        selected_digest = digest_bytes(canonical_json_bytes(sorted(selected)))
    else:
        raise refuse("pair_v2_scope_bindings")
    backend = scope.get("backend")
    if backend is not None and (type(backend) is not str or backend not in _BACKENDS):
        raise refuse("pair_v2_scope_backend")
    return {
        "graph_id": _digest_or_token(scope.get("graph_id"), "pair_v2_scope_graph"),
        "backend": backend,
        "publication_bundle_id": _digest_or_token(scope.get("publication_bundle_id"), "pair_v2_scope_publication"),
        "snapshot_manifest_id": _digest_or_token(scope.get("snapshot_manifest_id"), "pair_v2_scope_snapshot"),
        "selected_binding_count": selected_count,
        "selected_binding_ids_sha256": selected_digest,
        "source_path_prefix": _source_prefix(scope.get("source_path_prefix")),
    }


def _surface_projection(envelope: Mapping[str, object]) -> dict[str, object]:
    if "hits" not in envelope:
        return {"status": "not_recorded", "counts": None}
    hits = envelope.get("hits")
    if type(hits) is not list:
        raise refuse("pair_v2_surface_hits")
    if not hits:
        return {"status": "empty", "counts": {}}
    counts: dict[str, int] = {}
    missing_surface = False
    for raw_hit in hits:
        hit = _mapping(raw_hit, "pair_v2_surface_hit")
        if "match_surface" not in hit:
            missing_surface = True
            continue
        surface = hit.get("match_surface")
        if type(surface) is not str or surface not in _SURFACES - {"none"}:
            raise refuse("pair_v2_surface")
        counts[surface] = counts.get(surface, 0) + 1
    if missing_surface:
        return {"status": "not_recorded", "counts": None}
    return {"status": "recorded", "counts": dict(sorted(counts.items()))}


def project_envelope(event: Mapping[str, object] | None) -> dict[str, object] | None:
    """Project closed envelope fields; hits, locators, and raw paths never cross."""

    if event is None or event.get("envelope") is None:
        return None
    envelope = _mapping(event.get("envelope"), "pair_v2_envelope")
    provenance = envelope.get("provenance")
    publication = None
    if isinstance(provenance, Mapping):
        publication = _digest_or_token(
            provenance.get("publication_identity"), "pair_v2_publication_identity"
        )
    scope = _scope(envelope)
    if publication is None and isinstance(scope, Mapping):
        publication = cast(str | None, scope.get("publication_bundle_id"))
    surfaces = _surface_projection(envelope)
    complete = envelope.get("scope_complete")
    if complete is not None and type(complete) is not bool:
        raise refuse("pair_v2_scope_complete")
    match_surface = _state(envelope.get("match_surface"), _SURFACES, "pair_v2_surface")
    counts = surfaces.get("counts")
    if match_surface is None and surfaces["status"] == "recorded" and isinstance(counts, Mapping) and len(counts) == 1:
        match_surface = next(iter(counts))
    omissions = envelope.get("omissions")
    omission_reasons: list[str] = []
    if omissions is not None:
        if type(omissions) is not list:
            raise refuse("pair_v2_omissions")
        for omission in omissions:
            reason = _reason(_mapping(omission, "pair_v2_omission").get("reason_code"))
            if reason is not None:
                omission_reasons.append(reason)
    return {
        "contract_version": _token(envelope.get("contract_version"), "pair_v2_contract"),
        "requested_mode": _mode(envelope.get("requested_mode")),
        "effective_mode": _mode(envelope.get("effective_mode")),
        "match_surface": match_surface,
        "match_surfaces": surfaces,
        "capability_state": _state(envelope.get("capability_state"), _CAPABILITIES, "pair_v2_capability"),
        "scope": scope,
        "ordering_policy_version": _token(envelope.get("ordering_policy_version"), "pair_v2_ordering"),
        "scope_complete": complete,
        "fallback": _fallback(envelope),
        "unavailable_reason": _reason(envelope.get("unavailable_reason")),
        "refusal_code": _reason(envelope.get("refusal_code")),
        "publication_identity": publication,
        "omission_count": len(omissions) if type(omissions) is list else None,
        "omission_reason_codes": sorted(set(omission_reasons)),
    }


def _validate_surfaces(value: object) -> None:
    surfaces = _mapping(value, "pair_v2_surfaces")
    if frozenset(surfaces) != {"status", "counts"}:
        raise refuse("pair_v2_surfaces")
    status = surfaces.get("status")
    if type(status) is not str or status not in {"recorded", "empty", "not_recorded"}:
        raise refuse("pair_v2_surfaces")
    counts = surfaces.get("counts")
    if status == "not_recorded":
        if counts is not None:
            raise refuse("pair_v2_surfaces")
        return
    count_map = _mapping(counts, "pair_v2_surfaces")
    if any(
        type(key) is not str or key not in _SURFACES - {"none"}
        or type(item) is not int or item < 1 for key, item in count_map.items()
    ):
        raise refuse("pair_v2_surfaces")
    if status == "empty" and count_map:
        raise refuse("pair_v2_surfaces")
    if status == "recorded" and not count_map:
        raise refuse("pair_v2_surfaces")


def validate_projected_envelope(value: object) -> None:
    if value is None:
        return
    envelope = _mapping(value, "pair_v2_envelope")
    expected = {
        "contract_version", "requested_mode", "effective_mode", "match_surface", "match_surfaces",
        "capability_state", "scope", "ordering_policy_version", "scope_complete", "fallback",
        "unavailable_reason", "refusal_code", "publication_identity", "omission_count",
        "omission_reason_codes",
    }
    if frozenset(envelope) != expected:
        raise refuse("pair_v2_envelope_fields")
    _token(envelope.get("contract_version"), "pair_v2_contract")
    _mode(envelope.get("requested_mode"))
    _mode(envelope.get("effective_mode"))
    _state(envelope.get("match_surface"), _SURFACES, "pair_v2_surface")
    _validate_surfaces(envelope.get("match_surfaces"))
    _state(envelope.get("capability_state"), _CAPABILITIES, "pair_v2_capability")
    complete = envelope.get("scope_complete")
    if complete is not None and type(complete) is not bool:
        raise refuse("pair_v2_scope_complete")
    _token(envelope.get("ordering_policy_version"), "pair_v2_ordering")
    _digest_or_token(envelope.get("publication_identity"), "pair_v2_publication_identity")
    scope = envelope.get("scope")
    if scope is not None:
        scope_map = _mapping(scope, "pair_v2_scope")
        if frozenset(scope_map) != {
            "graph_id", "backend", "publication_bundle_id", "snapshot_manifest_id", "selected_binding_count",
            "selected_binding_ids_sha256", "source_path_prefix",
        }:
            raise refuse("pair_v2_scope_fields")
        _digest_or_token(scope_map.get("graph_id"), "pair_v2_scope_graph")
        backend = scope_map.get("backend")
        if backend is not None and (type(backend) is not str or backend not in _BACKENDS):
            raise refuse("pair_v2_scope_backend")
        _digest_or_token(scope_map.get("publication_bundle_id"), "pair_v2_scope_publication")
        _digest_or_token(scope_map.get("snapshot_manifest_id"), "pair_v2_scope_snapshot")
        count = scope_map.get("selected_binding_count")
        if count is not None and (type(count) is not int or count < 0):
            raise refuse("pair_v2_scope_bindings")
        if scope_map.get("selected_binding_ids_sha256") is not None:
            _required_digest(scope_map["selected_binding_ids_sha256"], "pair_v2_scope_bindings")
        prefix = _mapping(scope_map.get("source_path_prefix"), "pair_v2_scope_path")
        if frozenset(prefix) != {"status", "sha256"} or prefix.get("status") not in {"withheld", "not_recorded"}:
            raise refuse("pair_v2_scope_path")
        if prefix.get("status") == "not_recorded" and prefix.get("sha256") is not None:
            raise refuse("pair_v2_scope_path")
        if prefix.get("status") == "withheld":
            _required_digest(prefix.get("sha256"), "pair_v2_scope_path")
    fallback = envelope.get("fallback")
    if fallback is not None:
        fallback_map = _mapping(fallback, "pair_v2_fallback")
        if frozenset(fallback_map) != {"caller_selected", "from_mode", "to_mode", "reason_code"}:
            raise refuse("pair_v2_fallback_fields")
        if fallback_map.get("caller_selected") is not True:
            raise refuse("pair_v2_fallback_caller")
        _mode(fallback_map.get("from_mode"))
        _mode(fallback_map.get("to_mode"))
        _reason(fallback_map.get("reason_code"))
    count = envelope.get("omission_count")
    if count is not None and (type(count) is not int or count < 0):
        raise refuse("pair_v2_envelope_count")
    for field in ("unavailable_reason", "refusal_code"):
        if _reason(envelope.get(field)) != envelope.get(field):
            raise refuse("pair_v2_reason_value")
    reasons = envelope.get("omission_reason_codes")
    if type(reasons) is not list or any(
        type(reason) is not str or reason not in _PUBLIC_REASONS for reason in reasons
    ):
        raise refuse("pair_v2_omissions")


__all__ = [
    "_EXECUTION_STATES", "_fallback", "_mapping", "_mode", "_MODES", "_reason", "_state", "_token",
    "project_envelope", "validate_projected_envelope",
]
