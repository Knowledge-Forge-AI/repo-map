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
    discovery_fixture,
)

from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    js_framework_summary_to_jsonable,
    query_js_framework_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


EXPECTED_FIELDS = tuple(
    "root_path repository_name framework_observations framework_profiles node "
    "express nest next jest jquery generic_js diagnostics safety".split()
)

COUNT_MAP_KEYS = {
    "framework_profiles": tuple("node express nest next jest jquery generic_js".split()),
    "node": tuple("entrypoints requires exports env_references".split()),
    "express": tuple(
        "apps routers routes middleware error_handlers dynamic_routes".split()
    ),
    "nest": tuple("modules controllers providers routes decorators".split()),
    "next": tuple("pages api_routes app_routes components route_handlers".split()),
    "jest": tuple("suites tests expectations mocks".split()),
    "jquery": tuple("selectors events ajax_references plugin_references".split()),
    "generic_js": tuple(
        "canonical_routes canonical_test_suites canonical_test_cases "
        "canonical_components".split()
    ),
    "diagnostics": tuple(
        "framework_observation_limit framework_selector_limit".split()
    ),
}

SAFETY_KEYS = tuple(
    "no_execution no_fetch raw_profile_only no_new_canonical_namespaces".split()
)
WRAPPER_FIELDS = set("server version read_only graph summary_kind summary safety".split())

FRAMEWORK_KINDS = tuple(
    "node.entrypoint node.require node.export express.app express.router "
    "express.route express.middleware express.error_handler nest.module "
    "nest.controller nest.provider nest.route nest.decorator next.route "
    "next.page next.api_route next.app_route next.component jest.suite "
    "jest.test jest.expectation jest.mock jquery.selector jquery.event "
    "jquery.ajax jquery.plugin_reference js.framework_reference".split()
)


def test_psycopg71_js_framework_summary_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    public_root = "/tmp/psycopg71-js-framework-public"
    private_root = "/Users/synthetic-private/psycopg71-js-framework"
    empty_root = "/tmp/psycopg71-js-framework-empty"
    missing_root = "/tmp/psycopg71-js-framework-missing"
    invalid_psql = "/bin/psql-not-used-by-psycopg71"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (
            PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD",
            "REPOMAP_OPS_CONFIG", "REPOMAP_PSQL_COMMAND",
        )
    }

    try:
        with _framework_fixture_jsonl() as fixture_path, temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_js")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            for path, root, name, target in (
                (fixture_path, public_root, "psycopg71-public", postgres),
                (fixture_path, private_root, "psycopg71-private", private_postgres),
                (
                    canonicalization_fixture("ruby_basic", "raw_observations.jsonl"),
                    empty_root,
                    "psycopg71-empty",
                    postgres,
                ),
            ):
                _load_fixture(path, root_path=root, repository_name=name, postgres=target)

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
                record = query_js_framework_summary(
                    postgres.psql_args,
                    root_path=public_root,
                    psql_command=psql_command,
                )
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = js_framework_summary_to_jsonable(record)

            expected = direct_payloads["connector-psql"]
            assert tuple(expected) == EXPECTED_FIELDS
            assert expected["root_path"] == public_root
            assert expected["repository_name"] == "psycopg71-public"
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            _assert_complete_nonempty_contract(expected)

            defaults = {}
            for root_path in (missing_root, empty_root):
                for mode, selector, connector, psql_command in modes[:2]:
                    _select_connector(selector, connector, postgres=postgres)
                    defaults[(root_path, mode)] = query_js_framework_summary(
                        postgres.psql_args,
                        root_path=root_path,
                        psql_command=psql_command,
                    ).to_dict()
                assert defaults[(root_path, "default")] == defaults[
                    (root_path, "connector-psql")
                ]
                _assert_complete_default(defaults[(root_path, "default")])
            assert defaults[(missing_root, "default")]["repository_name"] is None
            assert defaults[(empty_root, "default")]["repository_name"] == (
                "psycopg71-empty"
            )

            cli_args = _cli_connection_args(postgres, root_path=public_root)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(
                run_repo_map_in_process("storage", "js-framework-summary", *cli_args, "--psql-command", postgres.psql_command, "--json")
            )
            _select_connector(None, None, postgres=postgres)
            default_cli = _successful_json(
                run_repo_map_in_process("storage", "js-framework-summary", *cli_args, "--psql-command", invalid_psql, "--json")
            )
            assert default_cli == psql_cli == expected

            mcp_payloads = _mcp_payloads(
                postgres, public_root=public_root, private_root=private_root
            )
            for graph_id in ("public-js-framework", "private-js-framework"):
                assert mcp_payloads["default"][graph_id] == mcp_payloads["psql"][
                    graph_id
                ]
                wrapper = mcp_payloads["default"][graph_id]
                assert set(wrapper) == WRAPPER_FIELDS
                assert wrapper["read_only"] is True
                assert wrapper["summary_kind"] == "js_framework"
                assert wrapper["graph"]["graph_id"] == graph_id
                assert wrapper["graph"]["enabled"] is True
                assert wrapper["graph"]["mcp_visible"] is True
                _assert_nested_key_order(wrapper["summary"])
            public_wrapper = mcp_payloads["default"]["public-js-framework"]
            sanitized_expected = json.loads(json.dumps(expected))
            sanitized_expected["root_path"] = "[graph-root]"
            assert public_wrapper["summary"] == sanitized_expected
            assert public_wrapper["graph"]["root_path_display"] == "[graph-root]"
            private_wrapper = mcp_payloads["default"]["private-js-framework"]
            assert private_wrapper["summary"]["root_path"] == "[private-root]"
            for key in ("root_path_display", "root_path_expanded"):
                assert private_wrapper["graph"][key] == "[private-root]"
            assert private_wrapper["graph"]["private"] is True
            assert private_wrapper["graph"]["warnings"][0]["code"] == (
                "private-graph-visible"
            )

            serialized = json.dumps({
                "direct": direct_payloads, "jsonable": jsonable_payloads,
                "defaults": list(defaults.values()),
                "cli": {"default": default_cli, "psql": psql_cli}, "mcp": mcp_payloads,
            }, sort_keys=True)
            for forbidden in (
                private_root, "synthetic-private", "private-package@9.9.9",
                "/internal/private-route", "PrivateController", "PrivateModule",
                "PrivateProvider", "PrivateComponent", "privateHandler",
                "npm run private-build", "PRIVATE_SETTING=value",
                "src/private-internal.ts", "https://private.invalid/api",
                "private parser diagnostic", "private source snippet",
                "private_raw_expression", "credential-value", "secret-value",
                "token-value",
            ):
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


class _framework_fixture_jsonl:
    def __enter__(self) -> Path:
        fixture_root = discovery_fixture("js5_frameworks")
        paths = {
            "node": "src/server.ts", "express": "src/server.ts", "nest": "src/app.controller.ts",
            "next": "app/users/[id]/page.tsx", "jest": "src/math.test.ts",
            "jquery": "public/jquery-widget.js", "js": "src/server.ts",
        }
        assert all((fixture_root / path).is_file() for path in paths.values())
        sensitive_metadata: dict[str, object] = {
            "package": "private-package@9.9.9", "route": "/internal/private-route",
            "symbols": [
                "PrivateController", "PrivateModule", "PrivateProvider",
                "PrivateComponent", "privateHandler",
            ],
            "command": "npm run private-build", "setting": "PRIVATE_SETTING=value",
            "path": "src/private-internal.ts", "url": "https://private.invalid/api",
            "diagnostic": "private parser diagnostic", "snippet": "private source snippet",
            "expression": "private_raw_expression", "credential": "credential-value",
            "secret": "secret-value", "token": "token-value",
        }
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.path = Path(handle.name)
        with handle:
            for index, kind in enumerate(FRAMEWORK_KINDS):
                family = kind.split(".", 1)[0]
                metadata = dict(sensitive_metadata if index == 0 else {})
                if kind == "js.framework_reference":
                    metadata["reference_kind"] = "environment"
                if kind == "express.route":
                    metadata["dynamic"] = True
                observation = RawObservation(
                    kind=kind,
                    source_id=f"{paths[family]}#{kind}:{index}",
                    path=paths[family],
                    confidence="extracted",
                    extractor="psycopg71-fixture",
                    extractor_version="1",
                    name=f"synthetic-{index}",
                    metadata=metadata,
                )
                handle.write(observation.to_json_line())
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
    from repomap_kg.server.mcp import repomap_js_framework_summary

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "psycopg71.local.toml"
        config_path.write_text(
            _ops_config(postgres, public_root=public_root, private_root=private_root),
            encoding="utf-8",
        )
        payloads = {}
        os.environ["REPOMAP_OPS_CONFIG"] = str(config_path)
        for mode, selector, connector, psql_command in (
            ("psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
            ("default", None, None, str(Path(tmpdir) / "missing" / "psql")),
        ):
            _select_connector(selector, connector, postgres=postgres)
            os.environ["REPOMAP_PSQL_COMMAND"] = psql_command
            payloads[mode] = {
                graph_id: repomap_js_framework_summary(graph_id=graph_id)
                for graph_id in ("public-js-framework", "private-js-framework")
            }
        return payloads


def _ops_config(postgres, *, public_root: str, private_root: str) -> str:
    return (
        'schema_version = 1\n\n[service]\nmode = "local"\n'
        'mcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\n'
        f'database = "repomap_test"\nuser = "{postgres.user}"\n'
        'password_env = "REPOMAP_PG_PASSWORD"\n\n'
        '[[graphs]]\nid = "public-js-framework"\n'
        f'name = "Public JavaScript Framework"\nroot_path = "{public_root}"\n'
        'repository_name = "psycopg71-public"\nprivacy = "public-dev"\n'
        'enabled = true\nmcp_visible = true\nextractor_profile = "default"\n'
        'refresh_policy = "manual"\n\n[[graphs]]\nid = "private-js-framework"\n'
        f'name = "Private JavaScript Framework"\nroot_path = "{private_root}"\n'
        'repository_name = "psycopg71-private"\nprivacy = "private-ops"\ndatabase = "repomap_test_private_js"\n'
        'enabled = true\nmcp_visible = true\nextractor_profile = "private"\nrefresh_policy = "manual"\n\n'
        '[server_memory]\nenabled = false\npath = "~/.codex/codex-vc/mcp/server-memory"\nmode = "read_only"\n'
    )


def _assert_complete_nonempty_contract(payload: dict[str, object]) -> None:
    assert payload["framework_observations"] == len(FRAMEWORK_KINDS)
    profiles = payload["framework_profiles"]
    assert isinstance(profiles, dict)
    assert all(isinstance(profiles[p], int) and profiles[p] > 0 for p in COUNT_MAP_KEYS["framework_profiles"])
    total_len = 0
    for name in COUNT_MAP_KEYS:
        val = payload[name]
        assert isinstance(val, (dict, list))
        total_len += len(val)
    assert total_len == 41
    safety = payload["safety"]
    assert isinstance(safety, dict) and tuple(safety) == SAFETY_KEYS and all(bool(v) for v in safety.values())


def _assert_complete_default(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert payload["framework_observations"] == 0
    _assert_nested_key_order(payload)
    for name in COUNT_MAP_KEYS:
        val_map = payload[name]
        assert isinstance(val_map, dict) and all(value == 0 for value in val_map.values())
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_nested_key_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    for name, required_keys in COUNT_MAP_KEYS.items():
        val = payload[name]
        assert isinstance(val, dict) and tuple(val) == required_keys
    safety = payload["safety"]
    assert isinstance(safety, dict) and tuple(safety) == SAFETY_KEYS


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


def _successful_json(result: tuple[int, str, str]) -> dict[str, object]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
