"""Actual dependency-closure owners for the Rust qualification command.

The test reads the frozen manifest and runs the resolver against the checkout;
it never imports the resolved production closure as a qualification shortcut.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci.qualification_rust_closure import ClosureRefused, module_path, required_sources
from ci.qualification_rust_manifest import GUEST_FILES

ROOT = Path(__file__).resolve().parents[6]
MANIFEST = ROOT / "tools/ci/rust_pilot_qualification_manifest.json"


def test_frozen_manifest_matches_resolved_component_closure() -> None:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    guest_init = "src/main/python/common_lore_index/extractors/rust_pilot/guest/__init__.py"
    expected = set(document["closure"]["python_paths"])
    assert required_sources(ROOT) | set(GUEST_FILES) | {guest_init} == expected


@pytest.mark.parametrize("module", [
    "psycopg",
    "psycopg2",
    "sqlalchemy", "sqlite3",
    "tree_sitter", "tree_sitter_rust",
    "common_lore_index.storage",
    "common_lore_index.storage.staged_ingestion",
    "common_lore_index.storage.staged_prepared_refresh",
    "common_lore_index.ops.rust_pilot_publication",
])
def test_resolver_refuses_database_and_publication_modules(module: str) -> None:
    with pytest.raises(ClosureRefused, match="forbidden_host_import"):
        module_path(ROOT, module)
