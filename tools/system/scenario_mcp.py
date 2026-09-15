"""MCP public-readback scenario for the assembled-product system gate."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Protocol

from repomap_kg.runtime.plan import LocalRuntimePlan
from tools.system.config import SystemTestError
from tools.system.report import SystemStepResult


class ScenarioTimer(Protocol):
    """Timer surface required by the MCP scenario."""

    def check_budget(self) -> None:
        """Raise when the system-test execution budget is exhausted."""


LoadPlanEnv = Callable[[LocalRuntimePlan], dict[str, str]]
RunCompose = Callable[..., subprocess.CompletedProcess[str]]


def run_mcp_public_readback(
    compose_dir: Path,
    plan: LocalRuntimePlan,
    timer: ScenarioTimer,
    *,
    load_plan_env: LoadPlanEnv,
    run_compose: RunCompose,
) -> tuple[SystemStepResult, str]:
    """Step 5: Public readback through candidate MCP stdio container and verify deterministic digest."""
    step_start = time.monotonic()
    timer.check_budget()
    env = load_plan_env(plan)

    def _query_mcp() -> dict[str, Any]:
        rpc_requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "system-test", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "repomap_list_graphs", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "repomap_graph_status", "arguments": {"graph_id": "fixture"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "repomap_search_nodes", "arguments": {"graph_id": "fixture", "query": "add"}}},
        ]
        stdin_text = "\n".join(json.dumps(req) for req in rpc_requests) + "\n"

        proc = run_compose(
            compose_dir,
            ["--profile", "integration", "run", "--rm", "-i", "mcp"],
            env=env,
            stdin_input=stdin_text,
            timeout=60.0,
            timer=timer,
        )

        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            raise SystemTestError("empty output from MCP stdio session")

        responses_by_id: dict[int, dict[str, Any]] = {}
        for line in lines:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemTestError(f"invalid JSON-RPC line from MCP server: {line!r}") from error

            if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                raise SystemTestError(f"invalid JSON-RPC protocol envelope: {msg!r}")

            if "error" in msg:
                raise SystemTestError(f"MCP server returned JSON-RPC error: {msg['error']!r}")

            if "id" not in msg:
                method = msg.get("method")
                if not isinstance(method, str) or not method or "result" in msg:
                    raise SystemTestError(
                        f"invalid JSON-RPC notification from MCP server: {msg!r}"
                    )
                continue
            msg_id = msg["id"]
            if not isinstance(msg_id, int) or isinstance(msg_id, bool):
                raise SystemTestError(f"invalid JSON-RPC response ID: {msg_id!r}")
            if msg_id not in {1, 3, 4, 5}:
                raise SystemTestError(f"unexpected JSON-RPC response ID: {msg_id}")
            if msg_id in responses_by_id:
                raise SystemTestError(f"duplicate JSON-RPC response ID received: {msg_id}")
            responses_by_id[msg_id] = msg

        # Validate required response IDs
        for req_id in (1, 3, 4, 5):
            if req_id not in responses_by_id:
                raise SystemTestError(f"missing JSON-RPC response for request ID {req_id}")

        # Check response 1 (initialize)
        init_res = responses_by_id[1].get("result", {})
        if init_res.get("serverInfo", {}).get("name") != "repomap-kg":
            raise SystemTestError(f"unexpected MCP serverInfo: {init_res}")

        # Check response 3 (repomap_list_graphs)
        list_graphs_payload = responses_by_id[3].get("result", {})
        if list_graphs_payload.get("isError"):
            raise SystemTestError(f"repomap_list_graphs returned tool error: {list_graphs_payload}")
        list_graphs_struct = list_graphs_payload.get("structuredContent", {})
        graphs = list_graphs_struct.get("graphs", [])
        graph_ids = [
            g["graph_id"]
            for g in graphs
            if isinstance(g, dict) and isinstance(g.get("graph_id"), str)
        ]
        if "fixture" not in graph_ids:
            raise SystemTestError(f"repomap_list_graphs did not contain 'fixture' graph: {graph_ids}")

        # Check response 4 (repomap_graph_status)
        status_payload = responses_by_id[4].get("result", {})
        if status_payload.get("isError"):
            raise SystemTestError(f"repomap_graph_status returned tool error: {status_payload}")
        status_struct = status_payload.get("structuredContent", {})
        graph_obj = status_struct.get("graph", {}) if isinstance(status_struct.get("graph"), dict) else status_struct
        storage_obj = status_struct.get("storage", {}) if isinstance(status_struct.get("storage"), dict) else status_struct

        graph_id = graph_obj.get("graph_id") or status_struct.get("graph_id")
        if graph_id != "fixture":
            raise SystemTestError(f"repomap_graph_status returned invalid graph_id: {status_struct}")
        repo_name = graph_obj.get("repository_name") or status_struct.get("repository_name")
        if repo_name != "fixture":
            raise SystemTestError(
                f"repomap_graph_status returned the wrong fixture repository: {status_struct}"
            )
        canonical_nodes = storage_obj.get("canonical_nodes") or status_struct.get("canonical_nodes")
        canonical_edges = storage_obj.get("canonical_edges") or status_struct.get("canonical_edges")
        if not isinstance(canonical_nodes, int) or canonical_nodes <= 0:
            raise SystemTestError(f"repomap_graph_status returned invalid canonical_nodes (expected > 0): {canonical_nodes}")
        if not isinstance(canonical_edges, int) or canonical_edges <= 0:
            raise SystemTestError(f"repomap_graph_status returned invalid canonical_edges (expected > 0): {canonical_edges}")

        # Check response 5 (repomap_search_nodes)
        search_payload = responses_by_id[5].get("result", {})
        if search_payload.get("isError"):
            raise SystemTestError(f"repomap_search_nodes returned tool error: {search_payload}")
        search_struct = search_payload.get("structuredContent", {})
        matches = search_struct.get("results") or search_struct.get("matches", [])
        if not isinstance(matches, list) or not matches:
            raise SystemTestError(f"repomap_search_nodes returned empty matches for query 'add': {search_struct}")
        found_keys = [
            m.get("canonical_key") for m in matches if isinstance(m, dict) and "canonical_key" in m
        ]
        expected_exact_key = "python.function:calc:add"
        if expected_exact_key not in found_keys:
            raise SystemTestError(
                f"repomap_search_nodes did not find expected exact semantic key {expected_exact_key!r}: found {found_keys}"
            )

        # Build stable canonical semantic projection
        semantic_projection = {
            "graph_ids": sorted(graph_ids),
            "fixture_status": {
                "graph_id": graph_id,
                "repository_name": repo_name,
                "canonical_nodes": canonical_nodes,
                "canonical_edges": canonical_edges,
            },
            "fixture_search_add_keys": sorted(str(k) for k in found_keys if k),
        }
        return semantic_projection

    def _projection_digest(proj: dict[str, Any]) -> str:
        encoded = json.dumps(proj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    # First MCP readback
    projection_1 = _query_mcp()
    digest_1 = _projection_digest(projection_1)

    # Second MCP readback across container recreation
    projection_2 = _query_mcp()
    digest_2 = _projection_digest(projection_2)

    if digest_1 != digest_2:
        raise SystemTestError(
            f"non-deterministic MCP readback across container runs: {digest_1} != {digest_2}"
        )

    duration = time.monotonic() - step_start
    return (
        SystemStepResult(
            step_name="mcp_public_stdio_readback",
            status="passed",
            duration_seconds=duration,
            message="Public MCP stdio queried; line-delimited JSON-RPC parsed; canonical semantic projection verified deterministically",
            details={"canonical_semantic_sha256": digest_1, "semantic_projection": projection_1},
        ),
        digest_1,
    )
