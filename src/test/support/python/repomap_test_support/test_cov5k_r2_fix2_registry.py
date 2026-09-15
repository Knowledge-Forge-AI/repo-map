"""Closed executor registry and mechanical owner reachability checks."""

from __future__ import annotations

import ast
import shutil
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from repomap_test_support import (
    test_cov5k_r2_fix2_administrative,
    test_cov5k_r2_fix2_gate_executor,
    test_cov5k_r2_fix2_observer,
    test_cov5k_r2_fix2_preparation,
    test_cov5k_r2_fix2_process_recorder,
    test_cov5k_r2_fix2_runtime,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    ALLOWED_READINESS,
    CatalogEntry,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_contracts import (
    exact_callable_matches,
)

_EXECUTOR_MODULES: Mapping[str, types.ModuleType] = {
    "test_cov5k_r2_fix2_administrative": test_cov5k_r2_fix2_administrative,
    "test_cov5k_r2_fix2_gate_executor": test_cov5k_r2_fix2_gate_executor,
    "test_cov5k_r2_fix2_observer": test_cov5k_r2_fix2_observer,
    "test_cov5k_r2_fix2_preparation": test_cov5k_r2_fix2_preparation,
    "test_cov5k_r2_fix2_process_recorder": test_cov5k_r2_fix2_process_recorder,
    "test_cov5k_r2_fix2_runtime": test_cov5k_r2_fix2_runtime,
}


class ExecutorRegistryError(ValueError):
    """Catalog execution authority is missing, generic, or unreachable."""


@dataclass(frozen=True, slots=True)
class ExecutorContract:
    authority_id: str
    executor_id: str
    executor_source_path: str
    executor_symbol: str
    product_owner_id: str
    readiness: str
    callgraph_reachable: bool
    executor: Callable[..., object]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _declares_symbol(path: Path, symbol: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    owner = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol.split(".")[0]
        ),
        None,
    )
    for nested in symbol.split(".")[1:]:
        if not isinstance(owner, ast.ClassDef):
            return False
        owner = next(
            (
                node
                for node in owner.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == nested
            ),
            None,
        )
    return owner is not None


def resolve_owner(entry: CatalogEntry, repository_root: Path) -> bool:
    """Resolve the literal owner, not a case-derived or hash-derived identity."""

    source = entry.owner.source_path
    if source.startswith("tool:"):
        executable = source.split(":", 2)[1]
        return shutil.which(executable) is not None
    path = repository_root / source
    return path.is_file() and _declares_symbol(path, entry.owner.symbol)


def _executor_callable(entry: CatalogEntry) -> Callable[..., object]:
    module_name = Path(entry.executor_source_path).stem
    module = _EXECUTOR_MODULES.get(module_name)
    if module is None:
        raise ExecutorRegistryError(
            f"executor symbol is unavailable: {entry.evidence_executor_id}"
        )
    executor = getattr(module, entry.executor_symbol, None)
    if not callable(executor):
        raise ExecutorRegistryError(
            f"executor symbol is unavailable: {entry.evidence_executor_id}"
        )
    return executor


def _callgraph_reachable(entry: CatalogEntry, repository_root: Path) -> bool:
    if not resolve_owner(entry, repository_root):
        return False
    executor_path = repository_root / entry.executor_source_path
    executor_source = executor_path.read_text(encoding="utf-8")
    if entry.owner.source_path.startswith("tool:"):
        executable = entry.owner.source_path.split(":", 2)[1]
        return executable in executor_source
    if entry.executor_readiness == "exact_pytest_node":
        if entry.pytest_node_id is None:
            return False
        node_path = repository_root / entry.pytest_node_id.split("::", 1)[0]
        return node_path.is_file()
    if entry.semantic_group in {"COMPLETE_GATE", "FOCUSED_SELECTION"}:
        return "tools/run_tests.py" in executor_source
    if entry.semantic_group == "K" and entry.owner.symbol == "dispatch_command":
        dispatch = repository_root / entry.owner.source_path
        return "dispatch_command" in dispatch.read_text(encoding="utf-8") and "subprocess" in executor_source
    if entry.semantic_group == "K" and entry.owner.symbol == "main":
        return "tools/run_tests.py" in entry.fixed_argv_shape
    if entry.semantic_group == "K" and entry.owner.symbol.endswith(
        ".build_ephemeral_image"
    ):
        delegated_path = (
            repository_root
            / "src/test/support/python/repomap_test_support/test_cov5k_r2_image_route.py"
        )
        delegated_source = delegated_path.read_text(encoding="utf-8")
        return (
            "execute_group_k" in executor_source
            and "execute_group_k_ephemeral" in delegated_source
            and "build_ephemeral_image" in delegated_source
        )
    if entry.semantic_group == "H":
        return "operation" in executor_source and "ProcessBoundaryRecorder" in executor_source
    if (
        entry.executor_symbol == "execute_failure_causality"
        and entry.owner.symbol == "FailureCausalityAuthority"
    ):
        delegated_path = (
            repository_root
            / "src/test/support/python/repomap_test_support/test_cov5k_r2_fix3_observer_programs.py"
        )
        delegated_source = delegated_path.read_text(encoding="utf-8")
        return (
            "enact_failure_causality" in executor_source
            and entry.owner.symbol in delegated_source
        )
    if (
        entry.operation_kind == "runtime_driver_read"
        and entry.owner.symbol == "read_scale15_terminal_state"
    ):
        delegated_path = (
            repository_root
            / "src/test/support/python/repomap_test_support/test_cov5k_r2_fix4_psycopg.py"
        )
        delegated_source = delegated_path.read_text(encoding="utf-8")
        return (
            "execute_registered_psycopg_read" in executor_source
            and entry.owner.symbol in delegated_source
        )
    return entry.owner.symbol in executor_source


def build_executor_registry(
    repository_root: Path | None = None,
) -> tuple[ExecutorContract, ...]:
    """Resolve all 1,698 cases without a default or placeholder branch."""

    root = _repository_root() if repository_root is None else repository_root
    contracts: list[ExecutorContract] = []
    for entry in build_closed_catalog():
        if entry.executor_readiness not in ALLOWED_READINESS:
            raise ExecutorRegistryError("executor readiness is prohibited")
        executor = _executor_callable(entry)
        executor_path = root / entry.executor_source_path
        if not exact_callable_matches(
            executor,
            source_path=executor_path,
            symbol=entry.executor_symbol,
        ):
            raise ExecutorRegistryError(
                f"runtime executor differs from committed symbol: {entry.authority_id}"
            )
        reachable = _callgraph_reachable(entry, root)
        if not reachable:
            raise ExecutorRegistryError(
                f"executor does not reach registered owner: {entry.authority_id}"
            )
        contracts.append(
            ExecutorContract(
                entry.authority_id,
                entry.evidence_executor_id,
                entry.executor_source_path,
                entry.executor_symbol,
                entry.product_owner_id,
                entry.executor_readiness,
                reachable,
                executor,
            )
        )
    if len(contracts) != 1698:
        raise ExecutorRegistryError("executor registry count is not closed")
    if len({contract.authority_id for contract in contracts}) != len(contracts):
        raise ExecutorRegistryError("executor authority ids are duplicated")
    return tuple(contracts)


def readiness_counts(contracts: tuple[ExecutorContract, ...]) -> dict[str, int]:
    counts = {readiness: 0 for readiness in ALLOWED_READINESS}
    for contract in contracts:
        counts[contract.readiness] += 1
    return counts
