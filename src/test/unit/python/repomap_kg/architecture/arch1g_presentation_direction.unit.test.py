from __future__ import annotations

import ast
from pathlib import Path

import repomap_kg.cli as cli
import repomap_kg.server.mcp_core as mcp_core
import repomap_kg.storage as storage
import repomap_kg.storage.canonical_filters as filters
from repomap_kg.cli.main import (
    __file__ as cli_main_file,
    canonical_node_kind_from_args,
    canonical_edge_filters_from_args,
    canonical_neighborhood_filters_from_args,
)


def _module_imports(module_path: str | None) -> set[str]:
    assert module_path is not None
    path = Path(module_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_canonical_filter_contract_has_stable_cli_and_mcp_exports() -> None:
    direct_contracts = {
        "canonical_node_kind_from_args": canonical_node_kind_from_args,
        "canonical_edge_filters_from_args": canonical_edge_filters_from_args,
        "canonical_neighborhood_filters_from_args": canonical_neighborhood_filters_from_args,
    }
    for name in (
        "canonical_node_kind_from_args",
        "canonical_edge_filters_from_args",
        "canonical_neighborhood_filters_from_args",
    ):
        contract = getattr(filters, name)
        assert direct_contracts[name] is contract
        assert getattr(cli, name) is contract
        assert getattr(mcp_core, name) is contract
    assert filters.StorageSchemaError is storage.StorageSchemaError


def test_canonical_filter_contract_removes_mcp_to_cli_dependency() -> None:
    assert "repomap_kg.storage.canonical_filters" in _module_imports(cli_main_file)
    assert "repomap_kg.storage.canonical_filters" in _module_imports(mcp_core.__file__)
    assert not {
        "repomap_kg.cli.main",
        "repomap_kg.cli.dispatch",
        "repomap_kg.server.mcp",
    } & _module_imports(filters.__file__)
    assert not {
        "repomap_kg.cli.main",
        "repomap_kg.cli.dispatch",
    } & _module_imports(mcp_core.__file__)
