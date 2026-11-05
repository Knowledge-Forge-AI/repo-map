"""Generation-domain and dependency-closure owners for Rust publication."""

from __future__ import annotations

import ast
from importlib import resources

from common_lore_index.ops.rust_pilot_publication import rust_publication_generations


def test_eg1_and_kg1_are_distinct_domain_separated_generations() -> None:
    first = rust_publication_generations(
        legacy_extractor_generation="eg1:" + "a" * 64,
        legacy_canonicalizer_generation="kg1:" + "b" * 64,
        lock_sha256="c" * 64, helper_closure_sha256="d" * 64,
    )
    changed = rust_publication_generations(
        legacy_extractor_generation="eg1:" + "a" * 64,
        legacy_canonicalizer_generation="kg1:" + "b" * 64,
        lock_sha256="c" * 64, helper_closure_sha256="e" * 64,
    )
    assert first[0].startswith("eg1:") and first[1].startswith("kg1:")
    assert first[0] != first[1] and first != changed
    assert all(len(value.split(":", 1)[1]) == 64 for value in first)


def test_module_import_closure_has_no_database_import_at_module_scope() -> None:
    source = resources.files("common_lore_index.ops").joinpath("rust_pilot_publication.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".", 1)[0]
        for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "psycopg" not in imported and "sqlite3" not in imported
