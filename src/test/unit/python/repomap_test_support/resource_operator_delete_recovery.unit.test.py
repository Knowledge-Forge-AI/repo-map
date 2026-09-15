"""TEST-HYGIENE3B3-FIX4 post-partial delete recovery contracts."""

from __future__ import annotations

from pathlib import Path
import pytest

from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_maintenance import (
    recover_stale_admission_lock,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    ProcessLiveness,
)
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    dead,
    private_root,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteResult,
)


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def test_b12_b13_recovery_requires_fresh_operation_and_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    add_run(root, "remaining")
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: SafeTreeDeleteResult(
            False, 1, 1, "wall_time_limit"
        ),
    )
    first = reclaim_run_population(
        root,
        approved(),
        now_seconds=100,
        process_is_live=dead,
        monotonic=lambda: 0.0,
    )

    registry = ClaimRegistry(root, "repo-map_dev")
    maintenance = registry.acquire_maintenance("recover", now_seconds=4_000)
    index = AdvisoryIndex.open(root / ".index" / "repo-map_dev", scratch_root=root)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="fix4-recovery",
        trigger="operator_scheduled",
        configuration_digest="a" * 64,
        maintenance_owner_token=maintenance.owner_token,
        now_seconds=4_000,
    )
    recover_stale_admission_lock(
        index,
        registry,
        maintenance,
        ledger,
        now_seconds=4_000,
        owner_is_live=lambda _pid, _start: ProcessLiveness.DEAD,
    )
    assert index.reconcile().active_runs == 0
    registry.release_maintenance(maintenance)
    assert not index.lock_path.exists()

    monkeypatch.undo()
    refused = reclaim_run_population(
        root,
        OperatorReclamationRequest(None, False, False),
        now_seconds=4_001,
        process_is_live=dead,
    )
    completed = reclaim_run_population(
        root,
        approved(),
        now_seconds=4_002,
        process_is_live=dead,
    )

    assert first.operation_id != refused.operation_id
    assert refused.operation_id != completed.operation_id
    assert first.operation_id != completed.operation_id
    assert refused.outcome == "confirmation_refused"
    assert completed.outcome == "completed"
