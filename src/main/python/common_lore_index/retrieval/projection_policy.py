"""Privacy, retention, and format authorization policy for body projection (S1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.retrieval.projection_chunks import frame_digest
from common_lore_index.retrieval.publication_binding import PROJECTION_REFERENCE_VERSION
from common_lore_index.storage.staging_family_contracts import PrivacyClassification

ALLOWED_GRAPH_PRIVACY = "public-dev"
ALLOWED_BINDING_PRIVACY = "public-dev"
ALLOWED_EVIDENCE_RETENTION = "full-authorized"

EMAIL_EXTENSIONS = frozenset({".eml", ".mbox", ".msg"})
FEED_EXTENSIONS = frozenset({".rss", ".atom", ".opml"})

SUPPORTED_TEXT_FORMATS: Mapping[str, str] = MappingProxyType({
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".nix": "nix",
    ".md": "markdown",
    ".txt": "text",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".go": "go",
    ".ts": "typescript",
    ".js": "javascript",
    ".css": "css",
})


class ExclusionReason(str, Enum):
    """Deterministic pre-open and post-open exclusion reasons for body projection."""

    UNRESOLVED_INHERIT_POLICY = "unresolved_inherit_policy"
    GRAPH_PRIVACY_NOT_AUTHORIZED = "graph_privacy_not_authorized"
    BINDING_PRIVACY_NOT_AUTHORIZED = "binding_privacy_not_authorized"
    RETENTION_NOT_AUTHORIZED = "retention_not_authorized"
    BINDING_NOT_SELECTED = "binding_not_selected"
    EMAIL_BODY_FORBIDDEN = "email_body_forbidden"
    FEED_BODY_FORBIDDEN = "feed_body_forbidden"
    UNSUPPORTED_SOURCE_FORMAT = "unsupported_source_format"
    ARTIFACT_PRIVACY_FORBIDDEN = "artifact_privacy_forbidden"
    ARTIFACT_OVERSIZED = "artifact_oversized"
    AGGREGATE_BUDGET_EXCEEDED = "aggregate_budget_exceeded"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_CORRUPT = "artifact_corrupt"
    INVALID_UTF8 = "invalid_utf8"
    NUL_BYTE_REJECTED = "nul_byte_rejected"


@dataclass(frozen=True)
class ResolvedBindingPolicy:
    """Original and resolved graph/binding privacy and retention policy labels."""

    binding_id: str
    alias: str
    role: str
    source_kind: str
    original_graph_privacy: str
    resolved_graph_privacy: str
    original_binding_privacy: str
    resolved_binding_privacy: str
    original_evidence_retention: str
    resolved_evidence_retention: str

    def validate(self) -> ResolvedBindingPolicy:
        for name, val in (
            ("binding_id", self.binding_id),
            ("alias", self.alias),
            ("role", self.role),
            ("source_kind", self.source_kind),
            ("original_graph_privacy", self.original_graph_privacy),
            ("resolved_graph_privacy", self.resolved_graph_privacy),
            ("original_binding_privacy", self.original_binding_privacy),
            ("resolved_binding_privacy", self.resolved_binding_privacy),
            ("original_evidence_retention", self.original_evidence_retention),
            ("resolved_evidence_retention", self.resolved_evidence_retention),
        ):
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{name} must be a non-empty string")
        return self

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "binding_id": self.binding_id,
            "alias": self.alias,
            "role": self.role,
            "source_kind": self.source_kind,
            "original_graph_privacy": self.original_graph_privacy,
            "resolved_graph_privacy": self.resolved_graph_privacy,
            "original_binding_privacy": self.original_binding_privacy,
            "resolved_binding_privacy": self.resolved_binding_privacy,
            "original_evidence_retention": self.original_evidence_retention,
            "resolved_evidence_retention": self.resolved_evidence_retention,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ResolvedBindingPolicy:
        req = (
            "binding_id",
            "alias",
            "role",
            "source_kind",
            "original_graph_privacy",
            "resolved_graph_privacy",
            "original_binding_privacy",
            "resolved_binding_privacy",
            "original_evidence_retention",
            "resolved_evidence_retention",
        )
        extra = set(raw.keys()) - set(req)
        if extra:
            raise ValueError(f"ResolvedBindingPolicy has unexpected fields: {sorted(extra)}")
        for k in req:
            if not isinstance(raw.get(k), str):
                raise ValueError(f"{k} must be a string")
        return cls(**{k: raw[k] for k in req}).validate()


@dataclass(frozen=True)
class BodyProjectionPolicy:
    """Explicit caller-supplied authorization and size policy for W2 body projection."""

    policy_version: str = PROJECTION_REFERENCE_VERSION
    graph_id: str = ""
    selected_binding_ids: frozenset[str] = field(default_factory=frozenset)
    bindings: Mapping[str, ResolvedBindingPolicy] = field(
        default_factory=lambda: MappingProxyType({})
    )
    max_chunk_lines: int = 80
    max_chunk_bytes: int = 8192
    max_projected_file_bytes: int = 262144
    max_input_artifact_bytes: int = 1048576
    max_aggregate_input_bytes: int = 8388608
    max_projected_files: int = 4096

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_binding_ids", frozenset(self.selected_binding_ids))
        object.__setattr__(self, "bindings", MappingProxyType(dict(self.bindings)))

    def validate(self) -> BodyProjectionPolicy:
        if self.policy_version != PROJECTION_REFERENCE_VERSION:
            raise ValueError(f"unsupported policy_version: {self.policy_version!r}")
        if not isinstance(self.graph_id, str) or not self.graph_id.strip():
            raise ValueError("graph_id must be a non-empty string")
        for sid in self.selected_binding_ids:
            if not isinstance(sid, str) or not sid.strip():
                raise ValueError("selected_binding_ids entries must be non-empty strings")
        for key, item in self.bindings.items():
            item.validate()
            if key != item.binding_id:
                raise ValueError(f"binding key {key!r} does not match {item.binding_id!r}")
        for limit_name, limit_val in (
            ("max_chunk_lines", self.max_chunk_lines),
            ("max_chunk_bytes", self.max_chunk_bytes),
            ("max_projected_file_bytes", self.max_projected_file_bytes),
            ("max_input_artifact_bytes", self.max_input_artifact_bytes),
            ("max_aggregate_input_bytes", self.max_aggregate_input_bytes),
            ("max_projected_files", self.max_projected_files),
        ):
            if isinstance(limit_val, bool) or not isinstance(limit_val, int) or limit_val < 1:
                raise ValueError(f"{limit_name} must be a positive integer")
        if self.max_aggregate_input_bytes < self.max_input_artifact_bytes:
            raise ValueError("max_aggregate_input_bytes must be >= max_input_artifact_bytes")
        return self

    def policy_digest(self) -> str:
        self.validate()
        parts: list[str] = [
            self.policy_version,
            self.graph_id,
            str(self.max_chunk_lines),
            str(self.max_chunk_bytes),
            str(self.max_projected_file_bytes),
            str(self.max_input_artifact_bytes),
            str(self.max_aggregate_input_bytes),
            ",".join(sorted(self.selected_binding_ids)),
        ]
        for binding_id in sorted(self.bindings):
            bp = self.bindings[binding_id]
            parts.extend((
                bp.binding_id,
                bp.alias,
                bp.role,
                bp.source_kind,
                bp.original_graph_privacy,
                bp.resolved_graph_privacy,
                bp.original_binding_privacy,
                bp.resolved_binding_privacy,
                bp.original_evidence_retention,
                bp.resolved_evidence_retention,
            ))
        return frame_digest("sha256", parts)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "policy_version": self.policy_version,
            "graph_id": self.graph_id,
            "selected_binding_ids": sorted(self.selected_binding_ids),
            "bindings": {k: v.to_dict() for k, v in sorted(self.bindings.items())},
            "max_chunk_lines": self.max_chunk_lines,
            "max_chunk_bytes": self.max_chunk_bytes,
            "max_projected_file_bytes": self.max_projected_file_bytes,
            "max_input_artifact_bytes": self.max_input_artifact_bytes,
            "max_aggregate_input_bytes": self.max_aggregate_input_bytes,
            "policy_digest": self.policy_digest(),
        }


def _is_email_role_or_path(role: str, source_kind: str, alias: str, rel_path: str | None) -> bool:
    lower_tokens = {role.lower(), source_kind.lower(), alias.lower()}
    if any(tok in {"email", "mailbox", "mail", "imap", "mbox"} for tok in lower_tokens):
        return True
    if rel_path is not None:
        posix = PurePosixPath(rel_path)
        if posix.suffix.lower() in EMAIL_EXTENSIONS:
            return True
        if any(seg.lower() in {"mailbox", "email", "emails"} for seg in posix.parts[:-1]):
            return True
    return False


def _is_feed_role_or_path(role: str, source_kind: str, alias: str, rel_path: str | None) -> bool:
    lower_tokens = {role.lower(), source_kind.lower(), alias.lower()}
    if any(tok in {"feed", "feeds", "rss", "atom"} for tok in lower_tokens):
        return True
    if rel_path is not None:
        posix = PurePosixPath(rel_path)
        if posix.suffix.lower() in FEED_EXTENSIONS:
            return True
        if any(seg.lower() in {"feed", "feeds", "rss", "atom"} for seg in posix.parts[:-1]):
            return True
    return False


def evaluate_binding_exclusion(
    policy: BodyProjectionPolicy,
    binding: ManifestBinding,
) -> ExclusionReason | None:
    """Evaluate binding-level authorization before inspecting any artifact."""
    policy.validate()
    resolved = policy.bindings.get(binding.binding_id)
    if resolved is None:
        return ExclusionReason.UNRESOLVED_INHERIT_POLICY

    if "inherit" in {
        resolved.resolved_graph_privacy,
        resolved.resolved_binding_privacy,
        resolved.resolved_evidence_retention,
        binding.privacy_policy,
        binding.evidence_retention_policy or "",
    }:
        return ExclusionReason.UNRESOLVED_INHERIT_POLICY

    if resolved.resolved_graph_privacy != ALLOWED_GRAPH_PRIVACY:
        return ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED

    if (
        resolved.resolved_binding_privacy != ALLOWED_BINDING_PRIVACY
        or binding.privacy_policy != ALLOWED_BINDING_PRIVACY
    ):
        return ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED

    if resolved.resolved_evidence_retention != ALLOWED_EVIDENCE_RETENTION or (
        binding.evidence_retention_policy not in {None, ALLOWED_EVIDENCE_RETENTION}
    ):
        return ExclusionReason.RETENTION_NOT_AUTHORIZED

    if _is_email_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN

    if _is_feed_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.FEED_BODY_FORBIDDEN

    if binding.binding_id not in policy.selected_binding_ids:
        return ExclusionReason.BINDING_NOT_SELECTED

    return None


def evaluate_artifact_pre_open(
    policy: BodyProjectionPolicy,
    binding: ManifestBinding,
    artifact: ManifestArtifact,
) -> tuple[ExclusionReason | None, str | None]:
    """Evaluate per-artifact authorization and size bounds BEFORE opening the blob."""
    rel_path = artifact.source_relative_path
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix in EMAIL_EXTENSIONS or _is_email_role_or_path(
        binding.role,
        binding.source_kind,
        binding.alias or "",
        rel_path,
    ):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN, None

    if suffix in FEED_EXTENSIONS or _is_feed_role_or_path(
        binding.role,
        binding.source_kind,
        binding.alias or "",
        rel_path,
    ):
        return ExclusionReason.FEED_BODY_FORBIDDEN, None

    binding_reason = evaluate_binding_exclusion(policy, binding)
    if binding_reason is not None:
        return binding_reason, None

    if artifact.reference.privacy not in {
        PrivacyClassification.PUBLIC,
        PrivacyClassification.RAW_SOURCE,
    }:
        return ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN, None

    source_format = SUPPORTED_TEXT_FORMATS.get(suffix)
    if source_format is None:
        return ExclusionReason.UNSUPPORTED_SOURCE_FORMAT, None

    if artifact.reference.size_bytes > policy.max_input_artifact_bytes:
        return ExclusionReason.ARTIFACT_OVERSIZED, None

    return None, source_format
