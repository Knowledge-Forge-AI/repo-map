"""Host-native stdio MCP reads through the named read-store seams (READSTORE1/2).

A real PostgreSQL publication is read by a real ``repomap-kg mcp serve``
subprocess that has no Docker access, no inherited database password, and no
source roots. The four canonical tools (READSTORE1) and the seven configured
investigation tools (READSTORE2) must equal incumbent PostgreSQL read APIs and
independent query owners on the same publication.

Inside the authenticated test sandbox the child is the runner-provisioned
``repomap-kg`` wrapper (recorded as ``launch_mode``). That is neither the
operator's macOS checkout console script nor native host proof.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import uuid

import pytest

from repomap_kg.runtime.database_roles import READ_STATUS_ROLE
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_kg.storage import (
    canonical_neighborhood_to_jsonable, canonical_node_records_to_jsonable,
    public_embedded_read_result_to_jsonable, public_read_page, public_read_page_to_jsonable,
    query_canonical_neighborhood, query_canonical_node_records,
)
from repomap_test_support.host_mcp_investigation import build_plan, seven_tool_requests, verify_plan
from repomap_test_support.host_mcp_publication import (
    ABSENT_DATABASE, RESTORE_LOGIN_SQL, assert_least_privilege, await_no_read_role_backends, cli, jsonable,
    publish_fixture, snapshot, write_config,
)
from repomap_test_support.host_mcp_stdio import (
    HostMcpHarness, forbidden_env_keys, initialize_request, tool_request, tools_list_request,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres

SEAM_TOOLS = ("repomap_canonical_nodes", "repomap_canonical_edges",
              "repomap_explain_canonical_edge", "repomap_canonical_neighborhood")
INVESTIGATION_TOOLS = ("repomap_graph_status", "repomap_refresh_status", "repomap_search_nodes",
                       "repomap_search_files", "repomap_search_observations", "repomap_project_summary",
                       "repomap_neighborhood")
READ_TOOL_IDS = (4, 5, 6, 7, 8)  # search x3, project summary, neighborhood in seven_tool_requests(1, ...)
CANARY_KEY = "REPOMAP_ENV_CANARY_PASSWORD_PROBE"


def test_host_native_stdio_mcp_reads_seam_tools_without_docker_or_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    for name in ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_READ_STATUS_PASSWORD",
                 "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psycopg")
    with temporary_postgres() as postgres:
        multi_name = f"host_multi_{uuid.uuid4().hex[:10]}"
        multi_db = postgres.create_database(multi_name)
        try:
            _run_proof(tmp_path, postgres, multi_db)
        finally:
            postgres.psql_scalar(RESTORE_LOGIN_SQL)
            postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{multi_name}" WITH (FORCE);')


def _run_proof(tmp_path: Path, postgres, multi_db) -> None:
    publication = publish_fixture(tmp_path, postgres, multi_db)
    home, databases, roots = publication.home, publication.databases, publication.roots
    before = snapshot(publication)
    catalog_sha256 = hashlib.sha256(json.dumps(tool_definitions(), sort_keys=True).encode()).hexdigest()

    harness = HostMcpHarness(tmp_path / "mcp", home)
    requests, expected = [initialize_request(1), tools_list_request(2)], {}
    for index, graph_id in enumerate(databases):
        base = 100 * (index + 1)
        oracle = _incumbent(graph_id, databases[graph_id], roots[graph_id], home)
        expected.update({base + offset: value for offset, value in oracle["expected"].items()})
        requests.extend(tool_request(base + offset, name, {"project": graph_id, **args})
                        for offset, (name, args) in oracle["requests"].items())
    plan = build_plan(publication)
    requests.extend(tool_request(mid, name, args) for mid, (name, args) in plan.requests.items())
    refusals: dict[int, tuple[str, dict[str, object], str]] = {
        900: ("repomap_canonical_nodes", {"project": "host-one", "limit": 201}, "limit must be between 1 and 200"),
        901: ("repomap_canonical_edges", {"project": "host-one", "result_schema_version": 2},
              "result schema version must be 0 or 1"),
        902: ("repomap_canonical_nodes", {"project": "no-such-graph"},
              "unknown legacy MCP project or graph-registry graph_id: no-such-graph"),
        903: ("repomap_canonical_nodes", {"project": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        910: ("repomap_search_nodes", {"graph_id": "no-such-graph", "query": "sh"}, "unknown graph_id: no-such-graph"),
        911: ("repomap_graph_status", {"graph_id": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        912: ("repomap_refresh_status", {"graph_id": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
        913: ("repomap_search_files", {"graph_id": "host-one", "query": "   "}, "query is required"),
        914: ("repomap_search_observations", {"graph_id": "host-one", "query": "sh", "limit": 0},
              "limit must be a positive integer"),
        915: ("repomap_neighborhood", {"graph_id": "host-one", "node": plan.chain["key"], "depth": 2},
              "neighborhood depth is capped at 1 in MCP-OPS4"),
        916: ("repomap_project_summary", {"graph_id": "host-hidden"}, "graph 'host-hidden' is not MCP-visible"),
    }
    requests.extend(tool_request(mid, name, args) for mid, (name, args, _) in refusals.items())

    session = harness.run(requests)
    assert session.returncode == 0, session.stderr
    assert forbidden_env_keys(session.observed_env_keys) == (), session.observed_env_keys
    assert session.result(1)["protocolVersion"] == "2024-11-05"
    listed = {tool["name"]: tool for tool in session.result(2)["tools"]}
    advertised = {tool["name"]: tool for tool in tool_definitions()}
    assert listed == advertised and set(SEAM_TOOLS + INVESTIGATION_TOOLS) <= set(listed) and len(listed) == 27
    for message_id, value in expected.items():
        assert session.structured(message_id) == value, message_id
    for message_id, (_name, _args, text) in refusals.items():
        assert session.refusal(message_id) == text, message_id
    node_pages = [session.structured(mid)["items"] for mid in (101, 102)]
    assert node_pages[0] and node_pages[1] and node_pages[0] != node_pages[1]
    investigation = verify_plan(plan, session.structured)

    assert_least_privilege(postgres, publication.secrets.read_status)
    postgres.psql_scalar(f'ALTER ROLE "{READ_STATUS_ROLE}" NOLOGIN;')
    try:
        denied = harness.run([initialize_request(1), tool_request(2, *_nodes_call("host-one")),
                              tool_request(3, "repomap_list_graphs", {}),
                              *_requests(seven_tool_requests(10, "host-one", plan.chain["key"]))])
    finally:
        postgres.psql_scalar(f'ALTER ROLE "{READ_STATUS_ROLE}" LOGIN;')
    assert denied.returncode == 0 and denied.refusal(2) == "psycopg readback failed for canonical node records"
    assert [g["graph_id"] for g in denied.structured(3)["graphs"]] == ["host-one", "host-multi", "host-absent"]
    nologin = _bounded_outcomes(denied, 10)

    restart_ids = {2: _nodes_call("host-one"), 3: plan.requests[313], 4: plan.requests[320], 5: plan.requests[305]}
    restarted = harness.run([initialize_request(1), *_requests(restart_ids)])
    assert restarted.returncode == 0 and restarted.structured(2) == expected[101]
    for mid, source in ((3, 313), (4, 320), (5, 305)):
        assert restarted.structured(mid) == session.structured(source), mid
    canary = harness.run([initialize_request(1), tool_request(2, "repomap_list_graphs", {})],
                         extra_env={CANARY_KEY: "synthetic"})
    assert canary.returncode == 0 and CANARY_KEY in canary.observed_env_keys
    assert forbidden_env_keys(canary.observed_env_keys) == (CANARY_KEY,)
    await_no_read_role_backends(postgres)
    assert snapshot(publication) == before
    absent = _postgres_absent_sessions(tmp_path, harness, plan.chain["key"])
    assert harness.shim_invocations() == ""
    _emit_evidence(session, denied, restarted, canary, absent, before, catalog_sha256, investigation, nologin)


def _incumbent(graph_id: str, database, root: str, home: Path) -> dict[str, dict]:
    """Incumbent PostgreSQL read APIs and CLI owners on the same publication."""

    identity = f"repo1:{graph_id}"
    common = {"root_path": root, "repository_identity": identity, "psql_command": database.psql_command}
    node_pages = {}
    for offset in (0, 1):
        records = query_canonical_node_records(database.psql_args, limit=2, offset=offset, **common)
        page = public_read_page(records, limit=1, offset=offset)
        node_pages[offset] = public_read_page_to_jsonable(
            page, result_kind="canonical_nodes", serialize_items=canonical_node_records_to_jsonable)
    all_nodes = query_canonical_node_records(database.psql_args, limit=201, offset=0, **common)
    edges = cli(home, graph_id, "edges", "--limit", "200")
    edges_v0 = cli(home, graph_id, "edges", "--limit", "200", "--legacy-json-array")
    edge = edges["items"][0]
    explain_args = ("--source-key", edge["source_key"], "--kind", edge["edge_kind"], "--target-key",
                    edge["target_key"], "--identity-metadata-json", json.dumps(edge["identity_metadata"]),
                    "--evidence-limit", "1")
    explanation = cli(home, graph_id, "explain-canonical-edge", *explain_args)
    explanation_v0 = cli(home, graph_id, "explain-canonical-edge", *explain_args, "--legacy-json-object")
    record = query_canonical_neighborhood(
        database.psql_args, node=edge["source_key"], direction="both", depth=1, graph_key_version=1,
        node_limit=2, node_offset=0, edge_limit=2, edge_offset=0, **common)
    node_page = public_read_page(record.nodes, limit=1, offset=0)
    edge_page = public_read_page(record.edges, limit=1, offset=0)
    neighborhood = public_embedded_read_result_to_jsonable(
        canonical_neighborhood_to_jsonable(replace(record, nodes=node_page.items, edges=edge_page.items)),
        result_kind="canonical_neighborhood", collection_pages={"nodes": node_page, "edges": edge_page})
    explain = {"source_key": edge["source_key"], "kind": edge["edge_kind"], "target_key": edge["target_key"],
               "identity_metadata": edge["identity_metadata"], "evidence_limit": 1}
    neighbor = {"node": edge["source_key"], "direction": "both", "node_limit": 1, "edge_limit": 1}
    return {
        "requests": {
            1: ("repomap_canonical_nodes", {"limit": 1, "offset": 0}),
            2: ("repomap_canonical_nodes", {"limit": 1, "offset": 1}),
            3: ("repomap_canonical_nodes", {"limit": 200, "result_schema_version": 0}),
            4: ("repomap_canonical_edges", {"limit": 200}),
            5: ("repomap_canonical_edges", {"limit": 200, "result_schema_version": 0}),
            6: ("repomap_explain_canonical_edge", explain),
            7: ("repomap_explain_canonical_edge", {**explain, "result_schema_version": 0}),
            8: ("repomap_canonical_neighborhood", neighbor),
        },
        "expected": {key: jsonable(value) for key, value in {
            1: node_pages[0], 2: node_pages[1], 3: canonical_node_records_to_jsonable(all_nodes[:200]),
            4: edges, 5: edges_v0, 6: explanation, 7: explanation_v0, 8: neighborhood,
        }.items()},
    }


def _requests(calls: dict[int, tuple[str, dict]]) -> list[dict]:
    return [tool_request(mid, name, args) for mid, (name, args) in calls.items()]


def _nodes_call(graph_id: str) -> tuple[str, dict]:
    return "repomap_canonical_nodes", {"project": graph_id, "limit": 1, "offset": 0}


def _bounded_outcomes(session, start: int) -> dict[str, str]:
    """Every seven-tool read is a bounded refusal or a bounded status error."""

    outcomes: dict[str, str] = {}
    for offset, label in enumerate(("graph_status", "refresh_selected", "refresh_all", "search_nodes",
                                    "search_files", "search_observations", "project_summary", "neighborhood")):
        if offset + 1 in READ_TOOL_IDS:
            text = session.refusal(start + offset)
        else:
            payload = session.structured(start + offset)
            statuses = [payload["storage"]] if "storage" in payload else payload["graphs"]
            assert statuses and all(s["error"] and not s["repository_exists"] for s in statuses), label
            text = statuses[0]["error"]
        assert 0 < len(text) <= 300 and "docker" not in text and "Postgres container" not in text, (label, text)
        outcomes[label] = text
    return outcomes


def _postgres_absent_sessions(tmp_path: Path, harness: HostMcpHarness, node: str) -> dict[str, dict]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    outcomes = {}
    for label, direct, port, env in (
        ("closed-host-port", "true", closed_port, {}),
        ("container-internal-psql", "false", 55439, {"REPOMAP_STORAGE_READBACK_DRIVER": "psql"}),
    ):
        home = tmp_path / f"absent-{label}"
        setup_local_runtime(home)
        write_config(home, port, "repomap_absent_one", "repomap_absent_multi", tmp_path / "missing-sources")
        config = home / "repomap.rpl.toml"
        config.write_text(config.read_text(encoding="utf-8").replace(
            "direct_host_port_enabled = true", f"direct_host_port_enabled = {direct}"), encoding="utf-8")
        started = time.monotonic()
        absent = harness.run([initialize_request(1), tool_request(2, *_nodes_call("host-one")),
                              *_requests(seven_tool_requests(10, "host-one", node))], home=home, extra_env=env)
        refusal = absent.refusal(2)
        assert absent.returncode == 0 and 0 < len(refusal) <= 300, refusal
        investigation = _bounded_outcomes(absent, 10)
        assert harness.shim_invocations() == "", label
        outcomes[label] = {"exit": absent.returncode, "refusal": refusal, "investigation": investigation,
                           "bounded_seconds": round(time.monotonic() - started, 1)}
    return outcomes


def _emit_evidence(session, denied, restarted, canary, absent, before, catalog, investigation, nologin) -> None:
    payload = {
        "argv_tail": list(session.argv[1:4]), "launched_executable": Path(session.argv[0]).name,
        "launch_mode": session.launch_mode, "launch_sha256": session.launch_sha256,
        "observed_env_keys": list(session.observed_env_keys),
        "observed_env_scope": "launched executable at the observer final-exec seam; a runner-provisioned "
                              "wrapper adds PYTHONPATH before exec'ing python3",
        "canary_observed_forbidden_keys": list(forbidden_env_keys(canary.observed_env_keys)),
        "catalog_sha256": catalog, "main_exit": session.returncode, "main_responses": len(session.responses),
        "investigation": investigation, "nologin_exit": denied.returncode, "nologin_outcomes": nologin,
        "restart_exit": restarted.returncode, "canary_exit": canary.returncode, "postgres_absent": absent,
        "absent_graph_database": ABSENT_DATABASE, "counts_unchanged": before[1],
        "home_files_unchanged": len(before[0]), "shim_invocations": "",
    }
    stream = getattr(sys, "__stdout__", None)
    if stream is not None:
        stream.write("HOST_MCP_READSTORE_EVIDENCE=" + json.dumps(payload, sort_keys=True, default=list) + "\n")
        stream.flush()
