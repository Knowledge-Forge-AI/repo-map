"""Validation-boundary tests for projection policy and literal query contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.artifacts.manifest import ManifestBinding
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ExclusionReason,
    ResolvedBindingPolicy,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.w5_publication_validation_fixtures import (
    build_validation_projection,
)


def _replace_policy_field(
    policy: BodyProjectionPolicy, field: str, value: object
) -> BodyProjectionPolicy:
    """Keep deliberately malformed parametrized values at the runtime boundary."""
    return replace(policy, **cast(Any, {field: value}))


def _replace_binding_field(
    binding: ManifestBinding, field: str, value: object
) -> ManifestBinding:
    """Keep deliberately malformed binding tokens at the runtime boundary."""
    return replace(binding, **cast(Any, {field: value}))


def _replace_resolved_field(
    resolved: ResolvedBindingPolicy, field: str, value: object
) -> ResolvedBindingPolicy:
    """Keep deliberately malformed resolved tokens at the runtime boundary."""
    return replace(resolved, **cast(Any, {field: value}))


@pytest.mark.parametrize(
    "field",
    (
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
    ),
)
def test_resolved_policy_rejects_empty_fields(tmp_path: Path, field: str) -> None:
    """Every resolved policy identity/authorization field requires text."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    resolved = next(iter(policy.bindings.values()))
    with pytest.raises(ValueError, match=field):
        _replace_resolved_field(resolved, field, "").validate()


def test_resolved_policy_rejects_non_text_field(tmp_path: Path) -> None:
    """Resolved policy type checks reject non-text values before authorization."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    resolved = next(iter(policy.bindings.values()))
    with pytest.raises(ValueError, match="alias"):
        # Deliberately malformed runtime input remains part of this boundary test.
        replace(resolved, alias=cast(Any, 1)).validate()


def test_resolved_policy_mapping_rejects_extra_and_wrong_fields(tmp_path: Path) -> None:
    """Resolved policy mappings remain closed and type checked."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    resolved = next(iter(policy.bindings.values()))
    raw = resolved.to_dict()
    with pytest.raises(ValueError, match="unexpected fields"):
        ResolvedBindingPolicy.from_mapping({**raw, "unexpected": True})
    with pytest.raises(ValueError, match="alias"):
        ResolvedBindingPolicy.from_mapping({**raw, "alias": 1})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("policy_version", "other-version"),
        ("graph_id", ""),
        ("selected_binding_ids", frozenset({1})),
        ("max_chunk_lines", False),
        ("max_chunk_bytes", 0),
        ("max_projected_file_bytes", "large"),
        ("max_input_artifact_bytes", 0),
        ("max_aggregate_input_bytes", 0),
        ("max_projected_files", False),
    ),
)
def test_body_policy_rejects_invalid_version_fields_and_limits(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Policy version, identity, selection, and every positive limit are validated."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    with pytest.raises(ValueError):
        _replace_policy_field(policy, field, value).validate()


def test_body_policy_rejects_aggregate_below_artifact_limit(tmp_path: Path) -> None:
    """Aggregate input capacity cannot be smaller than one artifact capacity."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    with pytest.raises(ValueError, match="aggregate_input_bytes"):
        replace(policy, max_aggregate_input_bytes=1).validate()


def test_body_policy_rejects_binding_key_mismatch(tmp_path: Path) -> None:
    """Policy mapping keys must preserve the binding identity they contain."""
    _inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    resolved = next(iter(policy.bindings.values()))
    with pytest.raises(ValueError, match="binding key"):
        replace(policy, bindings={"bind1:wrong": resolved}).validate()


@pytest.mark.parametrize(
    ("field", "token", "reason"),
    (
        ("role", "email", ExclusionReason.EMAIL_BODY_FORBIDDEN),
        ("alias", "mailbox", ExclusionReason.EMAIL_BODY_FORBIDDEN),
        ("role", "feed", ExclusionReason.FEED_BODY_FORBIDDEN),
        ("alias", "rss", ExclusionReason.FEED_BODY_FORBIDDEN),
    ),
)
def test_binding_role_and_alias_tokens_refuse_body_projection(
    tmp_path: Path,
    field: str,
    token: str,
    reason: ExclusionReason,
) -> None:
    """Role/alias policy tokens are refused independently of suffix heuristics."""
    inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    binding = inputs.manifest.bindings[0]
    resolved = policy.bindings[binding.binding_id]
    changed_binding = _replace_binding_field(binding, field, token)
    changed_resolved = _replace_resolved_field(resolved, field, token)
    changed_bindings = dict(policy.bindings)
    changed_bindings[binding.binding_id] = changed_resolved
    changed_policy = replace(policy, bindings=changed_bindings)
    assert evaluate_binding_exclusion(changed_policy, changed_binding) == reason


@pytest.mark.parametrize(
    ("path", "reason"),
    (
        ("docs/email/archive.txt", ExclusionReason.EMAIL_BODY_FORBIDDEN),
        ("mailbox/archive.txt", ExclusionReason.EMAIL_BODY_FORBIDDEN),
        ("docs/feeds/archive.txt", ExclusionReason.FEED_BODY_FORBIDDEN),
        ("rss/archive.txt", ExclusionReason.FEED_BODY_FORBIDDEN),
    ),
)
def test_parent_directories_refuse_body_projection_before_open(
    tmp_path: Path,
    path: str,
    reason: ExclusionReason,
) -> None:
    """Email/feed parent directories are recognized with ordinary text suffixes."""
    inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    binding = inputs.manifest.bindings[0]
    artifact = replace(inputs.manifest.entries[0], source_relative_path=path)
    assert evaluate_artifact_pre_open(policy, binding, artifact) == (reason, None)


@pytest.mark.parametrize(
    "query_request",
    (
        CapturedTextQueryRequest(query=""),
        CapturedTextQueryRequest(query="bad\x00query"),
        CapturedTextQueryRequest(query="x", limit=True),
        CapturedTextQueryRequest(query="x", limit=0),
        CapturedTextQueryRequest(query="x", limit=501),
        CapturedTextQueryRequest(query="x", offset=True),
        CapturedTextQueryRequest(query="x", offset=-1),
        CapturedTextQueryRequest(query="x", offset=10001),
    ),
)
def test_query_request_rejects_empty_nul_and_boundaries(
    query_request: CapturedTextQueryRequest,
) -> None:
    """Literal query request bounds reject empty/NUL and bool/range confusion."""
    with pytest.raises(ValueError):
        query_request.validate()


def test_query_reports_authorized_binding_file_omissions_without_leakage(
    tmp_path: Path,
) -> None:
    """File-level pre-open omissions remain partial when the binding is authorized."""
    inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(
        inputs,
        replace(policy, max_input_artifact_bytes=1),
    )
    core_id = inputs.manifest.bindings[0].binding_id
    envelope = query_captured_text(
        projection,
        CapturedTextQueryRequest(
            query="BOUNDARY_START_TOKEN",
            selected_binding_ids=(core_id,),
        ),
        current_accepted_reference=inputs.accepted_reference,
    )
    assert envelope.capability_state == CapabilityState.PARTIAL
    assert envelope.scope_complete is False
    assert any(
        omission.reason_code == ExclusionReason.ARTIFACT_OVERSIZED.value
        and omission.source_relative_path == "pkg/alpha.py"
        for omission in envelope.omissions
    )
