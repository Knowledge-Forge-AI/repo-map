"""Usage role labels cannot waive strict issued-child receipts.

These are inert reconciliation inputs; no collector or child is started and
no measurement or source coverage is claimed.
"""

from pathlib import Path

import pytest

from runner_coverage_diagnostics import ShardDiagnosticSnapshot, create_shard_snapshot
from runner_coverage_receipts import reconcile_child_manifests


@pytest.mark.parametrize("role", (
    "portable", "usage-self-sigkill", "usage-parent-interrupt", "conformance-abrupt",
))
def test_role_name_never_accepts_an_incomplete_registered_child(tmp_path: Path, role: str) -> None:
    snapshots: list[ShardDiagnosticSnapshot] = []
    with pytest.raises(RuntimeError, match="terminal receipt is incomplete"):
        reconcile_child_manifests(
            {41001: {"cov_start": 1, "exited": False, "strict": True, "role": role}},
            set(), tmp_path, str(tmp_path / "parent"), 41000,
            create_shard_snapshot, snapshots.append,
        )
    assert len(snapshots) == 1
    assert snapshots[0].file_type == "incomplete_terminal"
    assert snapshots[0].launch_role == role
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("role", ("usage-self-sigkill", "usage-parent-interrupt"))
def test_usage_role_name_never_exempts_missing_instrumentation(tmp_path: Path, role: str) -> None:
    with pytest.raises(RuntimeError, match="coverage bootstrap failed"):
        reconcile_child_manifests(
            {41001: {"cov_start": 0, "exited": False, "strict": True, "role": role}},
            set(), tmp_path, str(tmp_path / "parent"), 41000,
            create_shard_snapshot, lambda _snapshot: None,
        )


def test_usage_role_name_never_hides_a_child_save_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="reported coverage save failure"):
        reconcile_child_manifests(
            {41001: {"cov_start": 1, "exited": False, "strict": True,
                     "role": "usage-self-sigkill", "terminal_error": "save_failed"}},
            set(), tmp_path, str(tmp_path / "parent"), 41000,
            create_shard_snapshot, lambda _snapshot: None,
        )
