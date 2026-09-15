from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import canonicalization_fixture

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    nix_summary_to_jsonable,
    query_nix_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "nix_observations",
    "nix_files",
    "flake_files",
    "raw",
    "canonical",
    "edges",
    "programs",
    "paths",
    "flake_inputs",
    "output_sections",
    "dynamic_output_shapes",
    "unsupported_flake_shapes",
    "generic_config",
    "diagnostics",
    "limitations",
    "safety",
)


def test_psycopg62_nix_summary_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    public_root = "/tmp/psycopg62-nix-public"
    private_root = "/Users/synthetic-local-user/psycopg62-nix-private"
    invalid_psql = "/bin/psql-not-used-by-psycopg62"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD")
    }

    try:
        with _loadable_fixture() as fixture_path, temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_nix")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            _load_fixture(
                fixture_path,
                root_path=public_root,
                repository_name="psycopg62-public",
                postgres=postgres,
            )
            _load_fixture(
                fixture_path,
                root_path=private_root,
                repository_name="psycopg62-private",
                postgres=private_postgres,
            )

            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
                ("connector-psycopg", PG_CONNECTOR_ENV, "psycopg", invalid_psql),
                ("driver-psql", READBACK_DRIVER_ENV, "psql", postgres.psql_command),
                ("driver-psycopg", READBACK_DRIVER_ENV, "psycopg", invalid_psql),
            )
            direct_payloads: dict[str, dict[str, object]] = {}
            jsonable_payloads: dict[str, dict[str, object]] = {}
            for mode, selector, connector, psql_command in modes:
                _select_connector(selector, connector, postgres=postgres)
                record = query_nix_summary(
                    postgres.psql_args,
                    root_path=public_root,
                    psql_command=psql_command,
                )
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = nix_summary_to_jsonable(record)

            expected = direct_payloads["connector-psql"]
            assert expected["root_path"] == "[root-path]"
            assert expected["repository_name"] == "psycopg62-public"
            assert tuple(expected) == EXPECTED_FIELDS
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            _assert_nested_contract(expected)

            missing_payloads = {}
            for mode, selector, connector, psql_command in modes[:2]:
                _select_connector(selector, connector, postgres=postgres)
                missing_payloads[mode] = query_nix_summary(
                    postgres.psql_args,
                    root_path="/tmp/psycopg62-missing",
                    psql_command=psql_command,
                ).to_dict()
            assert missing_payloads["default"] == missing_payloads["connector-psql"]
            assert missing_payloads["default"]["repository_name"] is None
            assert missing_payloads["default"]["nix_observations"] == 0
            assert tuple(missing_payloads["default"]) == EXPECTED_FIELDS

            cli_args = _cli_connection_args(postgres, root_path=public_root)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "nix-summary",
                    *cli_args,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )
            _select_connector(None, None, postgres=postgres)
            default_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "nix-summary",
                    *cli_args,
                    "--psql-command",
                    invalid_psql,
                    "--json",
                )
            )
            assert default_cli == psql_cli == expected

            mcp_payloads = _mcp_payloads(
                postgres,
                public_root=public_root,
                private_root=private_root,
            )
            for graph_id in ("public-nix", "private-nix"):
                assert mcp_payloads["default"][graph_id] == mcp_payloads["psql"][graph_id]
                wrapper = mcp_payloads["default"][graph_id]
                assert wrapper["summary_kind"] == "nix"
                assert wrapper["read_only"] is True
                assert tuple(wrapper["summary"]) == EXPECTED_FIELDS
            assert mcp_payloads["default"]["public-nix"]["summary"]["root_path"] == (
                "[graph-root]"
            )
            private_wrapper = mcp_payloads["default"]["private-nix"]
            assert private_wrapper["summary"]["root_path"] == "[private-root]"
            assert private_wrapper["graph"]["root_path_display"] == "[private-root]"
            assert private_wrapper["graph"]["root_path_expanded"] == "[private-root]"

            serialized = json.dumps(
                {
                    "direct": direct_payloads,
                    "missing": missing_payloads,
                    "cli": default_cli,
                    "public_mcp_summaries": {
                        mode: payloads["public-nix"]["summary"]
                        for mode, payloads in mcp_payloads.items()
                    },
                    "private_mcp": {
                        mode: payloads["private-nix"]
                        for mode, payloads in mcp_payloads.items()
                    },
                },
                sort_keys=True,
            )
            for forbidden in (
                public_root,
                private_root,
                "synthetic-local-user",
                "flake.nix",
                "modules/base.nix",
                "bin/tool",
                "raw_expression",
                "source_snippet",
                "github:",
                "https://",
                "nix build",
                "REPOMAP_PASSWORD",
                "TOKEN",
                "SECRET",
            ):
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


class _loadable_fixture:
    def __enter__(self) -> Path:
        fixture = canonicalization_fixture(
            "nix_flake_basic",
            "raw_observations.jsonl",
        )
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.path = Path(handle.name)
        with handle:
            for line in fixture.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                metadata = record.get("metadata")
                if (
                    record.get("kind") == "file"
                    and isinstance(metadata, dict)
                    and metadata.get("role") == "configuration"
                ):
                    metadata["role"] = "config"
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return self.path

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.path.unlink(missing_ok=True)


def _load_fixture(fixture_path: Path, *, root_path: str, repository_name: str, postgres) -> None:
    result = run_repo_map_in_process(
        "storage",
        "load-files",
        str(fixture_path),
        "--repository-name",
        repository_name,
        *_cli_connection_args(postgres, root_path=root_path),
        "--psql-command",
        postgres.psql_command,
        "--json",
    )
    exit_code, _stdout, stderr = result
    assert exit_code == 0, stderr


def _cli_connection_args(postgres, *, root_path: str) -> tuple[str, ...]:
    return (
        "--root-path",
        root_path,
        "--pg-host",
        str(postgres.socket_dir),
        "--pg-port",
        str(postgres.port),
        "--pg-user",
        postgres.user,
        "--pg-database",
        postgres.database,
    )


def _mcp_payloads(postgres, *, public_root: str, private_root: str):
    from repomap_kg.server.mcp import repomap_nix_summary

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "psycopg62.local.toml"
        config_path.write_text(
            _ops_config(postgres, public_root=public_root, private_root=private_root),
            encoding="utf-8",
        )
        payloads = {}
        with patch.dict(
            os.environ,
            {
                "REPOMAP_OPS_CONFIG": str(config_path),
                "REPOMAP_PSQL_COMMAND": postgres.psql_command,
            },
            clear=False,
        ):
            for mode, selector, connector in (
                ("default", None, None),
                ("psql", PG_CONNECTOR_ENV, "psql"),
            ):
                _select_connector(selector, connector, postgres=postgres)
                payloads[mode] = {
                    graph_id: repomap_nix_summary(graph_id=graph_id)
                    for graph_id in ("public-nix", "private-nix")
                }
        return payloads


def _ops_config(postgres, *, public_root: str, private_root: str) -> str:
    return f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "public-nix"
name = "Public Nix"
root_path = "{public_root}"
repository_name = "psycopg62-public"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "private-nix"
name = "Private Nix"
root_path = "{private_root}"
repository_name = "psycopg62-private"
database = "repomap_test_private_nix"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
'''


def _assert_nested_contract(payload: dict[str, object]) -> None:
    for key in (
        "raw",
        "canonical",
        "edges",
        "programs",
        "paths",
        "flake_inputs",
        "output_sections",
        "dynamic_output_shapes",
        "unsupported_flake_shapes",
        "generic_config",
        "diagnostics",
        "limitations",
        "safety",
    ):
        assert payload[key]
    limitations = payload["limitations"]
    safety = payload["safety"]
    assert isinstance(limitations, dict)
    assert isinstance(safety, dict)
    assert limitations["no_nix_eval"] is True
    assert safety["no_execution"] is True
    assert safety["private_paths_redacted"] is True


def _select_connector(selector: str | None, connector: str | None, *, postgres) -> None:
    os.environ.pop(PG_CONNECTOR_ENV, None)
    os.environ.pop(READBACK_DRIVER_ENV, None)
    if selector is not None:
        assert connector is not None
        os.environ[selector] = connector
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password


def _successful_json(result: tuple[int, str, str]):
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    return json.loads(stdout)


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
