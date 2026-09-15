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
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    python_summary_to_jsonable,
    query_python_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

from src.test.int.python.repomap_kg.storage.python_summary_readback_contracts import (
    WRAPPER_FIELDS,
    _assert_meaningful_contract,
    _assert_nested_key_order,
    _assert_python_empty,
    _assert_unknown_root,
    _private_markers,
    _successful_json,
)
from src.test.int.python.repomap_kg.storage.python_summary_readback_fixtures import (
    _assert_fixture_anchors,
    _cli_connection_args,
    _fixture_jsonl,
    _insert_python_empty_canonical_nodes,
    _load_fixture,
    _python_empty_observations,
    _python_observations,
)

def test_psycopg80_python_summary_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    _assert_fixture_anchors()
    public_root = "/tmp/psycopg80-python-public"
    private_root = "/Users/synthetic-private/psycopg80-python"
    empty_root = "/tmp/psycopg80-python-empty"
    missing_root = "/tmp/psycopg80-python-missing"
    invalid_psql = "/tmp/psycopg80-missing/psql"
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
            _fixture_jsonl(_python_observations()) as python_fixture,
            _fixture_jsonl(_python_empty_observations()) as empty_fixture,
            temporary_postgres() as postgres,
        ):
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_python")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            for path, root, name, target in (
                (python_fixture, public_root, "psycopg80-public", postgres),
                (python_fixture, private_root, "psycopg80-private", private_postgres),
                (empty_fixture, empty_root, "psycopg80-empty", postgres),
            ):
                _load_fixture(
                    path,
                    root_path=root,
                    repository_name=name,
                    postgres=target,
                )
            _insert_python_empty_canonical_nodes(postgres, root_path=empty_root)

            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
                ("connector-psycopg", PG_CONNECTOR_ENV, "psycopg", invalid_psql),
                ("driver-psql", READBACK_DRIVER_ENV, "psql", postgres.psql_command),
                ("driver-psycopg", READBACK_DRIVER_ENV, "psycopg", invalid_psql),
            )
            direct_payloads = {}
            jsonable_payloads = {}
            for mode, selector, connector, psql_command in modes:
                _select_connector(selector, connector, postgres=postgres)
                record = query_python_summary(
                    postgres.psql_args,
                    root_path=public_root,
                    psql_command=psql_command,
                )
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = python_summary_to_jsonable(record)
            expected = direct_payloads["connector-psql"]
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            _assert_nested_key_order(expected)
            _assert_meaningful_contract(expected)

            defaults = {}
            for root_path in (missing_root, empty_root):
                for mode, selector, connector, psql_command in modes[:2]:
                    _select_connector(selector, connector, postgres=postgres)
                    record = query_python_summary(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=psql_command,
                    )
                    defaults[(root_path, mode)] = record.to_dict()
                    assert python_summary_to_jsonable(record) == record.to_dict()
                assert defaults[(root_path, "default")] == defaults[
                    (root_path, "connector-psql")
                ]
                _assert_nested_key_order(defaults[(root_path, "default")])
            _assert_unknown_root(defaults[(missing_root, "default")])
            _assert_python_empty(defaults[(empty_root, "default")])

            cli_args = _cli_connection_args(postgres, root_path=public_root)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "python-summary",
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
                    "python-summary",
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
            for graph_id in ("public-python", "private-python"):
                assert mcp_payloads["default"][graph_id] == (
                    mcp_payloads["psql"][graph_id]
                )
                wrapper = mcp_payloads["default"][graph_id]
                assert set(wrapper) == WRAPPER_FIELDS
                assert wrapper["read_only"] is True
                assert wrapper["summary_kind"] == "python"
                assert wrapper["graph"]["graph_id"] == graph_id
                assert wrapper["graph"]["enabled"] is True
                assert wrapper["graph"]["mcp_visible"] is True
                _assert_nested_key_order(wrapper["summary"])
            public_wrapper = mcp_payloads["default"]["public-python"]
            sanitized_expected = json.loads(json.dumps(expected))
            sanitized_expected["root_path"] = "[graph-root]"
            sanitized_expected["redactions"]["credentialed_urls"] = "[REDACTED]"
            sanitized_expected["redactions"]["secret_like_config"] = "[REDACTED]"
            assert public_wrapper["summary"] == sanitized_expected
            assert public_wrapper["summary"]["redactions"]["private_indexes"] == 1
            assert public_wrapper["summary"]["redactions"]["framework_settings"] == 1
            assert public_wrapper["graph"]["root_path_display"] == "[graph-root]"
            private_wrapper = mcp_payloads["default"]["private-python"]
            assert private_wrapper["summary"]["root_path"] == "[private-root]"
            for key in ("root_path_display", "root_path_expanded"):
                assert private_wrapper["graph"][key] == "[private-root]"
            assert private_wrapper["graph"]["private"] is True
            assert private_wrapper["graph"]["warnings"][0]["code"] == (
                "private-graph-visible"
            )

            serialized = json.dumps(
                {
                    "direct": direct_payloads,
                    "jsonable": jsonable_payloads,
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
    from repomap_kg.server.mcp import repomap_python_summary

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "psycopg80.local.toml"
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
                graph_id: repomap_python_summary(graph_id=graph_id)
                for graph_id in ("public-python", "private-python")
            }
        return payloads


def _ops_config(postgres, *, public_root: str, private_root: str) -> str:
    return (
        'schema_version = 1\n\n[service]\nmode = "local"\n'
        'mcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\n'
        f'database = "repomap_test"\nuser = "{postgres.user}"\n'
        'password_env = "REPOMAP_PG_PASSWORD"\n\n'
        '[[graphs]]\nid = "public-python"\nname = "Public Python"\n'
        f'root_path = "{public_root}"\nrepository_name = "psycopg80-public"\n'
        'privacy = "public-dev"\nenabled = true\nmcp_visible = true\n'
        'extractor_profile = "default"\nrefresh_policy = "manual"\n\n'
        '[[graphs]]\nid = "private-python"\nname = "Private Python"\n'
        f'root_path = "{private_root}"\nrepository_name = "psycopg80-private"\n'
        'database = "repomap_test_private_python"\n'
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
