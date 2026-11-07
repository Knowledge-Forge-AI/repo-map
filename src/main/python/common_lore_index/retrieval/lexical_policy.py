"""PostgreSQL lexical generation policy resolution, binding digests, and reclassification checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.retrieval.projection_policy import (
     ALLOWED_BINDING_PRIVACY,
    ALLOWED_EVIDENCE_RETENTION,
    ALLOWED_GRAPH_PRIVACY,
    BodyProjectionPolicy,
    ExclusionReason,
    ResolvedBindingPolicy,
    _is_email_role_or_path,
    _is_feed_role_or_path,
)

LEXICAL_POLICY_VERSION = "cloe-lexical-policy-v1"
LEXICAL_REPRESENTATION_VERSION = "cloe-lexical-pg-fts-v1"
LEXICAL_TEXT_CONFIG = "pg_catalog.simple"
LEXICAL_RANKING_FUNCTION = "ts_rank_cd(weight={0.1,0.2,0.4,1.0},normalization=32)"
LEXICAL_NORMALIZATION_FLAGS = 32
LEXICAL_ALIAS_SPLIT_VERSION = "identifier-path-split-v1"

PRODUCTION_MAX_PROJECTED_FILES = 65536
PRODUCTION_MAX_AGGREGATE_INPUT_BYTES = 268435456
PRODUCTION_MAX_INPUT_ARTIFACT_BYTES = 1048576
PRODUCTION_MAX_PROJECTED_FILE_BYTES = 262144
PRODUCTION_MAX_CHUNK_LINES = 80
PRODUCTION_MAX_CHUNK_BYTES = 8192


def normalize_lexical_path_prefix(value: str) -> str:
    """Normalize a literal relative path prefix without resolving traversal."""
    if not isinstance(value, str):
        raise ValueError("lexical path prefixes must be strings")
    prefix = value.strip().rstrip("/")
    if (
        not prefix or prefix.startswith(("/", "~"))
        or any(character in prefix for character in ("\x00", "\\", ":", "*", "?", "[", "]"))
        or any(part in {"", ".", ".."} for part in prefix.split("/"))
    ):
        raise ValueError("lexical path prefixes must be safe literal relative path segments")
    return prefix


_PRIVACY_EXCLUSION_REASONS = frozenset(
    {
        ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value,
        ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value,
        ExclusionReason.RETENTION_NOT_AUTHORIZED.value,
        ExclusionReason.EMAIL_BODY_FORBIDDEN.value,
        ExclusionReason.FEED_BODY_FORBIDDEN.value,
        ExclusionReason.UNRESOLVED_INHERIT_POLICY.value,
    }
)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def resolve_graph_privacy_for_lexical(graph: OpsGraphConfig) -> tuple[str, str]:
    """Resolve (original_graph_privacy, resolved_graph_privacy) for single-root or multi-binding graphs."""
    return graph.privacy, graph.privacy


def _binding_source_kind_str(binding: OpsGraphSourceBindingConfig) -> str:
    sk = binding.source_kind
    return str(sk.value) if hasattr(sk, "value") else str(sk)


def _evaluate_resolved_binding_exclusion(
    resolved: ResolvedBindingPolicy,
    raw_binding: OpsGraphSourceBindingConfig,
) -> ExclusionReason | None:
    if not raw_binding.enabled:
        return ExclusionReason.BINDING_NOT_SELECTED
    if "inherit" in {
        resolved.resolved_graph_privacy,
        resolved.resolved_binding_privacy,
        resolved.resolved_evidence_retention,
    }:
        return ExclusionReason.UNRESOLVED_INHERIT_POLICY
    if resolved.resolved_graph_privacy != ALLOWED_GRAPH_PRIVACY:
        return ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED
    if resolved.resolved_binding_privacy != ALLOWED_BINDING_PRIVACY:
        return ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED
    if resolved.resolved_evidence_retention != ALLOWED_EVIDENCE_RETENTION:
        return ExclusionReason.RETENTION_NOT_AUTHORIZED
    if _is_email_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN
    if _is_feed_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.FEED_BODY_FORBIDDEN
    return None


def _binding_config_fingerprint_payload(
    binding: OpsGraphSourceBindingConfig,
    resolved: ResolvedBindingPolicy,
) -> dict[str, Any]:
    return {
        "schema": LEXICAL_POLICY_VERSION,
        "resolved_binding_policy": resolved.to_dict(),
        "binding_config": {
            "binding_id": binding.binding_id,
            "alias": binding.alias,
            "role": binding.role,
            "source_kind": _binding_source_kind_str(binding),
            "privacy": binding.privacy,
            "evidence_retention": binding.evidence_retention,
            "enabled": binding.enabled,
            "revision": binding.revision,
            "include_paths": list(binding.include_paths),
            "exclude_paths": list(binding.exclude_paths),
            "selection_policy_id": binding.selection_policy_id,
            "logical_root": binding.logical_root,
            "repository_name": binding.repository_name,
            "extractor_profile": binding.extractor_profile,
            "resolution_policy": binding.resolution_policy,
            "source_definition_id": binding.source_definition_id,
            "root_and_input_sha256": _canonical_sha256(
                {
                    "root_path": str(binding.root_path or ""),
                    "input_name": str(binding.input_name or ""),
                }
            ),
        },
    }


@dataclass(frozen=True)
class LexicalGenerationPolicy:
    """Resolved lexical generation policy and per-binding policy digests."""

    policy_version: str
    resolved_graph_privacy: str
    body_policy: BodyProjectionPolicy
    binding_policy_digests: Mapping[str, str]
    admitted_binding_ids: tuple[str, ...]
    excluded_binding_ids: tuple[str, ...]
    excluded_binding_reasons: Mapping[str, str]
    policy_digest: str

    def is_binding_admitted(self, binding_id: str) -> bool:
        return binding_id in self.admitted_binding_ids

    def refusal_code_for_binding(self, binding_id: str) -> str:
        reason = self.excluded_binding_reasons.get(binding_id)
        return reason or ExclusionReason.BINDING_NOT_SELECTED.value

    def check_reclassification_against_published(
        self,
        *,
        published_policy_digest: str,
        published_admitted_binding_ids: tuple[str, ...],
        published_binding_digests: Mapping[str, str],
    ) -> tuple[str, str | None]:
        """Return ('ok'|'refused'|'stale', code_or_detail) comparing live policy to published generation."""
        if self.resolved_graph_privacy != "public-dev":
            return "refused", ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value
        for b_id in published_admitted_binding_ids:
            if b_id in self.excluded_binding_reasons:
                reason = self.excluded_binding_reasons[b_id]
                if reason in _PRIVACY_EXCLUSION_REASONS:
                    return "refused", reason
                return "stale", f"lexical_binding_excluded:{b_id}:{reason}"
            if self.binding_policy_digests.get(b_id) != published_binding_digests.get(b_id):
                return "stale", f"lexical_binding_policy_digest_changed:{b_id}"
        if self.policy_digest != published_policy_digest:
            return "stale", "lexical_policy_digest_changed"
        return "ok", None


def build_lexical_generation_policy(
    graph: OpsGraphConfig,
    *,
    selected_binding_ids: Sequence[str] | None = None,
    max_projected_files: int = PRODUCTION_MAX_PROJECTED_FILES,
    max_aggregate_input_bytes: int = PRODUCTION_MAX_AGGREGATE_INPUT_BYTES,
    max_input_artifact_bytes: int = PRODUCTION_MAX_INPUT_ARTIFACT_BYTES,
    max_projected_file_bytes: int = PRODUCTION_MAX_PROJECTED_FILE_BYTES,
    max_chunk_lines: int = PRODUCTION_MAX_CHUNK_LINES,
    max_chunk_bytes: int = PRODUCTION_MAX_CHUNK_BYTES,
) -> LexicalGenerationPolicy:
    """Build deterministic LexicalGenerationPolicy from a live OpsGraphConfig."""
    orig_privacy, res_privacy = resolve_graph_privacy_for_lexical(graph)
    raw_bindings = graph.effective_source_bindings
    by_id = {b.binding_id: b for b in raw_bindings}
    explicit_selection = frozenset(selected_binding_ids) if selected_binding_ids is not None else None

    resolved_map: dict[str, ResolvedBindingPolicy] = {}
    binding_digests: dict[str, str] = {}
    admitted: list[str] = []
    excluded: list[str] = []
    excluded_reasons: dict[str, str] = {}

    eligible_admitted: list[str] = []
    policy_excluded_reasons: dict[str, str] = {}

    for b in sorted(raw_bindings, key=lambda item: item.binding_id):
        resolved_b = ResolvedBindingPolicy(
            binding_id=b.binding_id,
            alias=b.alias,
            role=b.role,
            source_kind=_binding_source_kind_str(b),
            original_graph_privacy=orig_privacy,
            resolved_graph_privacy=res_privacy,
            original_binding_privacy=b.privacy,
            resolved_binding_privacy=b.privacy,
            original_evidence_retention=b.evidence_retention,
            resolved_evidence_retention=b.evidence_retention,
        ).validate()
        resolved_map[b.binding_id] = resolved_b
        binding_digests[b.binding_id] = _canonical_sha256(
            _binding_config_fingerprint_payload(b, resolved_b)
        )
        base_reason = _evaluate_resolved_binding_exclusion(resolved_b, by_id[b.binding_id])
        if base_reason is not None:
            policy_excluded_reasons[b.binding_id] = base_reason.value
        else:
            eligible_admitted.append(b.binding_id)
        reason = base_reason
        if reason is None and explicit_selection is not None and b.binding_id not in explicit_selection:
            reason = ExclusionReason.BINDING_NOT_SELECTED
        if reason is not None:
            excluded.append(b.binding_id)
            excluded_reasons[b.binding_id] = reason.value
        else:
            admitted.append(b.binding_id)

    body_policy = BodyProjectionPolicy(
        graph_id=graph.id,
        selected_binding_ids=frozenset(admitted),
        bindings=resolved_map,
        max_projected_files=max_projected_files,
        max_aggregate_input_bytes=max_aggregate_input_bytes,
        max_input_artifact_bytes=max_input_artifact_bytes,
        max_projected_file_bytes=max_projected_file_bytes,
        max_chunk_lines=max_chunk_lines,
        max_chunk_bytes=max_chunk_bytes,
    ).validate()
    canonical_body_policy = BodyProjectionPolicy(
        graph_id=graph.id,
        selected_binding_ids=frozenset(eligible_admitted),
        bindings=resolved_map,
        max_projected_files=max_projected_files,
        max_aggregate_input_bytes=max_aggregate_input_bytes,
        max_input_artifact_bytes=max_input_artifact_bytes,
        max_projected_file_bytes=max_projected_file_bytes,
        max_chunk_lines=max_chunk_lines,
        max_chunk_bytes=max_chunk_bytes,
    ).validate()

    full_policy_payload = {
        "policy_version": LEXICAL_POLICY_VERSION,
        "resolved_graph_privacy": res_privacy,
        "representation_version": LEXICAL_REPRESENTATION_VERSION,
        "text_config_regconfig": LEXICAL_TEXT_CONFIG,
        "ranking_function": LEXICAL_RANKING_FUNCTION,
        "normalization_flags": LEXICAL_NORMALIZATION_FLAGS,
        "alias_split_rule_version": LEXICAL_ALIAS_SPLIT_VERSION,
        "body_projection_policy": canonical_body_policy.to_dict(),
        "binding_policy_digests": dict(sorted(binding_digests.items())),
        "admitted_binding_ids": eligible_admitted,
        "excluded_binding_ids": sorted(policy_excluded_reasons),
        "excluded_binding_reasons": dict(sorted(policy_excluded_reasons.items())),
    }
    policy_digest = _canonical_sha256(full_policy_payload)

    return LexicalGenerationPolicy(
        policy_version=LEXICAL_POLICY_VERSION,
        resolved_graph_privacy=res_privacy,
        body_policy=body_policy,
        binding_policy_digests=binding_digests,
        admitted_binding_ids=tuple(admitted),
        excluded_binding_ids=tuple(excluded),
        excluded_binding_reasons=excluded_reasons,
        policy_digest=policy_digest,
    )


@dataclass(frozen=True)
class PublicationFence:
    """Publication identity tuple pinning a lexical generation to an accepted graph run."""

    run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]

    def validate(self) -> PublicationFence:
        if isinstance(self.run_id, bool) or not isinstance(self.run_id, int) or self.run_id <= 0:
            raise ValueError("PublicationFence.run_id must be a positive integer")
        if not self.publication_bundle_id or not self.snapshot_manifest_id:
            raise ValueError("PublicationFence requires non-empty bundle and manifest IDs")
        if not self.snapshot_vector:
            raise ValueError("PublicationFence requires a non-empty snapshot_vector")
        return self


__all__ = [
    "LEXICAL_ALIAS_SPLIT_VERSION",
    "LEXICAL_NORMALIZATION_FLAGS",
    "LEXICAL_POLICY_VERSION",
    "LEXICAL_RANKING_FUNCTION",
    "LEXICAL_REPRESENTATION_VERSION",
    "LEXICAL_TEXT_CONFIG",
    "LexicalGenerationPolicy",
    "PRODUCTION_MAX_AGGREGATE_INPUT_BYTES",
    "PRODUCTION_MAX_CHUNK_BYTES",
    "PRODUCTION_MAX_CHUNK_LINES",
    "PRODUCTION_MAX_INPUT_ARTIFACT_BYTES",
    "PRODUCTION_MAX_PROJECTED_FILES",
    "PRODUCTION_MAX_PROJECTED_FILE_BYTES",
    "PublicationFence",
    "build_lexical_generation_policy",
    "resolve_graph_privacy_for_lexical",
]
