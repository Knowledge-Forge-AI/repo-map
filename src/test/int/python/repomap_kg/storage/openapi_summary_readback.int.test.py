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
    openapi_fixture,
)

from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    openapi_summary_to_jsonable,
    query_openapi_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


EXPECTED_FIELDS = tuple("root_path repository_name openapi_observations "
    "openapi_documents spec_families openapi methods references redactions "
    "diagnostics generic_config safety".split())
COUNT_MAP_KEYS = {
    "spec_families": ("openapi3", "swagger2"),
    "openapi": tuple("info servers paths operations parameters request_bodies "
        "responses schemas components security_schemes tags examples".split()),
    "methods": tuple("GET POST PUT PATCH DELETE OPTIONS HEAD TRACE".split()),
    "references": tuple("internal_refs local_file_refs remote_refs_not_fetched "
        "external_docs_not_fetched refs_not_fetched".split()),
    "redactions": tuple("credentialed_urls openapi_ref_summaries text_summaries "
        "example_summaries secret_prone_fields".split()),
    "diagnostics": tuple("parse_errors unsupported_specs limit_overflows "
        "local_ref_errors malformed_specs".split()),
    "generic_config": tuple("config_documents config_paths config_references "
        "config_parse_errors".split()),
}
SAFETY_KEYS = tuple("no_fetch no_api_calls no_tool_execution raw_profile_only "
    "no_new_canonical_namespaces".split())
WRAPPER_FIELDS = set("server version read_only graph summary_kind summary safety".split())


def test_psycopg74_openapi_summary_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    public_root = "/tmp/psycopg74-openapi-public"
    private_root = "/Users/synthetic-private/psycopg74-openapi"
    empty_root = "/tmp/psycopg74-openapi-empty"
    missing_root = "/tmp/psycopg74-openapi-missing"
    invalid_psql = "/bin/psql-not-used-by-psycopg74"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD",
                     "REPOMAP_OPS_CONFIG", "REPOMAP_PSQL_COMMAND")
    }

    try:
        with _openapi_fixture_jsonl() as fixture_path, temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            private_postgres = postgres.create_database("repomap_test_private_openapi")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            for path, root, name, target in (
                (fixture_path, public_root, "psycopg74-public", postgres),
                (fixture_path, private_root, "psycopg74-private", private_postgres),
            ):
                _load_fixture(path, root_path=root, repository_name=name,
                              postgres=target)
            config_fixture = canonicalization_fixture("yaml_basic",
                                                      "raw_observations.jsonl")
            for root, name, target in (
                (public_root, "psycopg74-public", postgres),
                (private_root, "psycopg74-private", private_postgres),
                (empty_root, "psycopg74-empty", postgres),
            ):
                _load_fixture(config_fixture, root_path=root, repository_name=name,
                              postgres=target)

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
                record = query_openapi_summary(postgres.psql_args,
                    root_path=public_root, psql_command=psql_command)
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = openapi_summary_to_jsonable(record)

            expected = direct_payloads["connector-psql"]
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            _assert_complete_nonempty_contract(expected)

            defaults = {}
            for root_path in (missing_root, empty_root):
                for mode, selector, connector, psql_command in modes[:2]:
                    _select_connector(selector, connector, postgres=postgres)
                    defaults[(root_path, mode)] = query_openapi_summary(
                        postgres.psql_args, root_path=root_path,
                        psql_command=psql_command).to_dict()
                assert defaults[(root_path, "default")] == defaults[
                    (root_path, "connector-psql")
                ]
                _assert_nested_key_order(defaults[(root_path, "default")])
            _assert_unknown_root(defaults[(missing_root, "default")])
            _assert_openapi_empty(defaults[(empty_root, "default")])
            cli_args = _cli_connection_args(postgres, root_path=public_root)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(run_repo_map_in_process(
                "storage", "openapi-summary", *cli_args, "--psql-command", postgres.psql_command, "--json",
            ))
            _select_connector(None, None, postgres=postgres)
            default_cli = _successful_json(run_repo_map_in_process(
                "storage", "openapi-summary", *cli_args, "--psql-command", invalid_psql, "--json",
            ))
            assert default_cli == psql_cli == expected

            mcp_payloads = _mcp_payloads(postgres, public_root=public_root,
                                         private_root=private_root)
            for graph_id in ("public-openapi", "private-openapi"):
                assert mcp_payloads["default"][graph_id] == (
                    mcp_payloads["psql"][graph_id])
                wrapper = mcp_payloads["default"][graph_id]
                assert set(wrapper) == WRAPPER_FIELDS
                assert wrapper["read_only"] is True
                assert wrapper["summary_kind"] == "openapi"
                assert wrapper["graph"]["graph_id"] == graph_id
                assert wrapper["graph"]["enabled"] is True
                assert wrapper["graph"]["mcp_visible"] is True
                _assert_nested_key_order(wrapper["summary"])
            public_wrapper = mcp_payloads["default"]["public-openapi"]
            sanitized_expected = json.loads(json.dumps(expected))
            sanitized_expected["root_path"] = "[graph-root]"
            sanitized_expected["redactions"]["credentialed_urls"] = "[REDACTED]"
            sanitized_expected["redactions"]["secret_prone_fields"] = "[REDACTED]"
            assert public_wrapper["summary"] == sanitized_expected
            assert public_wrapper["graph"]["root_path_display"] == "[graph-root]"
            private_wrapper = mcp_payloads["default"]["private-openapi"]
            assert private_wrapper["summary"]["root_path"] == "[private-root]"
            for key in ("root_path_display", "root_path_expanded"):
                assert private_wrapper["graph"][key] == "[private-root]"
            assert private_wrapper["graph"]["private"] is True
            assert private_wrapper["graph"]["warnings"][0]["code"] == (
                "private-graph-visible")

            serialized = json.dumps({
                "direct": direct_payloads, "jsonable": jsonable_payloads,
                "defaults": list(defaults.values()),
                "cli": {"default": default_cli, "psql": psql_cli},
                "mcp": mcp_payloads,
            }, sort_keys=True)
            for forbidden in _private_markers(private_root):
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


class _openapi_fixture_jsonl:
    def __enter__(self) -> Path:
        fixture_root = openapi_fixture("openapi1_contracts")
        fixture_files = tuple(fixture_root.iterdir())
        assert len(fixture_files) == 5
        observations = _openapi_observations()
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.path = Path(handle.name)
        with handle:
            for observation in observations:
                handle.write(observation.to_json_line())
        return self.path

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.path.unlink(missing_ok=True)

def _openapi_observations() -> tuple[RawObservation, ...]:
    kinds = tuple("openapi.info openapi.server openapi.path openapi.parameter "
        "openapi.request_body openapi.response openapi.schema openapi.component "
        "openapi.security_scheme openapi.tag openapi.example".split())
    observations = [
        _observation("openapi.document", 0, spec_family="openapi3", sensitive=True),
        _observation("openapi.document", 1, spec_family="swagger2"),
        *(_observation(kind, index + 2) for index, kind in enumerate(kinds)),
        _observation("openapi.operation", 20, method="GET"),
        _observation("openapi.operation", 21, method="POST"),
        _observation("openapi.reference", 22, reference_scope="internal"),
        _observation("openapi.reference", 23, reference_scope="local_file"),
        _observation("openapi.reference", 24, reference_scope="remote", not_fetched=True),
        _observation("openapi.reference", 25, reference_scope="external_docs", not_fetched=True),
    ]
    reasons = tuple("credentialed-url openapi-ref-summary-only "
        "openapi-text-summary-only openapi-example-summary-only "
        "secret-prone-openapi-field".split())
    observations.extend(_observation("openapi.redaction", index,
        redaction_reason=reason) for index, reason in enumerate(reasons, start=30))
    errors = tuple("unsupported-openapi-document openapi-path-limit "
        "openapi-local-ref-outside-root malformed-openapi-yaml".split())
    observations.extend(_observation("openapi.parse_error", index,
        error_kind=error_kind) for index, error_kind in enumerate(errors, start=40))
    return tuple(observations)

def _observation(
    kind: str,
    index: int,
    *,
    sensitive: bool = False,
    **metadata: object,
) -> RawObservation:
    if sensitive:
        metadata.update({
            "document_path": "private/openapi.yaml", "operation_path": "/private/accounts",
            "operation_id": "privateOperation", "parameter_name": "privateParameter",
            "schema_name": "PrivateSchema", "example": "private example",
            "description": "private description", "server_url": "https://private.invalid/api",
            "reference_target": "private/reference.yaml", "security_scheme": "PrivateCredential",
            "credentialed_url": "https://user:secret@private.invalid", "diagnostic": "private parser diagnostic",
            "source_snippet": "private source snippet", "raw_document": "private raw json yaml",
            "credential": "credential-value", "secret": "secret-value", "token": "token-value",
        })
    return RawObservation(
        kind=kind,
        source_id=f"synthetic/openapi.yaml#{kind}:{index}",
        path="synthetic/openapi.yaml",
        confidence="extracted",
        extractor="psycopg74-fixture",
        extractor_version="1",
        name=f"synthetic-{index}",
        metadata=metadata,
    )


def _load_fixture(
    fixture_path: Path, *, root_path: str, repository_name: str, postgres,
) -> None:
    result = run_repo_map_in_process(
        "storage", "load-files", str(fixture_path), "--repository-name", repository_name,
        *_cli_connection_args(postgres, root_path=root_path), "--psql-command", postgres.psql_command, "--json",
    )
    assert result[0] == 0, result[2]


def _cli_connection_args(postgres, *, root_path: str) -> tuple[str, ...]:
    return (
        "--root-path", root_path, "--pg-host", str(postgres.socket_dir),
        "--pg-port", str(postgres.port), "--pg-user", postgres.user,
        "--pg-database", postgres.database,
    )

def _mcp_payloads(postgres, *, public_root: str, private_root: str):
    from repomap_kg.server.mcp import repomap_openapi_summary

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "psycopg74.local.toml"
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
                graph_id: repomap_openapi_summary(graph_id=graph_id)
                for graph_id in ("public-openapi", "private-openapi")
            }
        return payloads

def _ops_config(postgres, *, public_root: str, private_root: str) -> str:
    return (
        f'schema_version = 1\n\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\ndatabase = "repomap_test"\nuser = "{postgres.user}"\n'
        f'password_env = "REPOMAP_PG_PASSWORD"\n\n[[graphs]]\nid = "public-openapi"\nname = "Public OpenAPI"\n'
        f'root_path = "{public_root}"\nrepository_name = "psycopg74-public"\nprivacy = "public-dev"\nenabled = true\nmcp_visible = true\n'
        f'extractor_profile = "default"\nrefresh_policy = "manual"\n\n[[graphs]]\nid = "private-openapi"\nname = "Private OpenAPI"\n'
        f'root_path = "{private_root}"\nrepository_name = "psycopg74-private"\ndatabase = "repomap_test_private_openapi"\n'
        f'privacy = "private-ops"\nenabled = true\nmcp_visible = true\nextractor_profile = "private"\nrefresh_policy = "manual"\n\n'
        f'[server_memory]\nenabled = false\npath = "~/.codex/codex-vc/mcp/server-memory"\nmode = "read_only"\n'
    )


def _assert_complete_nonempty_contract(payload: dict[str, object]) -> None:
    assert payload["root_path"] == "/tmp/psycopg74-openapi-public"
    assert payload["repository_name"] == "psycopg74-public"
    obs = payload["openapi_observations"]
    assert isinstance(obs, int) and obs > 0
    assert payload["openapi_documents"] == 2
    assert payload["spec_families"] == {"openapi3": 1, "swagger2": 1}
    refs = payload["references"]
    assert isinstance(refs, dict) and refs["refs_not_fetched"] == 2
    redactions = payload["redactions"]
    assert isinstance(redactions, dict) and all(isinstance(v, int) and v > 0 for v in redactions.values())
    diag = payload["diagnostics"]
    assert isinstance(diag, dict) and diag["malformed_specs"] == 1
    gc = payload["generic_config"]
    assert isinstance(gc, dict)
    assert isinstance(gc["config_documents"], int) and gc["config_documents"] > 0
    assert isinstance(gc["config_paths"], int) and gc["config_paths"] > 0
    _assert_nested_key_order(payload)


def _assert_unknown_root(payload: dict[str, object]) -> None:
    assert payload["repository_name"] is None
    assert payload["openapi_observations"] == payload["openapi_documents"] == 0
    for name in COUNT_MAP_KEYS:
        val_map = payload[name]
        assert isinstance(val_map, dict) and all(v == 0 for v in val_map.values())
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_openapi_empty(payload: dict[str, object]) -> None:
    assert payload["repository_name"] == "psycopg74-empty"
    assert payload["openapi_observations"] == payload["openapi_documents"] == 0
    diag = payload["diagnostics"]
    assert isinstance(diag, dict) and diag["malformed_specs"] == 0
    gc = payload["generic_config"]
    assert isinstance(gc, dict)
    assert isinstance(gc["config_documents"], int) and gc["config_documents"] > 0
    assert isinstance(gc["config_paths"], int) and gc["config_paths"] > 0
    safety = payload["safety"]
    assert isinstance(safety, dict) and all(bool(v) for v in safety.values())


def _assert_nested_key_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    total_len = 0
    for name, required_keys in COUNT_MAP_KEYS.items():
        item = payload[name]
        assert isinstance(item, dict) and tuple(item) == required_keys
        total_len += len(item)
    assert total_len == 41
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


def _private_markers(private_root: str) -> tuple[str, ...]:
    return (private_root, "synthetic-private", "private/openapi.yaml",
        "/private/accounts", "privateOperation", "privateParameter",
        "PrivateSchema", "private example", "private description",
        "https://private.invalid/api", "private/reference.yaml",
        "PrivateCredential", "https://user:secret@private.invalid",
        "private parser diagnostic", "private source snippet",
        "private raw json yaml", "credential-value", "secret-value", "token-value")


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
