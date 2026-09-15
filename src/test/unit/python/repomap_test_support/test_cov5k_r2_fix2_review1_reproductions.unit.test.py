from __future__ import annotations

import inspect
import math
from dataclasses import replace
from pathlib import Path
import re
import subprocess
import sys

import pytest

from repomap_test_support import test_cov5k_r2_fix2_observer as observer
from repomap_test_support import test_cov5k_r2_fix2_preparation as preparation
from repomap_test_support import test_cov5k_r2_fix2_runtime as runtime
from repomap_test_support.test_cov5k_r2_fix2_administrative import (
    execute_administrative_operation,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    record_process_boundary,
)
from repomap_test_support.test_cov5k_r2_fix2_receipt import (
    QualificationReceiptDraft,
    finalize_receipt,
)
from repomap_test_support.test_cov5k_r2_fix2_registry import (
    build_executor_registry,
    _callgraph_reachable,
)


def _entry(case_id: str):
    return next(entry for entry in build_closed_catalog() if entry.case_id == case_id)


def test_review1_full_executor_classification_closes_forbidden_gaps() -> None:
    contracts = build_executor_registry()
    assert len(contracts) == 1_698
    assert all(contract.callgraph_reachable for contract in contracts)
    assert all(
        contract.readiness not in {"simulated_placeholder", "missing"}
        for contract in contracts
    )


@pytest.mark.parametrize("missing_edge", ("executor", "owner"))
def test_delegated_causality_requires_both_source_edges(
    tmp_path: Path, missing_edge: str,
) -> None:
    entry = next(item for item in build_closed_catalog()
                 if item.executor_symbol == "execute_failure_causality")
    root = Path(__file__).resolve().parents[5]
    helper = "src/test/support/python/repomap_test_support/test_cov5k_r2_fix3_observer_programs.py"
    for relative in (entry.executor_source_path, entry.owner.source_path, helper):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    assert _callgraph_reachable(entry, tmp_path)
    relative = entry.executor_source_path if missing_edge == "executor" else helper
    token = "enact_failure_causality" if missing_edge == "executor" else entry.owner.symbol
    target = tmp_path / relative
    target.write_text(target.read_text().replace(token, "removed_edge"))
    assert not _callgraph_reachable(entry, tmp_path)


@pytest.mark.parametrize(
    ("executor", "owner_token"),
    (
        (preparation.execute_preparation_state_path, "HybridPreparationAuthority"),
        (runtime.execute_runtime_driver_read, "read_scale15_terminal_state"),
        (observer.execute_observer_schedule, "enact_schedule"),
        (execute_administrative_operation, "runner"),
    ),
)
def test_review1_registered_owner_must_be_reached(executor, owner_token: str) -> None:
    assert owner_token in inspect.getsource(executor)


def test_review1_group_a_must_not_self_author_observed_truth() -> None:
    assert not hasattr(preparation, "_A_PROGRAMS")


def test_review1_group_d_must_read_every_frozen_parameter() -> None:
    assert "entry.parameter_values" in inspect.getsource(runtime.execute_runtime_driver_read)


def test_review1_group_g_must_not_parse_authority_from_labels() -> None:
    source = inspect.getsource(observer.execute_observer_schedule)
    assert "entry.condition_id" not in source
    assert "entry.case_id" not in source


def test_review1_group_h_detects_child_created_and_reaped_during_operation(
    tmp_path: Path,
) -> None:
    def short_lived_owner() -> None:
        subprocess.run(
            [sys.executable, "-c", "pass"],
            shell=False,
            timeout=5,
            check=True,
        )

    evidence = record_process_boundary(short_lived_owner)
    assert evidence.host_process_count == 1


def test_review1_group_h_nested_intent_must_not_be_hardcoded() -> None:
    evidence = record_process_boundary(
        lambda: subprocess.run(
            ["psql", "--version"], check=False, capture_output=True, shell=False
        )
    )
    assert evidence.nested_psql_intent_count == 1


def test_review1_group_k_binds_actual_effective_argv(
    tmp_path: Path,
) -> None:
    captured: list[str] = []

    def run(command, **_kwargs):
        captured[:] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    argv = ("repomap-kg", "local", "db", "dump", "--database", "private", "--dry-run", "--json")
    receipt = execute_administrative_operation(
        _entry("K01-backup"), argv, cwd=tmp_path, runner=run
    )
    assert captured == list(argv)
    assert receipt.effective_argv_digest == canonical_digest(
        {"effective_argv": argv, "shell": False, "timeout_seconds": 10}
    )
    assert "private" not in receipt.redacted_argv_shape


def test_review1_group_k_freezes_disposition_and_handles_timeout() -> None:
    entry = replace(
        _entry("K11-test_harness"),
        expected_execution_disposition="controlled_timeout",
    )
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["python"], 10)

    receipt = execute_administrative_operation(
        entry, (sys.executable, "tools/run_tests.py"), cwd=Path.cwd(), runner=timeout
    )
    assert receipt.execution_disposition == "controlled_timeout"


def test_review1_canonical_encoding_distinguishes_tuple_and_list() -> None:
    assert canonical_digest(("value",)) != canonical_digest(["value"])


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_review1_canonical_encoding_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises((TypeError, ValueError), match="finite"):
        canonical_digest(value)


def test_review1_catalog_identities_are_literal_and_nonmechanical() -> None:
    entry = _entry("attempt_one_success")
    assert not hasattr(entry, "repetition_ids")
    assert entry.case_id.lower() not in entry.authority_id
    assert re.fullmatch(r"fix1\.owner\.[0-9a-f]{16}", entry.product_owner_id) is None


def test_review1_complete_final_receipt_contract_exists() -> None:
    assert QualificationReceiptDraft is not None
    assert callable(finalize_receipt)
