from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from repomap_kg.storage.rowwise_caller_contracts import (
    RECEIPTLESS_BINDINGS,
    ROWWISE_CALLER_CONTRACTS,
)


_LOADERS = {"load_canonical_observations", "load_file_observations"}


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "src/main/python/repomap_kg").is_dir():
            return parent
    raise AssertionError("repository root is unavailable")


class _ReceiptlessBindingVisitor(ast.NodeVisitor):
    def __init__(self, source_path: str) -> None:
        self.source_path = source_path
        self.owners: list[str] = []
        self.bindings: Counter[tuple[str, str, str, str]] = Counter()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.owners.append(node.name)
        owner = ".".join(self.owners)
        defaults = (*node.args.defaults, *node.args.kw_defaults)
        for default in defaults:
            if isinstance(default, ast.Name) and default.id in _LOADERS:
                self.bindings[(self.source_path, owner, "default", default.id)] += 1
        self.generic_visit(node)
        self.owners.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _LOADERS:
            owner = ".".join(self.owners) or "<module>"
            self.bindings[(self.source_path, owner, "call", node.func.id)] += 1
        self.generic_visit(node)


def _discovered_bindings() -> Counter[tuple[str, str, str, str]]:
    root = _repository_root()
    paths = [
        *(root / "src/main/python/repomap_kg").rglob("*.py"),
        *(root / "tools").glob("*.py"),
    ]
    discovered: Counter[tuple[str, str, str, str]] = Counter()
    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _ReceiptlessBindingVisitor(relative_path)
        visitor.visit(tree)
        discovered.update(visitor.bindings)
    return discovered


def test_arch3e_classifies_every_required_public_and_programmatic_surface() -> None:
    contracts = {contract.caller_id: contract for contract in ROWWISE_CALLER_CONTRACTS}

    assert set(contracts) == {
        "api.acquire",
        "bulk.import",
        "github.acquire",
        "programmatic.load-canonical-observations",
        "programmatic.load-file-observations",
        "programmatic.refresh-graph-rowwise",
        "sources.import-archive",
        "sources.import-warc",
        "sources.ingest-feed",
        "storage.load-canonical",
        "storage.load-files",
        "tool.compare-pg-connectors-seed",
        "tool.scale7-rowwise-baseline",
    }
    assert {
        caller_id: contract.future_behavior for caller_id, contract in contracts.items()
    } == {
        "api.acquire": "acquisition-only non-mutating input",
        "bulk.import": "acquisition-only non-mutating input",
        "github.acquire": "acquisition-only non-mutating input",
        "programmatic.load-canonical-observations": "announced retirement",
        "programmatic.load-file-observations": "announced retirement",
        "programmatic.refresh-graph-rowwise": "complete staged publication",
        "sources.import-archive": "acquisition-only non-mutating input",
        "sources.import-warc": "acquisition-only non-mutating input",
        "sources.ingest-feed": "acquisition-only non-mutating input",
        "storage.load-canonical": "announced retirement",
        "storage.load-files": "complete staged publication",
        "tool.compare-pg-connectors-seed": "complete staged publication",
        "tool.scale7-rowwise-baseline": "announced retirement",
    }
    for caller_id, contract in contracts.items():
        assert contract.current_receiptless_mutation is False
        assert contract.migration_phase in {"ARCH4A", "ARCH4B", "ARCH4C"}
        assert contract.replacement_contract
        assert contract.compatibility_boundary


def test_arch3e_binding_registry_exactly_matches_production_and_tool_source() -> None:
    expected = Counter(
        {
            (
                binding.source_path,
                binding.owner,
                binding.binding_kind,
                binding.loader,
            ): binding.occurrences
            for binding in RECEIPTLESS_BINDINGS
        }
    )

    assert _discovered_bindings() == expected
    contract_ids = {contract.caller_id for contract in ROWWISE_CALLER_CONTRACTS}
    assert {binding.contract_id for binding in RECEIPTLESS_BINDINGS} <= contract_ids
