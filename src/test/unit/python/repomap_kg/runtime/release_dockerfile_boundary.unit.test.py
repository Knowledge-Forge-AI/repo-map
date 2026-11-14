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
    # correction, and the D12 linux-libc-dev 6.12.117-1 manifest refresh.
    # The former D12 hash is reproduced by restoring only that package row;
    # an alias calling itself would not detect a renderer regression.
    cases = (
        (release.DYNAMIC_PACKAGE_MANIFEST, release.PSYCOPG_LIBPQ_VERSION,
         "20db9ee3957945882d3a2f1fa83626a6cd37235ed0fdd4665e6d83c99ca37cf2"),
        (release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST, release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
         "94787a9f46a8c8ca407954bfad1a19ced79fe104c4caa4d47113d3af5fc105a8"),
    )
    for manifest, libpq_version, expected in cases:
        assert hashlib.sha256(render_server_dockerfile(manifest, libpq_version).encode()).hexdigest() == expected


def test_former_amd64_recipe_is_reproduced_by_only_restoring_the_builder_header_package() -> None:
    manifest = dict(release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST)
    platform = manifest["amd64"]
    previous = release.DebPackage(
        "linux-libc-dev", "6.12.116-1", "all",
        "c43f5c6dc104f2a2ce985d6d68d3575a7be6fe904313efa7b10edfa0170f9dce",
    )
    assert sum(row.name == previous.name for row in platform.builder) == 1
    manifest["amd64"] = platform._replace(builder=tuple(
        previous if row.name == previous.name else row for row in platform.builder
    ))
    rendered = render_server_dockerfile(manifest, release_manifest.D12_CANDIDATE_LIBPQ_VERSION)
    assert hashlib.sha256(rendered.encode()).hexdigest() == (
        "03157e09e1b68f731c7869578fdc2f685198817b70e4544dcbdd63e840a350ce"
    )


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
