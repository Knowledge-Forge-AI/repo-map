"""Parity and seam tests for the bounded worker-term extraction."""

from __future__ import annotations

from types import SimpleNamespace

from common_lore_index.coordinator.limits import CoordinatorLimits, DEFAULT_LIMITS
from common_lore_index.ops import _portable_worker_terms as terms
from common_lore_index.ops import portable_refresh


def test_explicit_limits_are_returned_unchanged() -> None:
    explicit = object()
    assert terms.effective_leaf_limits(explicit, None) is explicit


def test_authority_deadline_replaces_only_default_leaf_deadline() -> None:
    authority = SimpleNamespace(process_deadline_seconds=17)
    derived = terms.effective_leaf_limits(None, authority)
    assert isinstance(derived, CoordinatorLimits)
    assert derived is not DEFAULT_LIMITS
    assert derived.process_deadline_seconds == 17
    assert derived.cancel_deadline_seconds == DEFAULT_LIMITS.cancel_deadline_seconds


def test_no_authority_keeps_default_limits_object() -> None:
    assert terms.effective_leaf_limits(None, None) is DEFAULT_LIMITS


def test_named_artifact_cap_and_rebound_patch_seams_are_stable() -> None:
    assert terms.PORTABLE_MAX_ARTIFACT_BYTES == 4 * 1024 * 1024 * 1024
    assert portable_refresh.PORTABLE_MAX_ARTIFACT_BYTES is terms.PORTABLE_MAX_ARTIFACT_BYTES
    assert portable_refresh.effective_leaf_limits is terms.effective_leaf_limits
    assert portable_refresh._worker_references is terms._worker_references
