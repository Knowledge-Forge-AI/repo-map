from __future__ import annotations

from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, replace
import subprocess
from typing import Callable, Sequence
from unittest.mock import patch

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    CatalogEntry,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidence,
    ExecutorEvidenceError,
    verify_executor_evidence,
)
from repomap_test_support import test_cov5k_r2_fix2_runtime as runtime
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    execute_runtime_driver_read,
    execute_terminal_live_cohort,
    execute_terminal_read,
)
from repomap_test_support.test_cov5k_r2_fix4_psycopg import (
    public_expected_authority,
)
from repomap_test_support.test_cov5k_r2_fix4_terminal_contexts import (
    TerminalResultContext,
    verify_terminal_context_distinctions,
)
import scale15_actual_path_readback as readback
from scale15_terminal_contracts import (
    CleanupState,
    ExpectedRefreshAuthority,
    PublicationState,
    StageState,
    TerminalReadback,
)


_CATEGORIES = (
    "authentication",
    "class_08",
    "semantic_schema",
    "success",
    "transport_refusal",
    "unavailable",
)


class _CategoryError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _Readback:
    class _State:
        value = "success"

    publication_state = _State()


class _PsqlCompletion(subprocess.CompletedProcess[str]):
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        super().__init__(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@dataclass
class _TerminalResultContextDouble(TerminalResultContext):
    observed_fields: Iterable[tuple[str, object]]
    scenario_program_identity: str


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return None


def _entries(*, group: str, operation: str):
    return tuple(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == group and entry.operation_kind == operation
    )


def _psycopg_entry(category: str):
    return next(
        entry
        for entry in _entries(group="D", operation="runtime_driver_read")
        if dict(entry.parameter_values)["driver"] == "psycopg"
        and dict(entry.parameter_values)["failure_category"] == category
    )


def _terminal_readback(state: PublicationState) -> TerminalReadback:
    return TerminalReadback(
        state,
        StageState.PUBLISHED_RECONCILED,
        CleanupState.COMPLETED,
        {},
        "a" * 64,
        1,
        1,
    )


def _owner_seams(category: str) -> ExitStack:
    stack = ExitStack()
    state = PublicationState.PUBLISHED if category == "success" else PublicationState.NOT_PUBLISHED
    stack.enter_context(patch.object(readback, "read_run_authority", lambda *_a, **_k: object()))
    stack.enter_context(
        patch.object(readback, "read_latest_receipt_bearing_publication", lambda *_a, **_k: object())
    )
    stack.enter_context(
        patch.object(readback, "_psycopg_connection_params_from_psql_args", lambda _a: {})
    )
    stack.enter_context(patch.object(readback.psycopg, "connect", lambda **_k: _Connection()))
    stack.enter_context(
        patch.object(readback, "classify_terminal_evidence", lambda *_a, **_k: _terminal_readback(state))
    )
    if category not in {"success", "unavailable"}:
        stack.enter_context(
            patch.object(
                readback,
                "read_run_authority",
                lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(category)),
            )
        )
    return stack


def _rebind_result(result, owner):
    digest = canonical_digest(
        {
            "authority_id": result.authority_id,
            "frozen_parameter_digest": result.frozen_parameter_digest,
            "observed_enacted_parameter_digest": result.observed_enacted_parameter_digest,
            "owner": owner,
            "scenario_program_identity": result.scenario_program_identity,
            "observed_product_events": result.observed_product_events,
            "observed_fields": result.observed_fields,
        }
    )
    return replace(result, owner_entry_evidence=owner, result_digest=digest)


def _execute_with_caller_terminal_owner(
    entry: CatalogEntry,
    *,
    psql_args: Sequence[str],
    expected_authority: ExpectedRefreshAuthority,
    terminal_owner: Callable[..., object],
) -> ExecutorEvidence:
    kwargs: dict[str, Callable[..., object]] = {"terminal_owner": terminal_owner}
    return execute_runtime_driver_read(
        entry,
        psql_args=psql_args,
        expected_authority=expected_authority,
        psql_executable="psql",
        psql_runner=subprocess.run,
        **kwargs,
    )


@pytest.mark.parametrize("category", _CATEGORIES)
def test_fix4_rejects_caller_supplied_psycopg_category_owner(category: str) -> None:
    def terminal_owner(*_args: object, **_kwargs: object) -> _Readback:
        if category != "success":
            raise _CategoryError(category)
        return _Readback()

    with pytest.raises(TypeError, match="terminal_owner"):
        _execute_with_caller_terminal_owner(
            _psycopg_entry(category),
            psql_args=("-h", "127.0.0.1"),
            expected_authority=public_expected_authority(),
            terminal_owner=terminal_owner,
        )


def test_fix4_rejects_same_module_alternate_owner_with_right_shape() -> None:
    namespace = dict(runtime.__dict__)
    exec(
        compile(
            "def same_module_alternate(*_args, **_kwargs):\n"
            "    class State: value = 'success'\n"
            "    class Readback: publication_state = State()\n"
            "    return Readback()\n",
            runtime.__file__,
            "exec",
        ),
        namespace,
    )
    with pytest.raises(TypeError, match="terminal_owner"):
        _execute_with_caller_terminal_owner(
            _psycopg_entry("success"),
            psql_args=("-h", "127.0.0.1"),
            expected_authority=public_expected_authority(),
            terminal_owner=namespace["same_module_alternate"],
        )


@pytest.mark.parametrize("category", _CATEGORIES)
def test_fix4_exact_registered_owner_enacts_each_frozen_category(category: str) -> None:
    with _owner_seams(category):
        result = execute_runtime_driver_read(
            _psycopg_entry(category),
            psql_args=("-h", "127.0.0.1"),
            expected_authority=public_expected_authority(),
        )
    assert dict(result.observed_fields)["failure_category"] == category
    verify_executor_evidence(_psycopg_entry(category), result)


def test_fix4_verifier_rejects_registered_owner_digest_mismatch() -> None:
    entry = next(
        entry
        for entry in _entries(group="D", operation="runtime_driver_read")
        if dict(entry.parameter_values)["driver"] == "psql"
        and dict(entry.parameter_values)["failure_category"] == "success"
    )
    result = execute_runtime_driver_read(
        entry,
        psql_args=(),
        expected_authority=public_expected_authority(),
        psql_runner=lambda *_a, **_k: _PsqlCompletion(),
    )
    assert result.owner_entry_evidence is not None
    owner = replace(result.owner_entry_evidence, module_source_digest="0" * 64)
    with pytest.raises(ExecutorEvidenceError, match="module digest"):
        verify_executor_evidence(entry, _rebind_result(result, owner))


def test_fix4_verifier_rejects_same_module_alternate_qualified_symbol() -> None:
    entry = next(
        entry
        for entry in _entries(group="D", operation="terminal_read")
        if dict(entry.parameter_values)["dimension"] == "one_read"
    )
    result = execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
    assert result.owner_entry_evidence is not None
    owner = replace(
        result.owner_entry_evidence,
        qualified_symbol="scale15_actual_path_readback.read_scale15_terminal_state",
    )
    with pytest.raises(ExecutorEvidenceError, match="qualified symbol"):
        verify_executor_evidence(entry, _rebind_result(result, owner))


def test_fix4_verifier_requires_owner_entry_during_operation() -> None:
    entry = next(
        entry
        for entry in _entries(group="D", operation="terminal_read")
        if dict(entry.parameter_values)["dimension"] == "one_read"
    )
    result = execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
    owner = result.owner_entry_evidence
    assert owner is not None
    assert hasattr(owner, "owner_entry_during_operation")
    mutated = replace(owner, owner_entry_during_operation=False)
    with pytest.raises(ExecutorEvidenceError, match="outside.*operation"):
        verify_executor_evidence(entry, _rebind_result(result, mutated))


def test_fix4_success_contexts_are_observed_during_owner_execution() -> None:
    entries = (
        *(
            next(
                entry
                for entry in _entries(group="D", operation="terminal_read")
                if dict(entry.parameter_values)["dimension"] == value
            )
            for value in (
                "acquisition",
                "one_read",
                "process_boundary",
                "query_fetch",
                "settlement_cleanup",
            )
        ),
        *(
            next(
                entry
                for entry in _entries(group="E", operation="terminal_live_cohort")
                if dict(entry.parameter_values)["cohort"] == value
            )
            for value in (
                "success_after_observer",
                "success_connection_churn",
                "success_quiet",
            )
        ),
    )
    results = tuple(
        execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
        if entry.semantic_group == "D"
        else execute_terminal_live_cohort(entry, psql_args=(), timeout_seconds=0.5)
        for entry in entries
    )
    observed = tuple(dict(result.observed_fields) for result in results)
    assert all(item["context_condition_started"] for item in observed)
    assert all(item["context_condition_observed_during_owner"] for item in observed)
    assert all(item["observed_context"] for item in observed)
    assert len({item["context_program_id"] for item in observed}) == len(observed)
    verify_terminal_context_distinctions(
        tuple(
            _TerminalResultContextDouble(
                result.observed_fields,
                result.scenario_program_identity,
            )
            for result in results
        )
    )


def test_fix4_terminal_stage_has_no_scenario_label_fallback() -> None:
    entry = next(
        entry
        for entry in _entries(group="D", operation="terminal_read")
        if dict(entry.parameter_values)["dimension"] == "authentication"
    )
    result = execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
    observed = dict(result.observed_fields)
    assert observed["observed_stage_source"] == "owner_event"
    assert observed["observed_stage"] != "authentication_failure"
