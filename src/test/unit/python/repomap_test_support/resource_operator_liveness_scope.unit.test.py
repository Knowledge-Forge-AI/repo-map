"""TEST-HYGIENE3B3-FIX3 L1-L13 exact-valid liveness authority."""

from __future__ import annotations

import stat

from repomap_test_support.resource_lifecycle_claim import ProcessLiveness
from repomap_test_support.resource_operator_scope import ScopeEntry, classify_liveness
from repomap_test_support.resource_safe_tree_delete import RunEntryInspection


INSPECTION = RunEntryInspection(1, 2, stat.S_IFDIR | 0o700, 0, 1)


def entry(
    category: str,
    *,
    state: str = "running",
    pid: object = 123,
    manifest: bool = True,
) -> ScopeEntry:
    payload = {"state": state, "pid": pid} if manifest else None
    return ScopeEntry("opaque-token", INSPECTION, category, payload)


def result(value: ScopeEntry, state: ProcessLiveness) -> tuple[int, int]:
    return classify_liveness((value,), lambda _pid: state)


def test_l1_valid_running_live_pid_contributes_live() -> None:
    assert result(entry("valid"), ProcessLiveness.LIVE) == (1, 0)


def test_l2_valid_running_dead_pid_contributes_neither() -> None:
    assert result(entry("valid"), ProcessLiveness.DEAD) == (0, 0)


def test_l3_valid_running_unknown_probe_contributes_unknown() -> None:
    assert result(entry("valid"), ProcessLiveness.UNKNOWN) == (0, 1)


def test_l4_valid_running_missing_pid_contributes_unknown() -> None:
    assert result(entry("valid", pid=None), ProcessLiveness.LIVE) == (0, 1)


def test_l5_valid_running_nonpositive_pid_contributes_unknown() -> None:
    assert result(entry("valid", pid=0), ProcessLiveness.LIVE) == (0, 1)


def test_l6_foreign_running_missing_pid_has_no_liveness_authority() -> None:
    assert result(entry("foreign", pid=None), ProcessLiveness.LIVE) == (0, 0)


def test_l7_foreign_running_live_pid_has_no_liveness_authority() -> None:
    assert result(entry("foreign"), ProcessLiveness.LIVE) == (0, 0)


def test_l8_foreign_running_unknown_probe_has_no_liveness_authority() -> None:
    assert result(entry("foreign"), ProcessLiveness.UNKNOWN) == (0, 0)


def test_l9_ambiguous_running_missing_pid_has_no_liveness_authority() -> None:
    assert result(entry("ambiguous", pid=None), ProcessLiveness.LIVE) == (0, 0)


def test_l10_ambiguous_running_live_pid_has_no_liveness_authority() -> None:
    assert result(entry("ambiguous"), ProcessLiveness.LIVE) == (0, 0)


def test_l11_opaque_entry_cannot_contribute_liveness() -> None:
    assert result(
        entry("opaque", manifest=False), ProcessLiveness.LIVE
    ) == (0, 0)


def test_l12_mixed_population_counts_only_valid_live() -> None:
    values = (
        entry("valid"),
        entry("foreign", pid=None),
        entry("ambiguous", pid=None),
        entry("opaque", manifest=False),
    )
    assert classify_liveness(values, lambda _pid: ProcessLiveness.LIVE) == (1, 0)


def test_l13_current_shape_excludes_foreign_missing_pid() -> None:
    values = tuple(entry("valid") for _ in range(31)) + tuple(
        entry("foreign", pid=None) for _ in range(95)
    )
    assert classify_liveness(values, lambda _pid: ProcessLiveness.DEAD) == (0, 0)
