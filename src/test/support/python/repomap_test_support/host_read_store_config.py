"""Setup-owned home fixtures and no-fallback guards for MCP read-store tests.

Shared by the canonical (READSTORE1) and investigation (READSTORE2) read-store
unit owners. Fixtures are synthetic and public-safe; no database is started.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

# Guards that a host-only read must never reach: container fallback planning,
# lifecycle/refresh/publication entrypoints, and process or tool discovery.
NO_FALLBACK_GUARDS = (
    "common_lore_index.ops.readback._resolve_container_readback_plan",
    "common_lore_index.ops.readback._runtime_plan",
    "common_lore_index.ops.refresh._container_psql_execution",
    "common_lore_index.runtime.local.inspect_container",
    "common_lore_index.ops.refresh.refresh_graph",
    "common_lore_index.ops.direct_publication.publish_observation_generation",
    "common_lore_index.graph.multi_source_pipeline.capture_multi_source_candidate",
    "shutil.which",
    "subprocess.run",
    "subprocess.Popen",
)


# RESOLVE1: everything that makes a configured read PostgreSQL-specific. A
# neutral selection routed to injected fake stores must reach none of these
# once the (still PostgreSQL-coupled) config parse has returned: database-name
# derivation, psql argument construction, the PostgreSQL context, psql command
# selection, readback authority and secret readers, and the JSON drivers.
PG_BINDING_TRIPWIRES = (
    "common_lore_index.ops.resolved_config.resolve_ops_config",
    "common_lore_index.ops.config_status.resolve_ops_config",
    "common_lore_index.ops.config_loading.resolve_ops_config",
    "common_lore_index.ops.config.resolve_ops_config",
    "common_lore_index.ops.config_status.graph_database",
    "common_lore_index.ops.config.graph_database",
    "common_lore_index.server._ops_records.graph_database",
    "common_lore_index.server.ops.graph_database",
    "common_lore_index.server.postgres_read_binding.graph_database",
    "common_lore_index.ops.config_records.OpsPostgresConfig.psql_args_for_database",
    "common_lore_index.server._ops_records.McpOpsGraphContext.__init__",
    "common_lore_index.server._ops_records.psql_command_from_environment",
    "common_lore_index.server.postgres_read_binding.psql_command_from_environment",
    "common_lore_index.server.canonical_read_store.readback_postgres_authority",
    "common_lore_index.ops.readback.readback_postgres_authority",
    "common_lore_index.runtime.postgres_route.readback_postgres_authority",
    "common_lore_index.runtime.postgres_route.read_read_status_password",
    "common_lore_index.runtime.postgres_route.read_configured_postgres_password",
    "common_lore_index.runtime.database_role_contract.read_read_status_password",
    "common_lore_index.runtime.database_role_contract.read_configured_postgres_password",
    "common_lore_index.ops.readback.execute_json_readback_with_driver",
    "common_lore_index.storage.readback_driver.execute_json_readback_with_driver",
    "common_lore_index.storage.readback_driver.run_psql",
    "common_lore_index.storage.readback_driver._import_psycopg",
    *NO_FALLBACK_GUARDS,
)
# A psql command that the PostgreSQL binding refuses if it ever reads it.
INVALID_PSQL_COMMAND = "not a psql"


def fail_if_reached(*_args, **_kwargs):
    raise AssertionError("lifecycle, container, or subprocess path was reached")


class FailingStoreBinding:
    """Configured-graph binding double whose stores must never be reached.

    Construction and ``storage_label`` are harmless, matching the production
    bindings, which perform no IO until a store operation runs.
    """

    def storage_label(self, _selection: Any) -> str:
        return "unused-storage"

    def investigation_store(self) -> Any:
        return fail_if_reached()

    def canonical_store(self, _selection: Any) -> Any:
        return fail_if_reached()

    def source_store(self, _selection: Any) -> Any:
        return fail_if_reached()


def failing_store_binding(_config: Any) -> FailingStoreBinding:
    return FailingStoreBinding()


def patched_guards(targets: tuple[str, ...] = NO_FALLBACK_GUARDS) -> ExitStack:
    stack = ExitStack()
    for target in targets:
        stack.enter_context(patch(target, fail_if_reached))
    return stack


def setup_owned_home(test_case: unittest.TestCase, config: str | None = None) -> Path:
    """Create a setup-owned home whose config is ``setup_owned_config()``."""
    from common_lore_index.runtime.local import setup_local_runtime

    tmpdir = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmpdir.cleanup)
    home = Path(tmpdir.name) / "home"
    setup_local_runtime(home)
    (home / "repomap.rpl.toml").write_text(
        setup_owned_config() if config is None else config, encoding="utf-8"
    )
    return home


def setup_owned_config() -> str:
    return """schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[runtime]
container_runtime = "docker"
server_host_port = 55880
bind_host = "127.0.0.1"
[runtime.postgres]
direct_host_port_enabled = true
host_port = 55439
bind_host = "127.0.0.1"
[postgres]
host = "postgres"
port = 5432
database = "repomap"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "host-one"
name = "Host One"
root_path = "/public/host-one"
repository_name = "host-one"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_host_one"
[[graphs]]
id = "host-multi"
name = "Host Multi"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_host_multi"
[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:alpha"
alias = "alpha"
revision = 1
kind = "folder"
root_path = "./alpha"
repository_name = "alpha"
logical_root = "alpha"
privacy = "public-dev"
evidence_retention = "inherit"
extractor_profile = "default"
resolution_policy = "isolated"
role = "source"
enabled = true
[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
"""
