from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_terraform_summary,
    terraform_summary_to_jsonable,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

from src.test.int.python.repomap_kg.storage.terraform_summary_readback_contracts import (
    WRAPPER_FIELDS,
    _assert_meaningful_hcl_contract,
    _assert_meaningful_tfjson_contract,
    _assert_nested_key_order,
    _assert_terraform_empty,
    _assert_unknown_root,
    _private_markers,
    _successful_json,
)
from src.test.int.python.repomap_kg.storage.terraform_summary_readback_fixtures import (
    _cli_connection_args,
    _empty_fixture_jsonl,
    _fixture_jsonl,
    _load_fixture,
)

def test_psycopg77_terraform_summary_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    public_root = "/tmp/psycopg77-terraform-public"
    tfjson_root = "/tmp/psycopg77-terraform-tfjson"
    private_root = "/Users/synthetic-private/psycopg77-terraform"
    empty_root = "/tmp/psycopg77-terraform-empty"
    missing_root = "/tmp/psycopg77-terraform-missing"
    invalid_psql = "/tmp/psycopg77-missing/psql"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (
            PG_CONNECTOR_ENV,
            READBACK_DRIVER_ENV,
            "PGPASSWORD",
            "REPOMAP_OPS_CONFIG",
            "REPOMAP_PSQL_COMMAND",
        )
    }

    try:
        with (
            _fixture_jsonl("hcl") as hcl_fixture,
            _fixture_jsonl("tfjson") as tfjson_fixture,
            _empty_fixture_jsonl() as empty_fixture,
            temporary_postgres() as postgres,
        ):
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_terraform")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            for path, root, name, target in (
                (hcl_fixture, public_root, "psycopg77-public", postgres),
                (hcl_fixture, private_root, "psycopg77-private", private_postgres),
                (tfjson_fixture, tfjson_root, "psycopg77-tfjson", postgres),
                (empty_fixture, empty_root, "psycopg77-empty", postgres),
            ):
                _load_fixture(
                    path,
                    root_path=root,
                    repository_name=name,
                    postgres=target,
                )
            config_fixture = canonicalization_fixture(
                "yaml_basic", "raw_observations.jsonl"
            )
            for root, name, target in (
                (public_root, "psycopg77-public", postgres),
                (private_root, "psycopg77-private", private_postgres),
                (tfjson_root, "psycopg77-tfjson", postgres),
                (empty_root, "psycopg77-empty", postgres),
            ):
                _load_fixture(
                    config_fixture,
                    root_path=root,
                    repository_name=name,
                    postgres=target,
                )

            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
                ("connector-psycopg", PG_CONNECTOR_ENV, "psycopg", invalid_psql),
                ("driver-psql", READBACK_DRIVER_ENV, "psql", postgres.psql_command),
                ("driver-psycopg", READBACK_DRIVER_ENV, "psycopg", invalid_psql),
            )
            direct_payloads = {}
            jsonable_payloads = {}
            for root_path in (public_root, tfjson_root):
                for mode, selector, connector, psql_command in modes:
                    _select_connector(selector, connector, postgres=postgres)
                    record = query_terraform_summary(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=psql_command,
                    )
                    direct_payloads[(root_path, mode)] = record.to_dict()
                    jsonable_payloads[(root_path, mode)] = (
                        terraform_summary_to_jsonable(record)
                    )
                expected = direct_payloads[(root_path, "connector-psql")]
                assert all(
                    direct_payloads[(root_path, mode)] == expected
                    for mode, *_rest in modes
                )
                assert all(
                    jsonable_payloads[(root_path, mode)] == expected
                    for mode, *_rest in modes
                )
                _assert_nested_key_order(expected)
            public_expected = direct_payloads[(public_root, "connector-psql")]
            tfjson_expected = direct_payloads[(tfjson_root, "connector-psql")]
            _assert_meaningful_hcl_contract(public_expected)
            _assert_meaningful_tfjson_contract(tfjson_expected)

            defaults = {}
            for root_path in (missing_root, empty_root):
                for mode, selector, connector, psql_command in modes[:2]:
                    _select_connector(selector, connector, postgres=postgres)
                    defaults[(root_path, mode)] = query_terraform_summary(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=psql_command,
                    ).to_dict()
                assert defaults[(root_path, "default")] == defaults[
                    (root_path, "connector-psql")
                ]
                _assert_nested_key_order(defaults[(root_path, "default")])
            _assert_unknown_root(defaults[(missing_root, "default")])
            _assert_terraform_empty(defaults[(empty_root, "default")])

            cli_args = _cli_connection_args(postgres, root_path=public_root)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "terraform-summary",
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
                    "terraform-summary",
                    *cli_args,
                    "--psql-command",
                    invalid_psql,
                    "--json",
                )
            )
            assert default_cli == psql_cli == public_expected

            mcp_payloads = _mcp_payloads(
                postgres,
                public_root=public_root,
                private_root=private_root,
            )
            for graph_id in ("public-terraform", "private-terraform"):
                assert mcp_payloads["default"][graph_id] == (
                    mcp_payloads["psql"][graph_id]
                )
                wrapper = mcp_payloads["default"][graph_id]
                assert set(wrapper) == WRAPPER_FIELDS
                assert wrapper["read_only"] is True
                assert wrapper["summary_kind"] == "terraform"
                assert wrapper["graph"]["graph_id"] == graph_id
                assert wrapper["graph"]["enabled"] is True
                assert wrapper["graph"]["mcp_visible"] is True
                _assert_nested_key_order(wrapper["summary"])
            public_wrapper = mcp_payloads["default"]["public-terraform"]
            sanitized_expected = json.loads(json.dumps(public_expected))
            sanitized_expected["root_path"] = "[graph-root]"
            sanitized_expected["redactions"]["secret_like_fields"] = "[REDACTED]"
            sanitized_expected["redactions"]["credentialed_urls"] = "[REDACTED]"
            assert public_wrapper["summary"] == sanitized_expected
            assert public_wrapper["graph"]["root_path_display"] == "[graph-root]"
            private_wrapper = mcp_payloads["default"]["private-terraform"]
            assert private_wrapper["summary"]["root_path"] == "[private-root]"
            for key in ("root_path_display", "root_path_expanded"):
                assert private_wrapper["graph"][key] == "[private-root]"
            assert private_wrapper["graph"]["private"] is True
            assert private_wrapper["graph"]["warnings"][0]["code"] == (
                "private-graph-visible"
            )

            serialized = json.dumps(
                {
                    "direct": list(direct_payloads.values()),
                    "jsonable": list(jsonable_payloads.values()),
                    "defaults": list(defaults.values()),
                    "cli": {"default": default_cli, "psql": psql_cli},
                    "mcp": mcp_payloads,
                },
                sort_keys=True,
            )
            for forbidden in _private_markers(private_root):
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


def _mcp_payloads(postgres, *, public_root: str, private_root: str):
    from repomap_kg.server.mcp import repomap_terraform_summary

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "psycopg77.local.toml"
        config_path.write_text(
            _ops_config(postgres, public_root=public_root, private_root=private_root),
            encoding="utf-8",
        )
        os.environ["REPOMAP_OPS_CONFIG"] = str(config_path)
        payloads = {}
        for mode, selector, connector, psql_command in (
            ("psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
            ("default", None, None, str(Path(tmpdir) / "missing" / "psql")),
        ):
            _select_connector(selector, connector, postgres=postgres)
            os.environ["REPOMAP_PSQL_COMMAND"] = psql_command
            payloads[mode] = {
                graph_id: repomap_terraform_summary(graph_id=graph_id)
                for graph_id in ("public-terraform", "private-terraform")
            }
        return payloads


def _ops_config(postgres, *, public_root: str, private_root: str) -> str:
    return (
        'schema_version = 1\n\n[service]\nmode = "local"\n'
        'mcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\n'
        f'database = "repomap_test"\nuser = "{postgres.user}"\n'
        'password_env = "REPOMAP_PG_PASSWORD"\n\n'
        '[[graphs]]\nid = "public-terraform"\nname = "Public Terraform"\n'
        f'root_path = "{public_root}"\nrepository_name = "psycopg77-public"\n'
        'privacy = "public-dev"\nenabled = true\nmcp_visible = true\n'
        'extractor_profile = "default"\nrefresh_policy = "manual"\n\n'
        '[[graphs]]\nid = "private-terraform"\nname = "Private Terraform"\n'
        f'root_path = "{private_root}"\nrepository_name = "psycopg77-private"\n'
        'database = "repomap_test_private_terraform"\n'
        'privacy = "private-ops"\nenabled = true\nmcp_visible = true\n'
        'extractor_profile = "private"\nrefresh_policy = "manual"\n\n'
        '[server_memory]\nenabled = false\n'
        'path = "~/.codex/codex-vc/mcp/server-memory"\nmode = "read_only"\n'
    )


def _select_connector(
    selector: str | None,
    connector: str | None,
    *,
    postgres,
) -> None:
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


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
