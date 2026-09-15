"""Focused FIX4-R1 recovery parser and existing-ledger proof."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import test_hygiene_maintenance as maintenance_tool

from repomap_test_support.resource_gc_ledger import GcLedger, GcLedgerError
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
from repomap_test_support.resource_operator_reclamation_test_support import (
    PROJECT,
    private_root,
)
from repomap_test_support.test_scratch import select_scratch_root


def test_recover_parser_requires_pass_id() -> None:
    with pytest.raises(SystemExit) as caught:
        maintenance_tool.parser().parse_args(["recover"])

    assert caught.value.code == 2


def test_recover_with_pass_id_refuses_absent_ledger_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = private_root(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))

    with pytest.raises(GcLedgerError, match="GC pass record is invalid"):
        maintenance_tool.main(["recover", "absent-ledger"])

    assert not tuple((root / ".maintenance" / PROJECT).iterdir())


def test_recover_with_valid_existing_ledger_reaches_real_cli_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    pass_id = "fix4-r1-focused-recovery"
    registry = ClaimRegistry(root, PROJECT)
    setup_owner = registry.acquire_maintenance("recover-setup", now_seconds=4_000)
    ledger = GcLedger.create(
        root,
        project=PROJECT,
        pass_id=pass_id,
        trigger="operator_scheduled",
        configuration_digest="a" * 64,
        maintenance_owner_token=setup_owner.owner_token,
        now_seconds=4_000,
    )
    registry.release_maintenance(setup_owner)
    assert GcLedger.open(ledger.root).pass_id == pass_id

    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    assert os.environ["REPOMAP_TEST_SCRATCH_ROOT"] == str(root)
    assert select_scratch_root(os.environ) == root

    assert maintenance_tool.main(["recover", pass_id]) == 0
    assert "'stale_locks': 0" in capsys.readouterr().out
    assert not tuple((root / ".maintenance" / PROJECT).iterdir())
