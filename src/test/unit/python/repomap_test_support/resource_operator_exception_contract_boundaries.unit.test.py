"""Operator exceptional-progress, public cause, and CLI interruption contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import repomap_test_support.resource_operator_reclamation as reclamation
import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    private_root,
)
from repomap_test_support.resource_operator_records import (
    PUBLIC_LOG_SCHEMA,
    SCOPE_CLASS,
    append_public_log,
)
from repomap_test_support.resource_safe_tree_failure import SafeTreeDeleteFailure
from repomap_test_support.resource_validation import HygieneValidationError


def approved() -> OperatorReclamationRequest:
    return OperatorReclamationRequest(CONFIRMATION_LITERAL, False, False)


def _carrier(cause: BaseException, *, bytes_removed: int = 512, inodes: int = 1):
    try:
        raise cause
    except BaseException as error:
        raise SafeTreeDeleteFailure(
            removed_allocated_bytes=bytes_removed,
            removed_inode_count=inodes,
            failure_category="interrupted",
        ) from error


def _public_payload(*, outcome: str, reason, category) -> dict[str, object]:
    return {
        "schema": PUBLIC_LOG_SCHEMA,
        "timestamp_seconds": 1,
        "scope_class": SCOPE_CLASS,
        "outcome": outcome,
        "force_live": False,
        "override_pins": False,
        "entry_count": 0,
        "allocated_bytes": 0,
        "inode_count": 0,
        "live_count": 0,
        "unknown_count": 0,
        "pin_count": 0,
        "marker_count": 0,
        "removed_entry_count": 0,
        "removed_allocated_bytes": 0,
        "removed_inode_count": 0,
        "point_of_no_return": outcome == "partial",
        "barrier_released": outcome != "partial",
        "partial_reason": reason,
        "partial_failure_category": category,
    }

@pytest.mark.parametrize("code", [1, 2, 255])
def test_r1a6_systemexit_codes_in_closed_range_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: int,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "interrupt")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: _carrier(SystemExit(code)),
    )

    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == code
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "partial"
    assert payload["partial_failure_category"] == "interrupted"

@pytest.mark.parametrize("code", [0, -1, 256, True, "3", None])
def test_r1a7_invalid_systemexit_codes_map_to_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code,
) -> None:
    root = private_root(tmp_path)
    add_run(root, "interrupt")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: _carrier(SystemExit(code)),
    )

    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "partial"

def test_r1a8_keyboard_interrupt_maps_to_130_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    add_run(root, "interrupt")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setattr(
        reclamation,
        "delete_run_entry",
        lambda *_args, **_kwargs: _carrier(KeyboardInterrupt()),
    )

    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 130
    captured = capsys.readouterr()
    assert json.loads(captured.out)["partial_reason"] == "interrupted"
    assert captured.err == ""

@pytest.mark.parametrize(
    ("reason", "category"),
    [(None, "interrupted"), ("interrupted", None)],
)
def test_r1a9_public_partial_log_rejects_null_cause(
    tmp_path: Path, reason, category
) -> None:
    tmp_path.chmod(0o700)
    with pytest.raises(HygieneValidationError, match="cause"):
        append_public_log(
            tmp_path,
            _public_payload(outcome="partial", reason=reason, category=category),
        )

def test_r1a10_public_partial_log_accepts_closed_cause_and_completed_nulls(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    partial = append_public_log(
        tmp_path,
        _public_payload(
            outcome="partial",
            reason="exceptional_safe_tree_failure",
            category="durability_error",
        ),
    )
    completed = append_public_log(
        tmp_path,
        _public_payload(outcome="completed", reason=None, category=None),
    )
    assert partial == completed
    with pytest.raises(HygieneValidationError, match="reason"):
        append_public_log(
            tmp_path,
            _public_payload(outcome="partial", reason="unknown", category="interrupted"),
        )

@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("wall_time_limit", "interrupted"),
        ("interrupted", "wall_time_limit"),
        ("reconciliation_failure", "unexpected_post_pnr_failure"),
        ("unexpected_post_pnr_failure", "reconciliation_failure"),
        ("exceptional_safe_tree_failure", "interrupted"),
    ],
)
def test_r3a11_public_partial_log_rejects_mismatched_cause_pair(
    tmp_path: Path, reason: str, category: str
) -> None:
    tmp_path.chmod(0o700)
    with pytest.raises(HygieneValidationError, match="relation"):
        append_public_log(
            tmp_path,
            _public_payload(outcome="partial", reason=reason, category=category),
        )

def test_r3a12_nonpartial_public_log_rejects_non_null_cause(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    with pytest.raises(HygieneValidationError, match="non-partial"):
        append_public_log(
            tmp_path,
            _public_payload(
                outcome="completed",
                reason="wall_time_limit",
                category="wall_time_limit",
            ),
        )

