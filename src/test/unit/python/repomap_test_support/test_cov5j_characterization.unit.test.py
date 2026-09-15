from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import ModuleType

import scale28_preparation_worker_process as process_owner

import pytest

from repomap_test_support.scale28_fix10_candidate_receipt import (
    OBSERVED_CORRECTED_FIX9_EVIDENCE,
    ReceiptDefect,
    receipt_defects,
)
from repomap_test_support.scale28_fix9_failure_inventory import FORMER_FAILURES
from repomap_test_support.test_cov5i_characterization import CATEGORY_CONTRACTS
from repomap_test_support.test_cov5j_characterization import (
    BLOCKED_GROUPS,
    COMPLETED_GROUPS,
    CORRECTED_CANDIDATE_PATCH_SHA256,
    FIX10_COMMIT,
    FIX11_ACCEPTANCE_TESTS,
    FROZEN_SOURCE_DIGESTS,
    GroupStatus,
    SUPERSEDED_R1_SOURCE_DIGESTS,
    verify_independent_trace_manifest,
    verify_source_freeze,
)
from scale28_preparation_policy import DEFAULT_PREPARATION_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_cov5j_freezes_pushed_fix10_source_policy_and_protocol() -> None:
    with pytest.raises(ValueError, match="source, policy, or protocol changed"):
        verify_source_freeze(_REPOSITORY_ROOT)
    assert len(FIX10_COMMIT) == 40
    assert len(CORRECTED_CANDIDATE_PATCH_SHA256) == 64
    assert len(FROZEN_SOURCE_DIGESTS) == 14
    assert SUPERSEDED_R1_SOURCE_DIGESTS == {
        "tools/scale28_preparation_resources.py": (
            "ab0298a4f5f39c7f586e1b5a0912565f4fbe320b7540d7aa15e10bac04a0aa90"
        )
    }
    assert _REPOSITORY_ROOT.joinpath(
        "tools/scale28_runtime_identity.py"
    ).is_file()


def test_cov5j_independently_verifies_closed_critical_path_manifest() -> None:
    verify_independent_trace_manifest()


def test_safety3_attempt_clock_starts_before_worker_process_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adr = _REPOSITORY_ROOT.joinpath(
        "docs/adr/2026/07/0044-bounded-startup-authority-decomposition.md"
    ).read_text(encoding="utf-8")
    assert "preparation clock begins before one worker spawn" in adr.lower()
    events: list[str] = []
    origin = 9_500_000_123

    def clock() -> int:
        events.append("clock")
        return origin

    class Process:
        def start(self) -> None:
            events.append("start")
            assert events == ["clock", "start"]

    # Exercise both actual spawn branches, including an absent __main__ entry.
    for main in (None, ModuleType("__main__")):
        with monkeypatch.context() as patch:
            events.clear()
            if main is None:
                patch.delitem(sys.modules, "__main__", raising=False)
            else:
                patch.setitem(sys.modules, "__main__", main)
            patch.setattr(process_owner.time, "monotonic_ns", clock)
            assert process_owner._start_without_ambient_parent_main(Process()) == origin
            assert events == ["clock", "start"]

    source = _REPOSITORY_ROOT.joinpath("tools/scale28_preparation_worker.py")
    names = {node.id for node in ast.walk(ast.parse(source.read_text()))
             if isinstance(node, ast.Name)}
    assert not names & {
        "_operation_deadline_after_ready", "_await_worker_ready",
        "PREPARATION_STARTUP_TIMEOUT_MS",
    }


def test_cov5j_historical_policy_is_superseded_by_fix12_selection() -> None:
    policy = DEFAULT_PREPARATION_DEADLINE_POLICY
    assert policy.attempt_timeout_ms == 3_400
    assert policy.total_timeout_ms == 8_900
    assert policy.maximum_attempts == 2
    assert policy.acknowledgement_timeout_ms == 150
    assert policy.receipt_timeout_ms == 300
    assert policy.process_settlement_timeout_ms == 300


def test_cov5j_confirms_exact_receipt_blocker_without_base_inference() -> None:
    assert receipt_defects(OBSERVED_CORRECTED_FIX9_EVIDENCE) == (
        ReceiptDefect.OWNER_PRIVATE_RECEIPT_MISSING,
        ReceiptDefect.EXACT_BASE_MISSING,
        ReceiptDefect.MANIFEST_INCOMPLETE,
    )


def test_cov5j_retains_former_failure_and_category_manifests() -> None:
    assert len(FORMER_FAILURES) == 14
    assert len({case.node_id for case in FORMER_FAILURES}) == 14
    assert len(CATEGORY_CONTRACTS) == 8
    for case in FORMER_FAILURES:
        path, separator, node = case.node_id.partition("::")
        assert separator == "::"
        assert node.startswith("test_")
        assert _REPOSITORY_ROOT.joinpath(path).is_file()


@pytest.mark.parametrize("group", COMPLETED_GROUPS, ids=lambda item: item.name)
def test_cov5j_counts_only_safe_completed_groups(group) -> None:
    assert group.status is GroupStatus.COMPLETED
    assert group.completed_count == group.required_count


@pytest.mark.parametrize("group", BLOCKED_GROUPS, ids=lambda item: item.name)
def test_cov5j_does_not_inflate_candidate_dependent_groups(group) -> None:
    assert group.status is GroupStatus.BLOCKED_BY_MISSING_CANDIDATE_RECEIPT
    assert group.completed_count == 0


@pytest.mark.parametrize("acceptance_test", FIX11_ACCEPTANCE_TESTS)
def test_cov5j_fix11_acceptance_boundary_requires_no_retuning(
    acceptance_test: str,
) -> None:
    assert acceptance_test
    assert "increase" not in acceptance_test
    assert "assume" not in acceptance_test
    assert "suppress" not in acceptance_test
