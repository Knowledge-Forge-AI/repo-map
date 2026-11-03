"""Fixtures for publication correspondence and privacy regression tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceErrorCode,
    CorrespondenceRefusal,
    ProjectionInputs,
    check_correspondence,
)
from repomap_test_support.retrieval_evaluation_query_fixture import (
    build_fixture_projection,
)


def make_fixture_projection(
    *,
    spool_dir: Path,
) -> tuple[ProjectionInputs, BodyProjectionPolicy]:
    """Reuse the maintained query fixture rather than rebuilding publication records."""
    return build_fixture_projection(spool_dir=spool_dir)


def publication_tree(path: Path) -> tuple[tuple[str, int, str], ...]:
    """Capture exact run-owned file names, lengths, and bytes for cleanup assertions."""
    if not path.exists():
        return ()
    result: list[tuple[str, int, str]] = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            raw = item.read_bytes()
            result.append(
                (
                    item.relative_to(path).as_posix(),
                    len(raw),
                    hashlib.sha256(raw).hexdigest(),
                )
            )
    return tuple(result)


def policy_with_resolution(
    policy: BodyProjectionPolicy,
    binding_id: str,
    *,
    resolved_binding_privacy: str | None = None,
    resolved_evidence_retention: str | None = None,
    resolved_graph_privacy: str | None = None,
) -> BodyProjectionPolicy:
    """Return a validated policy with one explicit resolved privacy/retention change."""
    resolved = policy.bindings[binding_id]
    bindings = dict(policy.bindings)
    bindings[binding_id] = replace(
        resolved,
        resolved_binding_privacy=(
            resolved_binding_privacy
            if resolved_binding_privacy is not None
            else resolved.resolved_binding_privacy
        ),
        resolved_evidence_retention=(
            resolved_evidence_retention
            if resolved_evidence_retention is not None
            else resolved.resolved_evidence_retention
        ),
        resolved_graph_privacy=(
            resolved_graph_privacy
            if resolved_graph_privacy is not None
            else resolved.resolved_graph_privacy
        ),
    )
    return replace(policy, bindings=bindings).validate()


def assert_correspondence_mismatch_matrix(inputs: ProjectionInputs) -> None:
    """Exercise every existing check_correspondence identity refusal branch."""
    portable = inputs.receipt.portable
    assert portable is not None
    cases = (
        (
            replace(inputs.accepted_reference, graph_id="other-graph"),
            CorrespondenceErrorCode.GRAPH_ID_MISMATCH,
        ),
        (
            replace(inputs.accepted_reference, attempt=2),
            CorrespondenceErrorCode.ATTEMPT_MISMATCH,
        ),
        (
            replace(
                inputs.accepted_reference,
                publication_bundle_id="bundle1:" + "f" * 64,
            ),
            CorrespondenceErrorCode.BUNDLE_ID_MISMATCH,
        ),
        (
            replace(
                inputs.receipt,
                portable=replace(portable, candidate_id="cand1:" + "e" * 64),
            ),
            CorrespondenceErrorCode.CANDIDATE_ID_MISMATCH,
        ),
        (
            replace(
                inputs.accepted_reference,
                snapshot_manifest_id="snapmanifest1:" + "9" * 64,
            ),
            CorrespondenceErrorCode.MANIFEST_ID_MISMATCH,
        ),
        (
            replace(
                inputs.receipt,
                portable=replace(
                    portable,
                    snapshot_vector=(
                        ("bind1:" + "8" * 64, 1, "snap1:" + "2" * 64),
                    ),
                ),
            ),
            CorrespondenceErrorCode.SNAPSHOT_VECTOR_MISMATCH,
        ),
        (
            replace(
                inputs.receipt,
                generations=replace(
                    inputs.receipt.generations,
                    source_generation="sg1:" + "9" * 64,
                ),
            ),
            CorrespondenceErrorCode.GENERATION_MISMATCH,
        ),
        (
            replace(
                inputs.accepted_reference,
                extraction_receipt_id="receipt1:" + "0" * 64,
            ),
            CorrespondenceErrorCode.RECEIPT_ID_MISMATCH,
        ),
    )
    for mutated, expected in cases:
        candidate = (
            replace(inputs, accepted_reference=mutated)
            if isinstance(mutated, AcceptedPublicationReference)
            else replace(inputs, receipt=mutated)
        )
        try:
            check_correspondence(candidate)
        except CorrespondenceRefusal as error:
            if error.code != expected:
                raise AssertionError((expected, error.code)) from error
        else:
            raise AssertionError(f"expected correspondence refusal {expected}")


__all__ = [
    "assert_correspondence_mismatch_matrix",
    "make_fixture_projection",
    "policy_with_resolution",
    "publication_tree",
]
