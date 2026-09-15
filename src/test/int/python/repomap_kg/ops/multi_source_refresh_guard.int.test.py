import json
from pathlib import Path

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.graph_file_sql import GraphFileFilters
from repomap_kg.ops.graph_files import query_graph_files
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _binding(alias: str, root: Path, *, privacy: str = "public-dev") -> str:
    return f"""
[[graphs.source_bindings]]
schema_version = 1
binding_id = "{graph_source_binding_id('fixture-graph', alias)}"
source_definition_id = "src1:{alias}"
alias = "{alias}"
revision = 1
kind = "folder"
root_path = "{root}"
repository_name = "fixture-{alias}"
logical_root = "."
privacy = "{privacy}"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"
input_name = "{alias}"
exclude_paths = ["result-*"]
"""


def _config(postgres, *bindings: str) -> str:
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"

[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_test"
{''.join(bindings)}

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _legacy_config(postgres, root: Path) -> str:
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"

[[graphs]]
id = "fixture-graph"
name = "Fixture Graph"
root_path = "{root}"
repository_name = "fixture-legacy"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_test"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""


def _refresh(config_path: Path, psql_command: str) -> tuple[int, str, str]:
    return run_repo_map_in_process(
        "ops", "refresh-graph", "--config", str(config_path),
        "--graph", "fixture-graph", "--psql-command", psql_command, "--json",
    )


def _counts(postgres) -> tuple[int, ...]:
    return tuple(
        int(postgres.psql_scalar(f"SELECT count(*) FROM {table};"))
        for table in ("runs", "files", "raw_observations", "canonical_nodes", "canonical_edges")
    )


def _latest_generations(postgres) -> tuple[str, str, str, str]:
    columns = (
        "source_generation", "config_generation",
        "extractor_generation", "canonicalizer_generation",
    )
    return tuple(
        postgres.psql_scalar(
            f"SELECT {column} FROM runs ORDER BY id DESC LIMIT 1;"
        )
        for column in columns
    )


def test_multi_source_stages_one_atomic_publication_and_source_qualified_readback(tmp_path):
    require_postgres_binaries()
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    for root in (entry, composition):
        (root / "modules").mkdir(parents=True)
        (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (entry / "flake.nix").write_text(
        "{ inputs, ... }: { imports = [ inputs.composition.nixosModules.default ]; }\n",
        encoding="utf-8",
    )
    (composition / "flake.nix").write_text(
        "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "repomap.toml"

    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        config_path.write_text(
            _config(postgres, _binding("entry", entry), _binding("composition", composition)),
            encoding="utf-8",
        )
        exit_code, stdout, stderr = _refresh(config_path, postgres.psql_command)
        first_counts = _counts(postgres)
        first_generations = _latest_generations(postgres)
        config = load_ops_config(config_path)
        page = query_graph_files(
            config, "fixture-graph", filters=GraphFileFilters(),
            psql_command=postgres.psql_command,
        )
        replay_code, replay_stdout, replay_stderr = _refresh(
            config_path, postgres.psql_command
        )
        replay_counts = _counts(postgres)
        replay_generations = _latest_generations(postgres)

        (composition / "flake.nix").unlink()
        (composition / "modules/default.nix").unlink()
        failed_code, failed_stdout, failed_stderr = _refresh(
            config_path, postgres.psql_command
        )
        failed_counts = _counts(postgres)

    assert exit_code == 0, stderr
    assert replay_code == 0, replay_stderr
    assert failed_code == 1
    assert '"result": "success"' in stdout
    assert {record.binding_alias for record in page.records} == {"entry", "composition"}
    assert all(record.snapshot_id and record.candidate_id for record in page.records)
    assert all(value.startswith(prefix) for value, prefix in zip(
        first_generations, ("sg1:", "cg1:", "eg1:", "kg1:"), strict=True
    ))
    assert replay_generations == first_generations
    assert first_counts[1] == replay_counts[1]
    assert first_counts[3:] == replay_counts[3:]
    assert failed_counts == replay_counts
    rendered = stdout + replay_stdout + failed_stdout + failed_stderr
    assert str(entry) not in rendered
    assert str(composition) not in rendered


def test_legacy_one_source_publication_and_readback_qualifies_keys_with_source_relative_path(tmp_path):
    require_postgres_binaries()
    root = tmp_path / "legacy"
    (root / "modules").mkdir(parents=True)
    (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    config_path = tmp_path / "repomap.toml"

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        config_path.write_text(_legacy_config(postgres, root), encoding="utf-8")
        exit_code, stdout, stderr = _refresh(config_path, postgres.psql_command)
        page = query_graph_files(
            load_ops_config(config_path),
            "fixture-graph",
            filters=GraphFileFilters(),
            psql_command=postgres.psql_command,
        )

    assert exit_code == 0, stderr
    record = next(item for item in page.records if item.path == "modules/default.nix")
    assert record.canonical_key == "file:root/modules/default.nix"
    assert record.path == "modules/default.nix"
    assert record.binding_alias == "root"
    assert record.binding_id == graph_source_binding_id("fixture-graph", "root")
    assert record.candidate_id is not None and record.candidate_id.startswith("cand1:")
    payload = json.loads(stdout)
    assert payload["config_path"] == str(config_path)
    assert payload["result"] == "success"
    assert len(payload["graphs"]) == 1
    graph_row = payload["graphs"][0]
    assert graph_row["graph_id"] == "fixture-graph"
    assert graph_row["repository_name"] == "fixture-legacy"
    assert graph_row["privacy"] == "public-dev"
    assert graph_row["root_path_display"] == str(root)
    assert graph_row["root_path_expanded"] == str(root)
