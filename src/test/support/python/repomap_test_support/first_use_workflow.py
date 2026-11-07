"""Test-owned contracts and guards for the mixed-v1 first-use workflows.

The integration owners deliberately keep workflow setup in the existing
fixture and harness helpers.  This module contains only the policy-derived
expectations they share and a deletion guard for helpers that rebuild a
working-copy target in place.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS,
    MIXED_V1_FIXTURE_ROOT,
    binding_id_for_alias,
    build_mixed_v1_projection_policy,
)


@dataclass(frozen=True, slots=True)
class FirstUseBindingExpectation:
    """Policy-derived treatment of one declared mixed-v1 binding."""

    alias: str
    privacy: str
    retention: str
    body_treatment: str
    lexical_treatment: str


def first_use_expectations(
    declared_aliases: Sequence[str],
) -> tuple[FirstUseBindingExpectation, ...]:
    """Return deterministic first-use expectations for declared aliases.

    The projection policy remains the source of truth for privacy and
    retention.  Empty declarations are preserved as an empty tuple so that a
    workflow owner can bind the resulting behavior to the current owner's
    refusal instead of inventing a helper-level outcome.
    """
    raw_aliases = tuple(declared_aliases)
    if any(not isinstance(alias, str) or not alias for alias in raw_aliases):
        raise ValueError("first-use-aliases-invalid")
    aliases = tuple(dict.fromkeys(raw_aliases))
    unknown = set(aliases).difference(MIXED_V1_BINDINGS)
    if unknown:
        raise ValueError("first-use-alias-unknown")

    policy = build_mixed_v1_projection_policy(selected_aliases=aliases)
    expected: list[FirstUseBindingExpectation] = []
    for alias in MIXED_V1_BINDINGS:
        if alias not in aliases:
            continue
        binding = policy.bindings[binding_id_for_alias(alias)]
        retention = binding.resolved_evidence_retention
        privacy = binding.resolved_binding_privacy
        full_authorized = retention == "full-authorized" and privacy == "public-dev"
        expected.append(
            FirstUseBindingExpectation(
                alias=alias,
                privacy=privacy,
                retention=retention,
                body_treatment=("full-authorized" if full_authorized else "metadata-only"),
                lexical_treatment=("eligible" if full_authorized else "refused"),
            )
        )
    return tuple(expected)


def guard_first_use_root(
    target_root: Path,
    temporary_root: Path,
    *,
    fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
) -> Path:
    """Validate a disposable home/working-copy target before rebuilding it.

    ``materialize_mixed_v1_working_copy`` removes its target first.  The
    returned path is resolved for callers to pass to that helper.  Fixture
    overlap and lexical symlinks are refused before a caller can remove a
    target through an alias; errors intentionally omit filesystem details.
    """
    target = Path(target_root).resolve(strict=False)
    temporary = Path(temporary_root).resolve(strict=False)
    fixture = Path(fixture_root).resolve(strict=False)
    if target == temporary or not target.is_relative_to(temporary):
        raise ValueError("first-use-root-outside-temporary-root")
    if (
        target.is_relative_to(fixture)
        or fixture.is_relative_to(target)
    ):
        raise ValueError("first-use-root-is-fixture")
    if _has_symlink_component(target_root):
        raise ValueError("first-use-root-outside-temporary-root")
    return target


def _has_symlink_component(path: Path) -> bool:
    """Return whether the lexical target path contains an existing symlink."""
    lexical = Path(path)
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        if part in {"", "."}:
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


__all__ = [
    "FirstUseBindingExpectation",
    "first_use_expectations",
    "guard_first_use_root",
]
