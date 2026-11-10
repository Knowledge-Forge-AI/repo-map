"""Dependency-provisioned installed Server proof (rows S01-S04).

The environment is labelled ``provisioned-server`` and is never reported as
pure: it inherits the SDK's dynamic Psycopg and libpq. The temporary PostgreSQL
cluster stays in this parent process; the installed child receives only an
owned private home and private argv (the psql command), and none of those
values, paths or raw streams reach the evidence. An unavailable harness is
recorded as ``installed-server-harness-unavailable`` (gate G2), never skipped.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.coordinator._control_schema import discover_control_migrations
from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.server._mcp_dispatch import MCP_PROTOCOL_VERSION
from common_lore_index.server.mcp_schemas import tool_definitions
from common_lore_index.storage import discover_migrations
from installed_experience_pins import CODE_KIND, GRAPH_ID, POSTGRES_BIN
from installed_experience_rules import classify_environment
from repomap_test_support.installed_candidate import ROOT, candidate_wheel
from repomap_test_support.installed_environment import include_system_site_packages, run_child
from repomap_test_support.installed_experience_driver import (
    Observed, OwnerRun, intent_for, json_object, preparation, pure_environment,
)
from repomap_test_support.installed_experience_fixture import (
    expectations, provisioned_postgres_home, write_tiny_material,
)
from repomap_test_support.installed_mcp_session import result_digest, useful_question
from repomap_test_support.installed_origin import classify, closure, observe_origin
from repomap_test_support.postgres_harness import temporary_postgres

OUT, MCP = "child-stdout", "mcp-reply"
READBACK = {"REPOMAP_STORAGE_READBACK_DRIVER": "psycopg"}
SERVER_PROBE = """import json, os, sys
home, psql, database, graph, query = sys.argv[1:6]
secret = os.path.join(home, 'pgpass.secret')
if os.path.isfile(secret):
    with open(secret, encoding='utf-8') as handle:
        os.environ['PGPASSWORD'] = handle.read()
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.storage import apply_migrations, default_rdbms_root
config = load_graph_registry_config_home(home)
apply_migrations(default_rdbms_root(), config.postgres.psql_args_for_database(database), psql_command=psql)
result = refresh_graph(config, graph, psql_command=psql)
print(json.dumps({'stage': 'refresh', 'result': result.result,
                  'publication_state': result.publication_state,
                  'failure_category': result.error_category}), flush=True)
os.environ['CLOE_HOME'] = home
from common_lore_index.server._mcp_navigation import repomap_navigation_search
found = repomap_navigation_search(graph_id=graph, query=query, scope='code')
kinds = [member.get('kind') for group in found.get('results', []) for member in group.get('members', [])]
print(json.dumps({'result': result.result, 'publication_state': result.publication_state,
                  'function_present': %r in kinds}))
""" % CODE_KIND


def _triples_sha(items: Any) -> str:
    rows = [[item.relative_path, item.changeset_id, item.checksum] for item in items]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def test_installed_provisioned_server(tmp_path_factory, tmp_path: Path) -> None:
    candidate = candidate_wheel(tmp_path_factory)
    owned = tmp_path / "owned root"
    env = pure_environment(owned / "provisioned env", candidate, env_class="provisioned-server")
    material = write_tiny_material(owned / "owned material" / "tiny")
    expect = expectations()
    resources = ROOT / "src" / "main" / "resources"
    source = {"S02": {"graph_catalog_sha256": _triples_sha(discover_migrations(resources / "rdbms")),
                      "control_catalog_sha256": _triples_sha(discover_control_migrations(
                          resources / "coordinator-rdbms"))},
              "S04": {"tools_sha256": result_digest({"tools": tool_definitions()})}}
    run = OwnerRun("server", intent_for("server", preparation(candidate), source))
    run.registry.own(owned)
    state: dict[str, Any] = {}
    cluster = contextlib.ExitStack()

    def s01() -> Observed:
        normal = observe_origin(env, ROOT, isolated=False)
        record = observe_origin(env, ROOT, isolated=True)
        if not (normal.ok and record.ok):
            return Observed(failure_code="witness-failed")
        state["probe"] = record.payload
        driver = (record.payload or {}).get("driver") or {}
        observed = classify_environment(include_system_site_packages(env),
                                        record.path_counts.get("system-site", 0) > 0)
        return Observed({
            "closure_holds": (closure(env.env_class, normal, record)
                              and (normal.payload or {}).get("driver") == driver, OUT),
            "product_origin": (record.module_origins["common_lore_index"], OUT),
            "facade_origin": (record.module_origins.get("repomap_kg"), OUT),
            "dependency_origin": (record.module_origins.get("typing_extensions"), OUT),
            "resource_root": (record.resource_root, OUT),
            "psycopg_origin": (classify(driver.get("file"), env, ROOT), OUT),
            "psycopg_version": (driver.get("version"), OUT), "psycopg_impl": (driver.get("impl"), OUT),
            "label": ("provisioned-server" if observed == "provisioned" else "pure-local", OUT)},
            origin_classes=record.path_counts)

    def s02() -> Observed:
        payload = state.get("probe") or {}
        return Observed({"graph_catalog_sha256": (payload.get("graph_catalog_sha256"), OUT),
                         "control_catalog_sha256": (payload.get("control_catalog_sha256"), OUT)})

    def s03() -> Observed:
        try:
            postgres = cluster.enter_context(temporary_postgres())
        except (Exception, pytest.skip.Exception):
            return Observed(failure_code="installed-server-harness-unavailable")
        home = provisioned_postgres_home(owned / "owned homes" / "server home", material,
                                         host=postgres.host, port=postgres.port, database=postgres.database,
                                         user=postgres.user, password=postgres.password)
        state["home"] = home
        # The container harness wrapper needs its parent's Docker CLI environment.
        # The installed child uses the already provisioned SDK client over the same TCP endpoint.
        client = Path(POSTGRES_BIN) / "psql"
        if not client.is_file():
            return Observed(failure_code="installed-server-harness-unavailable")
        result = run_child(env, (str(env.python), "-c", SERVER_PROBE, str(home), str(client),
                                 postgres.database, GRAPH_ID, expect.code_query), extra=READBACK)
        payload = json_object(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "") or {}
        if result.returncode != 0:
            print(json.dumps({"event": "installed-server-probe-rejected",
                              "refresh_result": payload.get("result"),
                              "publication_state": payload.get("publication_state"),
                              "failure_category": payload.get("failure_category")}, sort_keys=True))
            return Observed(exit=result.exit, failure_code="child-exit-nonzero")
        if not payload:
            return Observed(failure_code="protocol-violation")
        selected = run_child(env, (str(env.wrapper("cloe")), "ops", "context-select",
                                   "--repo-map-home", str(home), "--graph", GRAPH_ID,
                                   "--binding", graph_source_binding_id(GRAPH_ID, "code"),
                                   "--pin-publication", "--output", str(owned / "server-selection.json")),
                             extra=READBACK)
        pin = (json_object(selected.stdout) or {}).get("expected_publication") or {}
        generation = pin.get("generation") if selected.returncode == 0 else None
        return Observed({"accepted_generation": (generation, OUT),
                         "refresh_result": (payload.get("result"), OUT),
                         "publication_state": (payload.get("publication_state"), OUT),
                         "function_present": (payload.get("function_present"), OUT)}, exit=result.exit)

    def s04() -> Observed:
        home = state["home"]
        answer = useful_question(env, (str(env.wrapper("cloe")), "mcp", "serve", "--repo-map-home", str(home)),
                                 graph_id=GRAPH_ID, code_query=expect.code_query, code_kind=CODE_KIND,
                                 docs_query=expect.docs_query, protocol=MCP_PROTOCOL_VERSION, extra=READBACK)
        if not answer.complete:
            return Observed(failure_code="protocol-violation")
        return Observed({"tools_sha256": (answer.tools_sha256, MCP),
                         "useful_member_found": (answer.facts.get("code_kind", (None,))[0] == CODE_KIND, MCP)})

    try:
        for scenario, action in (("S01", s01), ("S02", s02), ("S03", s03), ("S04", s04)):
            run.step(scenario, action)
    finally:
        cluster.close()
    root, verdict = run.finish(tmp_path)
    assert verdict.outcome == "accepted", (verdict.categories, run.mismatches, [
        (row["scenario"], row["outcome"], row["failure_code"]) for row in verdict.rows])
    assert root.is_dir()
