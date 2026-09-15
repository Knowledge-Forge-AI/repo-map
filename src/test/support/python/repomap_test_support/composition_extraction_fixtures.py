"""Public test fixtures for composition extraction and canonicalization integration tests."""

from __future__ import annotations

from pathlib import Path

from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig

DEPLOY_SH_CONTENT = """#!/bin/bash
source ./lib/common.sh
main() {
    log_info "Deploying"
    run_bats_tests
}
main "$@"
"""

LIB_COMMON_SH_CONTENT = """#!/bin/bash
log_info() {
    echo "[INFO] $1"
}
"""

PROCESS_AWK_CONTENT = """BEGIN { count = 0 }
{ count++ }
END { print count }
"""

README_MD_CONTENT = """# Shell Project
Refer to [Deploy](deploy.sh) for entrypoint.
"""

SCRIPT_SH_CONTENT = """#!/bin/bash
valid_helper() {
    echo "valid"
}
"""


def populate_shell_project(proj: Path) -> None:
    """Populate a test directory with multi-file shell, awk, and markdown fixtures."""
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "deploy.sh").write_text(DEPLOY_SH_CONTENT, encoding="utf-8")
    lib_dir = proj / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "common.sh").write_text(LIB_COMMON_SH_CONTENT, encoding="utf-8")
    (proj / "process.awk").write_text(PROCESS_AWK_CONTENT, encoding="utf-8")
    (proj / "README.md").write_text(README_MD_CONTENT, encoding="utf-8")


def populate_valid_script_project(proj: Path) -> None:
    """Populate a valid extraction control for canonicalization diagnostics."""
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "script.sh").write_text(SCRIPT_SH_CONTENT, encoding="utf-8")


def create_composition_graph_config(
    source_dir: Path,
    *,
    graph_id: str = "test-composition-graph",
    repository_name: str = "test-comp-repo",
    privacy: str = "public-dev",
) -> OpsGraphConfig:
    """Build a single-source OpsGraphConfig for composition extraction tests."""
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(graph_id, "primary"),
        source_definition_id=f"src1:{graph_id}-primary",
        alias="primary",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(source_dir),
        root_path_expanded=str(source_dir),
        repository_name=repository_name,
        logical_root=".",
        privacy=privacy,
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
        input_name=None,
    )
    return OpsGraphConfig(
        id=graph_id,
        name=f"Graph {graph_id}",
        root_path="",
        root_path_expanded="",
        repository_name=repository_name,
        privacy=privacy,
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )


__all__ = [
    "DEPLOY_SH_CONTENT",
    "LIB_COMMON_SH_CONTENT",
    "PROCESS_AWK_CONTENT",
    "README_MD_CONTENT",
    "SCRIPT_SH_CONTENT",
    "create_composition_graph_config",
    "populate_valid_script_project",
    "populate_shell_project",
]
