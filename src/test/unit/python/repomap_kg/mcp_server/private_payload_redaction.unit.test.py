import json
import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    JSFrameworkSummaryRecord,
    CanonicalStorageSummaryRecord,
)

from repomap_test_support.mcp_server import McpServerTestSupport


@pytest.mark.parametrize("center,direction,expected", [
    ("python.module:pkg.alpha", "out", "imports"),
    ("python.module:pkg.beta", "in", "imports"),
    ("python.module:pkg.alpha", "both", "imports"),
    ("doc.page:file%3Aroot%2Fdocs%2Fstart.md", "out", "links_to"),
])
def test_public_neighborhood_real_endpoints_and_unchanged_sanitization(
    tmp_path, monkeypatch, center, direction, expected,
):
    from repomap_kg.server import mcp, ops, _ops_summaries
    from repomap_kg.server._ops_sanitization import sanitize_jsonable
    from repomap_test_support.related_context_fixtures import (
        EXPECTED_IMPORTS, EXPECTED_LINKS, GRAPH, related_home,
    )

    home, _, _ = related_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    selection = ops.configured_graph(GRAPH).selection
    markers = selection.path_markers
    args = dict(graph_id=GRAPH, node=center, direction=direction, depth=1)
    original = _ops_summaries.canonical_neighborhood_to_jsonable
    raw = []

    def capture(record):
        result = original(record)
        # Disclosed fixture mutation verifies nested fields stay under normal policy.
        result["center"]["metadata"] = {
            "source_key": center, "token": "synthetic-secret",
            "path": str(home), "url": "https://u:p@example.invalid/data",
            "source_id": "fixture/source", "long": "x" * 600,
            "graph_root": selection.graph.root_path_expanded,
            "config": selection.config_locations[0], "username": Path.home().name,
        }
        result["edges"][0]["identity_metadata"]["target_key"] = center
        raw.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(_ops_summaries, "canonical_neighborhood_to_jsonable", capture)
    reply = mcp.handle_tool_call("repomap_neighborhood", args)
    rpc = mcp.handle_jsonrpc_message(dict(jsonrpc="2.0", id=1, method="tools/call",
        params=dict(name="repomap_neighborhood", arguments=args)))
    assert rpc is not None
    assert rpc["result"] == reply
    payload = reply["structuredContent"]
    assert json.loads(reply["content"][0]["text"]) == payload
    relations = {(e["source_key"], e["edge_kind"], e["target_key"])
                 for e in payload["result"]["edges"] if e["edge_kind"] == expected}
    assert relations == (EXPECTED_IMPORTS if expected == "imports" else EXPECTED_LINKS)
    visible = {n["canonical_key"] for n in payload["result"]["nodes"]} | {center}
    assert all(s in visible and t in visible for s, _, t in relations)
    baseline = sanitize_jsonable(raw[0], private_markers=markers)
    withheld = copy.deepcopy(payload["result"])
    for edge in withheld["edges"]:
        edge["source_key"] = edge["target_key"] = "[REDACTED]"
    assert withheld == baseline
    assert all(payload["result"]["center"]["metadata"][field] == "[private-path]"
               for field in ("path", "graph_root", "config", "username"))
    assert payload["graph"]["private"] is False
    assert payload["graph"]["database"] == "[graph-database]"
    assert payload["graph"]["root_path_display"] == "[graph-root]"
    assert "synthetic-secret" not in json.dumps(payload)


@pytest.mark.parametrize("privacy", ["public-dev", "private-ops"])
@pytest.mark.parametrize("tool", ["repomap_canonical_edges", "repomap_canonical_neighborhood"])
@pytest.mark.parametrize("schema", [0, 1])
def test_legacy_canonical_routes_preserve_existing_endpoint_policy(
    tmp_path, monkeypatch, privacy, tool, schema,
):
    from repomap_kg.server import mcp, _ops_summaries
    from repomap_test_support.related_context_fixtures import (
        EXPECTED_IMPORTS, GRAPH, MODULE, related_home,
    )

    home, _, _ = related_home(tmp_path)
    config = home / "repomap.rp.toml"
    config.write_text(config.read_text().replace('privacy = "public-dev"', f'privacy = "{privacy}"'))
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    def refuse_restoration(*args, **kwargs):
        pytest.fail("Legacy canonical tools must not use selected-graph endpoint restoration")
    monkeypatch.setattr(_ops_summaries, "_preserve_visible_endpoints", refuse_restoration)
    args = dict(project=GRAPH, result_schema_version=schema)
    args.update(dict(kind="imports") if tool.endswith("edges") else dict(node=MODULE, direction="out"))
    reply = mcp.handle_tool_call(tool, args)
    rpc = mcp.handle_jsonrpc_message(dict(jsonrpc="2.0", id=1, method="tools/call",
        params=dict(name=tool, arguments=args)))
    assert rpc is not None and rpc["result"] == reply
    payload = reply["structuredContent"]
    assert json.loads(reply["content"][0]["text"]) == payload
    result = payload["result"] if schema and tool.endswith("neighborhood") else payload
    edges = (payload["items"] if schema else payload) if tool.endswith("edges") else result["edges"]
    # Legacy canonical identity fields were already public, including private selections.
    assert {(e["source_key"], e["edge_kind"], e["target_key"]) for e in edges} == EXPECTED_IMPORTS
    assert all(e["metadata"] == {"imported_modules": ["pkg.beta"], "resolutions": ["local"]}
               for e in edges)


def _mixed_multi_source_ops_config() -> str:
    return (
        "schema_version = 1\n\n"
        "[service]\nmode = \"local\"\nmcp_transport = \"stdio\"\nlog_level = \"info\"\n\n"
        "[postgres]\nhost = \"127.0.0.1\"\nport = 5432\ndatabase = \"repomap\"\nuser = \"fixture\"\n\n"
        "[[graphs]]\nid = \"mixed\"\nname = \"Mixed Sources\"\nenabled = true\nmcp_visible = true\nrefresh_policy = \"manual\"\ndatabase = \"repomap_mixed\"\n\n"
        "[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = \"src1:public\"\nalias = \"public\"\nrevision = 1\nkind = \"folder\"\n"
        "root_path = \"~/.synthetic-public-source\"\nrepository_name = \"public-source\"\nlogical_root = \"public\"\nprivacy = \"public-dev\"\n"
        "evidence_retention = \"metadata-only\"\nextractor_profile = \"default\"\nresolution_policy = \"isolated\"\nrole = \"composition\"\ninput_name = \"public-input\"\nenabled = true\n\n"
        "[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = \"src1:private\"\nalias = \"private\"\nrevision = 1\nkind = \"folder\"\n"
        "root_path = \"/synthetic-private-source\"\nrepository_name = \"private-source\"\nlogical_root = \"private\"\nprivacy = \"private-ops\"\n"
        "evidence_retention = \"metadata-only\"\nextractor_profile = \"default\"\nresolution_policy = \"isolated\"\nrole = \"security\"\ninput_name = \"private-input\"\nenabled = true\n\n"
        "[server_memory]\nenabled = false\npath = \"disabled\"\nmode = \"read_only\"\n"
    )


class McpServerPrivatePayloadRedactionUnitTests(McpServerTestSupport):
    def test_mcp_multi_source_storage_routes_to_logical_graph_root(self):
        from repomap_kg.server.mcp import storage_connection

        config_path = self.write_ops_config(_mixed_multi_source_ops_config())

        with self.patch_ops_config(config_path):
            connection = storage_connection(project="mixed")

        self.assertEqual(connection.root_path, "graph:mixed")
        self.assertEqual(connection.root_path_display, "[private-root]")
        self.assertEqual(connection.project, "mixed")

    def test_mcp_private_markers_include_all_multi_source_binding_roots(self):
        from repomap_kg.server.mcp import storage_connection
        from repomap_kg.server.mcp_core import private_storage_payload
        from repomap_kg.server.ops import graph_context, readback_path_markers

        config_path = self.write_ops_config(_mixed_multi_source_ops_config())

        with self.patch_ops_config(config_path):
            context = graph_context("mixed")
            connection = storage_connection(project="mixed")
            markers = readback_path_markers(context)
            selection = connection.selection
            assert selection is not None
            self.assertEqual(set(selection.path_markers), set(markers))
            bindings = context.graph.effective_source_bindings
            for binding in bindings:
                self.assertIn(binding.root_path, markers)
                self.assertIn(binding.root_path_expanded, markers)

            injected_roots = [
                f"physical={binding.root_path}" for binding in bindings
            ] + [
                f"expanded={binding.root_path_expanded}" for binding in bindings
            ]
            payload = private_storage_payload(
                connection,
                {
                    "injected_roots": injected_roots,
                    "logical": {
                        "binding_id": bindings[0].binding_id,
                        "alias": bindings[0].alias,
                        "role": bindings[0].role,
                    },
                },
            )

        self.assertEqual(payload["injected_roots"], ["[private-path]"] * len(injected_roots))
        self.assertEqual(payload["logical"]["binding_id"], bindings[0].binding_id)
        self.assertEqual(payload["logical"]["alias"], bindings[0].alias)
        self.assertEqual(payload["logical"]["role"], bindings[0].role)

    def test_mcp_harden2_private_graph_payloads_redact_roots_across_tools(self):
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_project_summary,
            repomap_search_files,
        )

        config_path = self.write_visible_ops_config()
        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:private.app",
                graph_key_version=1,
                kind="python.module",
                display_name="private.app",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(),
            edges=(),
        )

        cases = [
            ("list_graphs", None, None, repomap_list_graphs, lambda p: p["graphs"][1], lambda p: self.assertTrue(p["graphs"][1]["warnings"])),
            ("project_summary", "repomap_kg.server.ops.query_canonical_storage_summary", CanonicalStorageSummaryRecord(
                root_path="synthetic-private-root", repository_name="private-visible", latest_run_id=44, runs=1, files=2,
                raw_observations=13, canonical_nodes=3, canonical_edges=4, canonical_evidence=5,
            ), lambda: repomap_project_summary(graph_id="private-visible"), lambda p: p["graph"], lambda p: self.assertEqual(p["summary"]["root_path"], "[private-root]")),
            ("js_framework_summary", "repomap_kg.server.ops.query_js_framework_summary", JSFrameworkSummaryRecord(
                root_path="synthetic-private-root", repository_name="private-visible", framework_observations=6, framework_profiles={"node": 1},
                node={}, express={}, nest={}, next={}, jest={}, jquery={}, generic_js={}, diagnostics={}, safety={"no_execution": True},
            ), lambda: repomap_js_framework_summary(graph_id="private-visible"), lambda p: p["graph"], lambda p: self.assertEqual(p["summary"]["root_path"], "[private-root]")),
            ("neighborhood", "repomap_kg.server.ops.query_canonical_neighborhood", neighborhood,
             lambda: repomap_neighborhood(graph_id="private-visible", node="python.module:private.app"), lambda p: p["graph"],
             lambda p: self.assertEqual(p["result"]["center"]["canonical_key"], "python.module:private.app")),
            ("search_files", "repomap_kg.server.ops.query_mcp_search", {"results": [{"path": "src/private_app.py", "language": "python"}], "total": 1},
             lambda: repomap_search_files(graph_id="private-visible", query="private"), lambda p: p["graph"], lambda p: self.assertEqual(p["result_count"], 1)),
        ]

        with self.patch_ops_config(config_path):
            for label, patch_target, patch_val, call_fn, get_graph, extra in cases:
                with self.subTest(tool=label):
                    if patch_target is None:
                        payload = call_fn()
                    else:
                        with patch(patch_target, return_value=patch_val):
                            payload = call_fn()
                    self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(get_graph(payload))
                    self.assert_no_synthetic_private_root(payload)
                    extra(payload)

    def test_smoke_harden2_mcp_private_graph_metadata_redacts_connection_values(
        self,
    ):
        from repomap_kg.server.mcp import (
            repomap_graph_status,
            repomap_js_framework_summary,
            repomap_list_graphs,
            repomap_project_summary,
            repomap_refresh_status,
        )
        from repomap_kg.ops.reports import OpsRefreshGraphStatus

        private_root = "/Users/synthetic-user/private-repo"
        synthetic_values = (
            private_root,
            "/home/synthetic-user/private-repo",
            "/private/tmp/synthetic/repo-map",
            "synthetic-user",
            "synthetic_private_user",
            "synthetic_private_database",
            "synthetic-private-host.invalid",
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db",
            "synthetic-secret-token",
        )
        ops_config_path = self.write_ops_config(
            f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "synthetic-private-host.invalid"
port = 5432
database = "synthetic_private_database"
user = "synthetic_private_user"
password_file = "/private/tmp/synthetic/repo-map/pgpass"
password = "synthetic-secret-token"

[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "{private_root}"
repository_name = "private-visible"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "/private/tmp/synthetic/repo-map/server-memory"
mode = "read_only"
"""
        )
        refresh_status = OpsRefreshGraphStatus(
            graph_id="private-visible",
            repository_name="private-visible",
            database="synthetic_private_database",
            privacy="private-ops",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            db_checked=True,
            repository_exists=True,
            latest_run_id=44,
            latest_run_status="complete",
            latest_run_started_at="2026-07-01T00:00:00Z",
            latest_run_finished_at="2026-07-01T00:01:00Z",
            raw_observations=5,
            canonical_nodes=4,
            canonical_edges=3,
        )
        storage_summary = CanonicalStorageSummaryRecord(
            root_path=private_root,
            repository_name="private-visible",
            latest_run_id=44,
            runs=1,
            files=2,
            raw_observations=13,
            canonical_nodes=3,
            canonical_edges=4,
            canonical_evidence=5,
        )
        js_framework_summary = JSFrameworkSummaryRecord(
            root_path=private_root,
            repository_name="private-visible",
            framework_observations=6,
            framework_profiles={"node": 1},
            node={},
            express={},
            nest={},
            next={},
            jest={},
            jquery={},
            generic_js={},
            diagnostics={},
            safety={"no_execution": True},
        )
        cases = (
            ("list_graphs", repomap_list_graphs, None, None, lambda p: p["graphs"][0]),
            ("graph_status", lambda: repomap_graph_status(graph_id="private-visible"), "repomap_kg.server.ops.query_refresh_status", {"private-visible": refresh_status}, lambda p: p["graph"]),
            ("refresh_status", lambda: repomap_refresh_status(graph_id="private-visible"), "repomap_kg.server.ops.query_refresh_status", {"private-visible": refresh_status}, lambda p: p["graphs"][0]),
            ("project_summary", lambda: repomap_project_summary(graph_id="private-visible"), "repomap_kg.server.ops.query_canonical_storage_summary", storage_summary, lambda p: p["graph"]),
            ("js_framework_summary", lambda: repomap_js_framework_summary(graph_id="private-visible"), "repomap_kg.server.ops.query_js_framework_summary", js_framework_summary, lambda p: p["graph"]),
        )

        with self.patch_ops_config(ops_config_path):
            for label, call_fn, patch_target, patch_val, get_graph in cases:
                with self.subTest(payload=label):
                    if patch_target is None:
                        payload = call_fn()
                    else:
                        with patch(patch_target, return_value=patch_val):
                            payload = call_fn()

                    self.assert_read_only_payload(payload)
                    graph_metadata = get_graph(payload)
                    if "private" in graph_metadata:
                        self.assert_private_graph_payload(graph_metadata)
                    else:
                        self.assertEqual(graph_metadata["graph_id"], "private-visible")
                        self.assertEqual(graph_metadata["privacy"], "private-ops")
                        self.assertEqual(
                            graph_metadata["root_path_display"],
                            "[private-root]",
                        )
                        self.assertEqual(
                            graph_metadata["root_path_expanded"],
                            "[private-root]",
                        )
                    self.assertEqual(
                        graph_metadata["database"],
                        "[private-database]",
                    )
                    serialized = json.dumps(payload, sort_keys=True)
                    self.assertIn("[private-root]", serialized)
                    for synthetic_value in synthetic_values:
                        self.assertNotIn(synthetic_value, serialized)
