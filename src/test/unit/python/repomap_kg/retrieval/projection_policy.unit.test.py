"""Unit tests for body projection privacy, retention, and format policy (S1)."""

from __future__ import annotations

from typing import Any, cast

from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.artifacts.references import ArtifactLocator, ArtifactReference
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ExclusionReason,
    ResolvedBindingPolicy,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


def _binding(
    binding_id: str = "bind1:core",
    *,
    privacy: str = "public-dev",
    retention: str = "full-authorized",
    role: str = "source",
    source_kind: str = "local-directory",
    alias: str = "core",
) -> ManifestBinding:
    return ManifestBinding(
        binding_id=binding_id,
        revision=1,
        snapshot_id="snap1:" + "1" * 64,
        source_definition_id=f"src1:{alias}",
        source_kind=source_kind,
        acquisition_method="sealed-local-copy",
        selection_policy_id="select1:default",
        ignore_policy_id="ignore1:default",
        privacy_policy=privacy,
        role=role,
        input_name=alias,
        alias=alias,
        logical_root=alias,
        evidence_retention_policy=retention,
        extractor_profile="default",
        resolution_policy="isolated",
        repository_scope=alias,
    )


def _artifact(
    binding_id: str = "bind1:core",
    path: str = "pkg/pipeline.py",
    *,
    size_bytes: int = 128,
    privacy: PrivacyClassification = PrivacyClassification.RAW_SOURCE,
) -> ManifestArtifact:
    return ManifestArtifact(
        binding_id=binding_id,
        source_relative_path=path,
        reference=ArtifactReference(
            content_digest="sha256:" + "a" * 64,
            size_bytes=size_bytes,
            media_type="text/plain",
            record_format="raw-source-v1",
            privacy=privacy,
            locator=ArtifactLocator("filesystem", "objects/" + "a" * 64),
        ),
        executable=False,
    )


def _policy_for(
    resolved: ResolvedBindingPolicy,
    *,
    selected: tuple[str, ...] = ("bind1:core",),
    max_input_artifact_bytes: int = 1048576,
) -> BodyProjectionPolicy:
    return BodyProjectionPolicy(
        graph_id="mixed-v1",
        selected_binding_ids=frozenset(selected),
        bindings={resolved.binding_id: resolved},
        max_input_artifact_bytes=max_input_artifact_bytes,
    ).validate()


def test_public_dev_full_authorized_selected_binding_is_admitted() -> None:
    """Explicitly resolved public-dev + full-authorized binding in selected scope is admitted."""
    resolved = ResolvedBindingPolicy(
        binding_id="bind1:core",
        alias="core",
        role="source",
        source_kind="folder",
        original_graph_privacy="public-dev",
        resolved_graph_privacy="public-dev",
        original_binding_privacy="public-dev",
        resolved_binding_privacy="public-dev",
        original_evidence_retention="full-authorized",
        resolved_evidence_retention="full-authorized",
    ).validate()
    policy = _policy_for(resolved)
    b = _binding()
    assert evaluate_binding_exclusion(policy, b) is None
    reason, fmt = evaluate_artifact_pre_open(policy, b, _artifact(path="pkg/pipeline.py"))
    assert reason is None
    assert fmt == "python"


def test_unresolved_inherit_and_private_policies_refused_before_open() -> None:
    """Unresolved inherit, private graph/binding policies, and metadata-only retention are refused."""
    b = _binding()
    inherit_policy = _policy_for(
        ResolvedBindingPolicy(
            binding_id="bind1:core",
            alias="core",
            role="source",
            source_kind="folder",
            original_graph_privacy="public-dev",
            resolved_graph_privacy="public-dev",
            original_binding_privacy="inherit",
            resolved_binding_privacy="inherit",
            original_evidence_retention="full-authorized",
            resolved_evidence_retention="full-authorized",
        )
    )
    assert evaluate_binding_exclusion(inherit_policy, b) == ExclusionReason.UNRESOLVED_INHERIT_POLICY

    private_graph_policy = _policy_for(
        ResolvedBindingPolicy(
            binding_id="bind1:core",
            alias="core",
            role="source",
            source_kind="folder",
            original_graph_privacy="private-ops",
            resolved_graph_privacy="private-ops",
            original_binding_privacy="public-dev",
            resolved_binding_privacy="public-dev",
            original_evidence_retention="full-authorized",
            resolved_evidence_retention="full-authorized",
        )
    )
    assert evaluate_binding_exclusion(private_graph_policy, b) == ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED

    for private_label in ("private-ops", "private-memory", "private-config", "sensitive-local"):
        private_binding_policy = _policy_for(
            ResolvedBindingPolicy(
                binding_id="bind1:core",
                alias="core",
                role="source",
                source_kind="folder",
                original_graph_privacy="public-dev",
                resolved_graph_privacy="public-dev",
                original_binding_privacy=private_label,
                resolved_binding_privacy=private_label,
                original_evidence_retention="full-authorized",
                resolved_evidence_retention="full-authorized",
            )
        )
        assert (
            evaluate_binding_exclusion(private_binding_policy, b)
            == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED
        )

    for retention_label in ("metadata-only", "ephemeral"):
        ret_policy = _policy_for(
            ResolvedBindingPolicy(
                binding_id="bind1:core",
                alias="core",
                role="source",
                source_kind="folder",
                original_graph_privacy="public-dev",
                resolved_graph_privacy="public-dev",
                original_binding_privacy="public-dev",
                resolved_binding_privacy="public-dev",
                original_evidence_retention=retention_label,
                resolved_evidence_retention=retention_label,
            )
        )
        assert evaluate_binding_exclusion(ret_policy, b) == ExclusionReason.RETENTION_NOT_AUTHORIZED


def test_unselected_email_feed_unsupported_and_oversized_refused_pre_open() -> None:
    """Unselected bindings, email, feeds, unsupported extensions, and >1 MiB artifacts are refused."""
    resolved = ResolvedBindingPolicy(
        binding_id="bind1:core",
        alias="core",
        role="source",
        source_kind="folder",
        original_graph_privacy="public-dev",
        resolved_graph_privacy="public-dev",
        original_binding_privacy="public-dev",
        resolved_binding_privacy="public-dev",
        original_evidence_retention="full-authorized",
        resolved_evidence_retention="full-authorized",
    )
    unselected = _policy_for(resolved, selected=("bind1:other",))
    b = _binding()
    assert evaluate_binding_exclusion(unselected, b) == ExclusionReason.BINDING_NOT_SELECTED

    policy = _policy_for(resolved)
    for email_path in ("mailbox/thread.eml", "mailbox/archive.mbox", "mailbox/note.msg"):
        reason, fmt = evaluate_artifact_pre_open(policy, b, _artifact(path=email_path))
        assert reason == ExclusionReason.EMAIL_BODY_FORBIDDEN and fmt is None

    for feed_path in ("feeds/releases.rss", "feeds/news.atom", "feeds/subs.opml", "feeds/data.xml", "feeds/items.json"):
        reason, fmt = evaluate_artifact_pre_open(policy, b, _artifact(path=feed_path))
        assert reason == ExclusionReason.FEED_BODY_FORBIDDEN and fmt is None

    for non_body_path in ("assets/logo.png", "config/data.xml", "config/items.json", "docs/page.html"):
        reason, fmt = evaluate_artifact_pre_open(policy, b, _artifact(path=non_body_path))
        assert reason == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT and fmt is None

    # Verify BodyProjectionPolicy freezes caller-supplied mappings and sets
    mutable_bindings = {resolved.binding_id: resolved}
    mutable_selected = {"bind1:core"}
    frozen_pol = BodyProjectionPolicy(
        graph_id="mixed-v1",
        selected_binding_ids=cast(Any, mutable_selected),
        bindings=mutable_bindings,
    ).validate()
    digest_before = frozen_pol.policy_digest()
    mutable_bindings.clear()
    mutable_selected.clear()
    assert frozen_pol.policy_digest() == digest_before

    reason, fmt = evaluate_artifact_pre_open(
        policy,
        b,
        _artifact(path="pkg/pipeline.py", privacy=PrivacyClassification.CANONICAL_PROVENANCE),
    )
    assert reason == ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN and fmt is None

    reason, fmt = evaluate_artifact_pre_open(
        policy,
        b,
        _artifact(path="pkg/huge.py", size_bytes=1048577),
    )
    assert reason == ExclusionReason.ARTIFACT_OVERSIZED and fmt is None
