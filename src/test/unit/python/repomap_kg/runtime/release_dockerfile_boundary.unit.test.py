"""Pure release recipe leaf and public API equivalence owners."""

from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess
import sys

from common_lore_index.runtime import commands, release, release_manifest
from common_lore_index.runtime.release_dockerfile import render_server_dockerfile

ROOT = Path(__file__).resolve().parents[6]


def test_commands_reexports_pure_leaf_and_preserves_recipe_bytes() -> None:
    assert commands.render_server_dockerfile is render_server_dockerfile
    # Original a06142b renderer, with only the approved exact four-notice COPY
    # correction. These frozen output identities were compared before extraction
    # acceptance; an alias calling itself would not detect a renderer regression.
    cases = (
        (release.DYNAMIC_PACKAGE_MANIFEST, release.PSYCOPG_LIBPQ_VERSION,
         "20db9ee3957945882d3a2f1fa83626a6cd37235ed0fdd4665e6d83c99ca37cf2"),
        (release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST, release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
         "b4b1e44be8d99d0f481e8e35b5e172c96dba58cebe2199a3926d3cde092b6337"),
    )
    for manifest, libpq_version, expected in cases:
        assert hashlib.sha256(render_server_dockerfile(manifest, libpq_version).encode()).hexdigest() == expected


def test_pure_leaf_imports_with_database_modules_blocked() -> None:
    canary = r"""
import importlib.abc
import sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        forbidden = (
            "psycopg", "psycopg2", "sqlalchemy",
            "sqlite3", "tree_sitter", "tree_sitter_rust",
            "common_lore_index.storage",
            "common_lore_index.ops.rust_pilot_publication",
        )
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            raise ImportError("database/publication import blocked")
        return None

sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, Blocker())
from common_lore_index.runtime.release_dockerfile import render_server_dockerfile
assert callable(render_server_dockerfile)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", canary, str(ROOT / "src/main/python")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
