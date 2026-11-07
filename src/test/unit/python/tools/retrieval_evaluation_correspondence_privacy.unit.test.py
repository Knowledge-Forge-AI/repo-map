"""Unit matrix for publication binding and privacy refusal edges."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import (
    ExclusionReason,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.publication_binding import CorrespondenceRefusal
from common_lore_index.retrieval.query_contracts import CapabilityState
from common_lore_index.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.w5_publication_privacy_fixtures import (
    assert_correspondence_mismatch_matrix,
    make_fixture_projection,
    policy_with_resolution,
    publication_tree,
)


def test_identity_matrix_refuses_mismatches_before_projection(tmp_path: Path) -> None:
    """Every accepted/receipt identity axis has a closed refusal code."""
    inputs, _public_policy = make_fixture_projection(spool_dir=tmp_path / "spool")
    assert_correspondence_mismatch_matrix(inputs)

    foreign_repository = replace(
        inputs.accepted_reference,
        repository_id="repo1:foreign",
    )
    assert inputs.accepted_reference.matches_current(foreign_repository) is False
    assert inputs.accepted_reference.matches_current(inputs.accepted_reference)


def test_private_binding_is_refused_before_artifact_open_and_cleans_spool(
    tmp_path: Path,
) -> None:
    """Binding privacy is decided before source bytes are opened and leaves no spool residue."""
    inputs, public_policy = make_fixture_projection(spool_dir=tmp_path / "spool")
    binding = inputs.manifest.bindings[0]
    private_policy = policy_with_resolution(
        public_policy,
        binding.binding_id,
        resolved_binding_privacy="private-memory",
    )
    spool_dir = inputs.spool_dir
    assert spool_dir is not None
    before = publication_tree(spool_dir)
    projection = build_captured_text_projection(inputs, private_policy)
    assert evaluate_binding_exclusion(private_policy, binding) == (
        ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED
    )
    assert projection.projected_files == ()
    assert projection.excluded_bindings[0].reason == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED
    assert all(not item.store_opened for item in projection.excluded_files)
    assert publication_tree(spool_dir) == before


@pytest.mark.parametrize(
    ("path", "privacy", "expected"),
    (
        ("mailbox/thread.eml", PrivacyClassification.RAW_SOURCE, ExclusionReason.EMAIL_BODY_FORBIDDEN),
        ("feeds/releases.rss", PrivacyClassification.RAW_SOURCE, ExclusionReason.FEED_BODY_FORBIDDEN),
        ("assets/logo.png", PrivacyClassification.RAW_SOURCE, ExclusionReason.UNSUPPORTED_SOURCE_FORMAT),
        ("pkg/private.py", PrivacyClassification.CANONICAL_PROVENANCE, ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN),
    ),
)
def test_artifact_policy_refuses_sensitive_or_unsupported_paths_before_open(
    tmp_path: Path,
    path: str,
    privacy: PrivacyClassification,
    expected: ExclusionReason,
) -> None:
    """Per-artifact privacy and format gates are evaluated without store access."""
    inputs, policy = make_fixture_projection(spool_dir=tmp_path / "spool")
    binding = inputs.manifest.bindings[0]
    source = inputs.manifest.entries[0]
    artifact = replace(
        source,
        source_relative_path=path,
        reference=replace(source.reference, privacy=privacy),
    )
    reason, source_format = evaluate_artifact_pre_open(policy, binding, artifact)
    assert reason == expected
    assert source_format is None


def test_current_public_projection_queries_and_rejects_foreign_current_marker(
    tmp_path: Path,
) -> None:
    """A valid projection answers only while its accepted repository marker remains current."""
    inputs, public_policy = make_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, public_policy)
    request = CapturedTextQueryRequest(query="BOUNDARY_START_TOKEN")
    available = query_captured_text(
        projection,
        request,
        current_accepted_reference=inputs.accepted_reference,
    )
    assert available.capability_state == CapabilityState.AVAILABLE
    assert available.hits

    foreign = replace(inputs.accepted_reference, repository_id="repo1:foreign")
    stale = query_captured_text(
        projection,
        request,
        current_accepted_reference=foreign,
    )
    assert stale.capability_state == CapabilityState.STALE
    assert stale.hits == ()


def test_untrusted_reference_is_not_a_projection_input(tmp_path: Path) -> None:
    """Caller-provided accepted markers cannot bypass the trusted-readback fence."""
    inputs, public_policy = make_fixture_projection(spool_dir=tmp_path / "spool")
    untrusted = replace(inputs.accepted_reference, trusted_caller=False)
    with pytest.raises(CorrespondenceRefusal) as failure:
        build_captured_text_projection(
            replace(inputs, accepted_reference=untrusted),
            public_policy,
        )
    assert "untrusted_caller_reference" in str(failure.value)
