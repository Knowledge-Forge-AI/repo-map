import ast
from pathlib import Path

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser


PRODUCTION_ROOT = Path("src/main/python/repomap_kg")
STORAGE_ROOT = PRODUCTION_ROOT / "storage"

OBSOLETE_MODULES = {
    "composed_read_adapters.py",
    "composed_read_contracts.py",
    "edge_evidence_read_adapter.py",
    "edge_evidence_read_compatibility.py",
    "edge_evidence_read_contracts.py",
    "legacy.py",
    "legacy_rows.py",
    "node_file_read_adapter.py",
    "node_file_read_compatibility.py",
    "public_read_migration.py",
    "public_read_pages.py",
    "readback_rows.py",
    "source_backed_composed_sql.py",
    "source_backed_summary.py",
    "sql_readback.py",
}

OBSOLETE_IMPORT_PREFIXES = tuple(
    f"repomap_kg.storage.{path.removesuffix('.py')}" for path in OBSOLETE_MODULES
)


def test_arch5e_obsolete_storage_modules_and_imports_are_absent() -> None:
    assert not {path.name for path in STORAGE_ROOT.glob("*.py")} & OBSOLETE_MODULES

    obsolete_imports = []
    for path in PRODUCTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(OBSOLETE_IMPORT_PREFIXES):
                    obsolete_imports.append((path.as_posix(), node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(OBSOLETE_IMPORT_PREFIXES):
                        obsolete_imports.append((path.as_posix(), node.lineno, alias.name))
    assert obsolete_imports == []


def test_arch5e_cli_parser_exposes_only_canonical_graph_readback() -> None:
    parser_source = (
        PRODUCTION_ROOT / "cli" / "storage_parser.py"
    ).read_text(encoding="utf-8")

    for obsolete_text in (
        '"--legacy"',
        '"--canonical"',
        '"canonical-nodes"',
        '"canonical-edges"',
        '"canonical-neighborhood"',
        '"--stable-key"',
        '"--source-node"',
        '"--target-node"',
    ):
        assert obsolete_text not in parser_source

    parser = build_parser()
    obsolete_argv = (
        ("storage", "canonical-nodes", "--root-path", "/tmp/fixture"),
        ("storage", "nodes", "--root-path", "/tmp/fixture", "--canonical"),
        ("storage", "summary", "--root-path", "/tmp/fixture", "--legacy"),
    )
    for argv in obsolete_argv:
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_arch5e_runtime_summaries_expose_no_legacy_graph_schema() -> None:
    checked_paths = (
        STORAGE_ROOT / "summary_rows_storage.py",
        STORAGE_ROOT / "sql_canonical.py",
        PRODUCTION_ROOT / "server" / "mcp.py",
        PRODUCTION_ROOT / "server" / "ops.py",
    )
    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        assert "legacy_nodes" not in source
        assert "legacy_edges" not in source
        assert "legacy_evidence" not in source
