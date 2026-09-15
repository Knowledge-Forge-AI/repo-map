"""Real request and fixture construction helpers for RepoMap MCP server tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    NixSummaryRecord,
)


class McpServerRequestSupport(unittest.TestCase):
    def write_mcp_config(self, payload):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "config.json"
        config_path.write_text(json.dumps(payload))
        return config_path

    def write_ops_config(self, body: str):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        config_path = Path(tmpdir.name) / "repomap.local.toml"
        config_path.write_text(body, encoding="utf-8")
        return config_path

    def visible_ops_config(self) -> str:
        return """
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "repo_map"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/tmp/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_repo_map"

[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "~/private-visible"
repository_name = "private-visible"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"
database = "repomap_private_visible"

[[graphs]]
id = "disabled"
name = "Disabled"
root_path = "~/disabled"
repository_name = "disabled"
privacy = "private-memory"
enabled = false
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"
database = "repomap_disabled"

[[graphs]]
id = "hidden"
name = "Hidden"
root_path = "~/hidden"
repository_name = "hidden"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_hidden"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""

    def server_memory_ops_config(self, server_memory_path: Path | str) -> str:
        return self.visible_ops_config().replace(
            "enabled = false\npath = \"~/.codex/codex-vc/mcp/server-memory\"",
            f"enabled = true\npath = \"{server_memory_path}\"",
        )

    def write_visible_ops_config(self) -> Path:
        return self.write_ops_config(self.visible_ops_config())

    def write_container_internal_ops_config(self) -> Path:
        return self.write_ops_config(
            self.visible_ops_config().replace(
                'host = "127.0.0.1"',
                'host = "postgres"',
            )
        )

    def write_live_ops8_private_ops_config(self, private_root: str) -> Path:
        return self.write_ops_config(
            self.visible_ops_config().replace(
                'root_path = "~/private-visible"',
                f'root_path = "{private_root}"',
            )
        )

    def write_empty_mcp_config(self) -> Path:
        return self.write_mcp_config({"projects": {}})

    def patch_ops_config(self, config_path: Path):
        return patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)})

    def patch_mcp_and_ops_config(self, mcp_config_path: Path, ops_config_path: Path):
        return patch.dict(
            "os.environ",
            {
                "REPOMAP_MCP_CONFIG": str(mcp_config_path),
                "REPOMAP_OPS_CONFIG": str(ops_config_path),
            },
            clear=True,
        )

    def synthetic_refresh_status(
        self,
        *,
        latest_run_status: str,
        latest_run_finished_at: str | None,
        latest_run_id: int = 77,
        raw_observations: int | None = None,
        raw_observations_total: int | None = None,
        latest_run_raw_observations: int | None = None,
        canonical_nodes: int | None = None,
        canonical_edges: int | None = None,
    ):
        from repomap_kg.ops.refresh import OpsRefreshGraphStatus

        return OpsRefreshGraphStatus(
            graph_id="repo-map",
            repository_name="fixture",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="/tmp/fixture",
            root_path_expanded="/tmp/fixture",
            repository_exists=True,
            latest_run_id=latest_run_id,
            latest_run_status=latest_run_status,
            latest_run_started_at="2026-07-01T00:00:00Z",
            latest_run_finished_at=latest_run_finished_at,
            raw_observations=raw_observations,
            raw_observations_total=raw_observations_total,
            latest_run_raw_observations=latest_run_raw_observations,
            canonical_nodes=canonical_nodes,
            canonical_edges=canonical_edges,
        )

    def synthetic_nix_summary(
        self,
        *,
        root_path: str = "[root-path]",
        repository_name: str = "fixture",
    ) -> NixSummaryRecord:
        return NixSummaryRecord(
            root_path=root_path,
            repository_name=repository_name,
            nix_observations=21,
            nix_files=3,
            flake_files=1,
            raw={
                "imports": 1,
                "path_refs": 1,
                "apps": 1,
                "packages": 1,
                "dev_shells": 1,
                "checks": 1,
            },
            canonical={
                "apps": 1,
                "packages": 1,
                "dev_shells": 1,
                "checks": 1,
                "output_sections": 3,
            },
            edges={
                "import_sources": 1,
                "output_defines": 4,
                "output_section_defines": 3,
                "app_program_edges": 1,
            },
            programs={
                "app_programs_total": 1,
                "local": 1,
                "dynamic": 0,
                "external": 0,
                "unknown": 0,
            },
            paths={
                "path_refs_total": 1,
                "local": 1,
                "dynamic": 0,
                "unknown": 0,
                "repo_escaping_or_rejected": 0,
            },
            flake_inputs={
                "total": 4,
                "with_url": 3,
                "with_follows": 1,
                "redacted_sources": 4,
                "source_types": {
                    "github": 1,
                    "git": 0,
                    "path": 1,
                    "tarball": 0,
                    "follows": 1,
                    "unknown": 1,
                    "dynamic": 0,
                },
            },
            output_sections={
                "total": 6,
                "by_section": {
                    "packages": 1,
                    "apps": 1,
                    "devShells": 1,
                    "checks": 1,
                    "nixosModules": 1,
                    "darwinModules": 0,
                    "homeManagerModules": 0,
                    "overlays": 1,
                    "formatter": 0,
                    "templates": 0,
                    "legacyPackages": 0,
                },
                "by_family": {
                    "output": 4,
                    "module": 1,
                    "overlay": 1,
                    "formatter": 0,
                    "template": 0,
                    "legacy_package": 0,
                },
                "by_shape": {
                    "direct_assignment": 4,
                    "nested_attrset": 0,
                    "inherit": 0,
                    "merged_attrset": 0,
                    "dynamic": 0,
                    "helper_framework": 2,
                    "unknown": 0,
                },
            },
            dynamic_output_shapes={
                "total": 2,
                "by_pattern": {
                    "eachDefaultSystem": 1,
                    "genAttrs": 1,
                    "forAllSystems": 0,
                    "flake-utils": 0,
                    "flake-parts": 0,
                    "string_interpolation": 0,
                },
            },
            unsupported_flake_shapes={
                "total": 3,
                "by_pattern": {
                    "imported_outputs": 1,
                    "merged_attrset": 1,
                    "inherit_outputs": 0,
                    "nested_attrset_without_direct_identity": 1,
                    "template_section": 0,
                    "legacy_packages_section": 0,
                    "unknown_dynamic": 0,
                },
            },
            generic_config={
                "config_documents": 17,
                "config_paths": 153,
                "config_references": 21,
                "config_parse_errors": 2,
                "config_redactions": 0,
            },
            diagnostics={
                "missing_output_identity": 0,
                "dynamic_imports": 0,
                "unknown_imports": 0,
                "unknown_app_programs": 0,
                "raw_only_path_refs": 1,
                "flake_files_without_output_observations": 0,
            },
            limitations={
                "flake_inputs_not_extracted": False,
                "overlays_not_extracted": True,
                "modules_not_classified": True,
                "packages_are_static_attr_counts_only": True,
                "no_nix_eval": True,
                "no_flake_lock_resolution": True,
                "path_values_omitted": True,
                "weak_output_sections_are_not_concrete_outputs": True,
            },
            safety={
                "read_only": True,
                "no_execution": True,
                "no_nix_cli": True,
                "no_fetch": True,
                "no_flake_lock_resolution": True,
                "no_store_inspection": True,
                "no_path_values": True,
                "private_paths_redacted": True,
                "raw_profile_only": True,
            },
        )


McpServerRequests = McpServerRequestSupport

__all__ = [
    "McpServerRequestSupport",
    "McpServerRequests",
    "NixSummaryRecord",
]
