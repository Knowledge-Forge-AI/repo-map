"""Maintained source templates for false-identity initialization and helper provenance."""

INITIALIZATION = r'''
from __future__ import annotations
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass, replace
import subprocess
from typing import Callable, Sequence
from unittest.mock import patch
import pytest
from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry, build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidence, ExecutorEvidenceError, verify_executor_evidence
from repomap_test_support import test_cov5k_r2_fix2_runtime as runtime
from repomap_test_support.test_cov5k_r2_fix2_runtime import execute_runtime_driver_read, execute_terminal_live_cohort, execute_terminal_read
from repomap_test_support.test_cov5k_r2_fix4_psycopg import public_expected_authority
from repomap_test_support.test_cov5k_r2_fix4_terminal_contexts import TerminalResultContext, verify_terminal_context_distinctions
import scale15_actual_path_readback as readback
from scale15_terminal_contracts import CleanupState, ExpectedRefreshAuthority, PublicationState, StageState, TerminalReadback
_CATEGORIES = ('authentication', 'class_08', 'semantic_schema', 'success', 'transport_refusal', 'unavailable')

class _CategoryError(RuntimeError):

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)

class _Readback:

    class _State:
        value = 'success'
    publication_state = _State()

class _PsqlCompletion(subprocess.CompletedProcess[str]):

    def __init__(self, returncode: int=0, stdout: str='', stderr: str='') -> None:
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
    pass

def _psycopg_entry(category: str):
    pass

def _terminal_readback(state: PublicationState) -> TerminalReadback:
    pass

def _owner_seams(category: str) -> ExitStack:
    pass

def _rebind_result(result, owner):
    pass

def _execute_with_caller_terminal_owner(entry: CatalogEntry, *, psql_args: Sequence[str], expected_authority: ExpectedRefreshAuthority, terminal_owner: Callable[..., object]) -> ExecutorEvidence:
    pass

@pytest.mark.parametrize('category', _CATEGORIES)
def test_fix4_rejects_caller_supplied_psycopg_category_owner(category: str) -> None:
    pass

def test_fix4_rejects_same_module_alternate_owner_with_right_shape() -> None:
    pass

@pytest.mark.parametrize('category', _CATEGORIES)
def test_fix4_exact_registered_owner_enacts_each_frozen_category(category: str) -> None:
    pass

def test_fix4_verifier_rejects_registered_owner_digest_mismatch() -> None:
    pass

def test_fix4_verifier_rejects_same_module_alternate_qualified_symbol() -> None:
    pass

def test_fix4_verifier_requires_owner_entry_during_operation() -> None:
    pass

def test_fix4_success_contexts_are_observed_during_owner_execution() -> None:
    pass

def test_fix4_terminal_stage_has_no_scenario_label_fallback() -> None:
    pass
'''

HELPERS = {
    '_entries': r'''
def _entries(*, group: str, operation: str):
    return tuple((entry for entry in build_closed_catalog() if entry.semantic_group == group and entry.operation_kind == operation))
''',
    '_psycopg_entry': r'''
def _psycopg_entry(category: str):
    return next((entry for entry in _entries(group='D', operation='runtime_driver_read') if dict(entry.parameter_values)['driver'] == 'psycopg' and dict(entry.parameter_values)['failure_category'] == category))
''',
    '_execute_with_caller_terminal_owner': r'''
def _execute_with_caller_terminal_owner(entry: CatalogEntry, *, psql_args: Sequence[str], expected_authority: ExpectedRefreshAuthority, terminal_owner: Callable[..., object]) -> ExecutorEvidence:
    kwargs: dict[str, Callable[..., object]] = {'terminal_owner': terminal_owner}
    return execute_runtime_driver_read(entry, psql_args=psql_args, expected_authority=expected_authority, psql_executable='psql', psql_runner=subprocess.run, **kwargs)
''',
}
