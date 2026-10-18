import json
import copy
from unittest.mock import patch

import pytest

from repomap_kg.storage import (
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    JSFrameworkSummaryRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    TerraformSummaryRecord,
)

from repomap_test_support.mcp_server import McpServerTestSupport


@pytest.fixture
def endpoint_home(tmp_path, monkeypatch):
    from repomap_test_support.related_context_fixtures import related_home

    home, _, _ = related_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    return home


def _endpoint_node(key):
    return dict(canonical_key=key, graph_key_version=1)


def _endpoint_fixture():
    """Synthetic negative/privacy mutations, never claimed as stored relations."""
    return dict(center=_endpoint_node("python.module:a"),
        nodes=[_endpoint_node("python.module:b")],
        edges=[dict(source_key="python.module:a", target_key="python.module:b",
                    graph_key_version=1, edge_kind="imports", metadata={}, identity_metadata={})])


def _endpoint_call(monkeypatch, payload):
    from repomap_kg.server import mcp, _ops_summaries

    monkeypatch.setattr(_ops_summaries, "canonical_neighborhood_to_jsonable",
                        lambda record: copy.deepcopy(payload))
    reply = mcp.handle_tool_call("repomap_neighborhood",
        dict(graph_id="related", node="python.module:pkg.alpha", direction="out"))
    assert json.loads(reply["content"][0]["text"]) == reply["structuredContent"]
    return reply["structuredContent"]["result"]


@pytest.mark.parametrize("field,value", [
    ("privacy", "private-ops"), ("privacy", "unknown"), ("privacy", None),
    ("private", True), ("private", None), ("mcp_visible", False),
    ("mcp_visible", None), ("enabled", False), ("enabled", None),
    ("graph_id", "another-graph"),
])
def test_neighborhood_noneligible_public_facts_keep_exact_redaction(
    endpoint_home, monkeypatch, field, value,
):
    from repomap_kg.server import ops
    from repomap_kg.server._ops_sanitization import sanitize_jsonable

    original = ops.graph_payload
    def facts(*args, **kwargs):
        public = original(*args, **kwargs)
        if value is None:
            public.pop(field, None)
        else:
            public[field] = value
        return public
    monkeypatch.setattr(ops, "graph_payload", facts)
    raw = _endpoint_fixture()
    assert _endpoint_call(monkeypatch, raw) == sanitize_jsonable(raw)


@pytest.mark.parametrize("privacy", ["private-ops", "private-config", "sensitive-local"])
def test_neighborhood_actual_private_selection_keeps_endpoints_withheld(
    endpoint_home, monkeypatch, privacy,
):
    from repomap_kg.server._ops_sanitization import sanitize_jsonable

    config = endpoint_home / "repomap.rp.toml"
    config.write_text(config.read_text().replace('privacy = "public-dev"', f'privacy = "{privacy}"'))
    raw = _endpoint_fixture()
    assert _endpoint_call(monkeypatch, raw) == sanitize_jsonable(raw)


def test_neighborhood_private_source_binding_refuses_public_graph_projection(endpoint_home, monkeypatch):
    from dataclasses import replace
    from repomap_kg.server import ops
    from repomap_kg.server._ops_sanitization import sanitize_jsonable

    original = ops.configured_graph
    def selected(*args, **kwargs):
        target = original(*args, **kwargs)
        graph = target.selection.graph
        binding = replace(graph.effective_source_bindings[0], privacy="private-ops")
        graph = replace(graph, source_bindings=(binding,), explicit_source_bindings=True)
        return replace(target, selection=replace(target.selection, graph=graph))
    monkeypatch.setattr(ops, "configured_graph", selected)
    raw = _endpoint_fixture()
    assert _endpoint_call(monkeypatch, raw) == sanitize_jsonable(raw)


@pytest.mark.parametrize("field", ["source_key", "target_key"])
@pytest.mark.parametrize("candidate", [
    "python.module:unseen", "[REDACTED]", "[private-path]", "[graph-root]",
    "python.module:x...[truncated]", None, 4, {"canonical_key": "python.module:b"},
    "/synthetic/private/file", "file:///synthetic/private/file", "https://example.invalid/path",
    "mailto:synthetic@example.invalid", "C:\\synthetic\\private", "python.module:a/b",
    "python.module:token=synthetic-secret", "python.module:" + "x" * 600,
    "unlisted.namespace:visible", "doc.page:file%3aroot%2fdocs%2fguide.md",
])
def test_neighborhood_placeholder_unsafe_mutated_and_unseen_endpoint_refusal(
    endpoint_home, monkeypatch, candidate, field,
):
    raw = _endpoint_fixture()
    known = "target_key" if field == "source_key" else "source_key"
    expected = raw["edges"][0][known]
    raw["edges"][0][field] = candidate
    if candidate != "python.module:unseen":
        raw["nodes"].append(_endpoint_node(candidate))
    result = _endpoint_call(monkeypatch, raw)
    assert result["edges"][0][known] == expected
    assert result["edges"][0][field] == "[REDACTED]"


@pytest.mark.parametrize("change", ["center", "nodes", "edges", "missing-field", "version"])
def test_neighborhood_malformed_and_short_windows_refuse_without_guessing(
    endpoint_home, monkeypatch, change,
):
    from repomap_kg.server._ops_sanitization import sanitize_jsonable

    raw = _endpoint_fixture()
    if change in {"center", "nodes", "edges"}:
        raw[change] = None if change != "edges" else [None, raw["edges"][0]]
    elif change == "missing-field":
        del raw["edges"][0]["target_key"]
    else:
        raw["edges"][0]["graph_key_version"] = 2
    result = _endpoint_call(monkeypatch, raw)
    expected = sanitize_jsonable(raw)
    if change == "missing-field":
        expected["edges"][0]["source_key"] = "python.module:a"
    assert result == expected
    # A short backend window proves the center endpoint independently of its absent peer.
    raw = _endpoint_fixture()
    raw["nodes"] = []
    result = _endpoint_call(monkeypatch, raw)
    assert result["edges"][0]["source_key"] == "python.module:a"
    assert result["edges"][0]["target_key"] == "[REDACTED]"


def test_neighborhood_own_record_alignment_self_loops_and_nested_redaction(endpoint_home, monkeypatch):
    from repomap_kg.server import _ops_summaries
    from repomap_kg.server._ops_sanitization import sanitize_jsonable

    raw = _endpoint_fixture()
    edge = raw["edges"][0]
    edge["metadata"] = {"source_key": "python.module:a", "target_key": "python.module:b"}
    raw["edges"] += [dict(edge, source_key="python.module:b", target_key="python.module:a"),
                     dict(edge, target_key="python.module:a")]
    original = copy.deepcopy(raw)
    result = _endpoint_call(monkeypatch, raw)
    assert [(e["source_key"], e["target_key"]) for e in result["edges"]] == [
        ("python.module:a", "python.module:b"), ("python.module:b", "python.module:a"),
        ("python.module:a", "python.module:a")]
    assert all(e["metadata"] == {"source_key": "[REDACTED]", "target_key": "[REDACTED]"}
               for e in result["edges"])
    assert raw == original
    # Disclosed projection mutations check observable reordering/length drift.
    raw["edges"][0]["edge_kind"] = "first"
    for mode in ("reverse", "short"):
        def altered(value, **kwargs):
            public = sanitize_jsonable(value, **kwargs)
            if isinstance(public, dict) and "edges" in public:
                public["edges"] = (public["edges"][::-1] if mode == "reverse" else public["edges"][:1])
            return public
        monkeypatch.setattr(_ops_summaries, "sanitize_jsonable", altered)
        assert _endpoint_call(monkeypatch, raw) == altered(raw)


def test_neighborhood_key_versions_and_responses_are_never_joined(endpoint_home, monkeypatch):
    raw = _endpoint_fixture()
    raw["nodes"][0]["graph_key_version"] = 2
    assert _endpoint_call(monkeypatch, raw)["edges"][0]["target_key"] == "[REDACTED]"
    raw["nodes"] = []
    assert _endpoint_call(monkeypatch, raw)["edges"][0]["target_key"] == "[REDACTED]"
    raw = _endpoint_fixture()
    raw["edges"][0]["target_key"] = "python.module:B"
    assert _endpoint_call(monkeypatch, raw)["edges"][0]["target_key"] == "[REDACTED]"


def test_neighborhood_sanitizer_changed_identity_stays_withheld(endpoint_home, monkeypatch):
    from pathlib import Path

    raw = _endpoint_fixture()
    candidate = "python.module:" + Path.home().name
    raw["nodes"][0]["canonical_key"] = candidate
    raw["edges"][0]["target_key"] = candidate
    result = _endpoint_call(monkeypatch, raw)
    assert result["nodes"][0]["canonical_key"] == "[private-path]"
    assert result["edges"][0]["source_key"] == "python.module:a"
    assert result["edges"][0]["target_key"] == "[REDACTED]"


def _make_record(cls, **kwargs):
    rec = cls.__new__(cls)
    rec.__dict__.update(kwargs)
    return rec


class McpServerPrivatePayloadRedactionDomainsUnitTests(McpServerTestSupport):
    def test_mcp_harden3_private_graph_payloads_never_serialize_private_roots(
        self,
    ):
        from repomap_kg.server.mcp import (
            repomap_graph_status,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_projects,
            repomap_search_files,
        )
        from repomap_kg.ops.refresh import OpsRefreshGraphStatus

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        private_status = OpsRefreshGraphStatus(
            graph_id="private-visible",
            repository_name="private-visible",
            privacy="private-ops",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            repository_exists=True,
            latest_run_id=88,
            latest_run_status="complete",
            latest_run_started_at="2026-07-01T00:00:00Z",
            latest_run_finished_at="2026-07-01T00:01:00Z",
            raw_observations=3,
            canonical_nodes=2,
            canonical_edges=1,
        )
        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:private.visible",
                graph_key_version=1,
                kind="python.module",
                display_name="private.visible",
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
            ("list_graphs", None, None, repomap_list_graphs, lambda p: p["graphs"][1], True),
            ("projects_hint", None, None, repomap_projects, lambda p: {g["graph_id"]: g for g in p["graphs"]}["private-visible"], False),
            ("graph_status", "repomap_kg.server.ops.query_refresh_status", {"private-visible": private_status},
             lambda: repomap_graph_status(graph_id="private-visible"), lambda p: p["graph"], True),
            ("neighborhood", "repomap_kg.server.ops.query_canonical_neighborhood", neighborhood,
             lambda: repomap_neighborhood(graph_id="private-visible", node="python.module:private.visible"), lambda p: p["graph"], True),
            ("search_files", "repomap_kg.server.ops.query_mcp_search", {"results": [{"path": "src/private_visible.py", "metadata": {"origin": "synthetic-fixture"}}], "total": 1},
             lambda: repomap_search_files(graph_id="private-visible", query="private"), lambda p: p["graph"], True),
        ]

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            for label, patch_target, patch_val, call_fn, get_graph, read_only in cases:
                with self.subTest(tool=label):
                    if patch_target is None:
                        payload = call_fn()
                    else:
                        with patch(patch_target, return_value=patch_val):
                            payload = call_fn()
                    if read_only:
                        self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(get_graph(payload))
                    self.assert_no_synthetic_private_root(payload)

    def test_mcp_harden3_private_summary_roots_are_redacted_across_domains(
        self,
    ):
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )

        config_path = self.write_visible_ops_config()
        secret_token = "mcp-harden3-secret-value"
        credentialed_url = "https://user:password@example.invalid/private.git"
        nested_sensitive_metadata = {
            "root_path": "synthetic-private-root",
            "root_path_display": "synthetic-private-root",
            "root_path_expanded": "synthetic-private-root",
            "api_key": secret_token,
            "repository_url": credentialed_url,
        }
        cases = [
            ("python", "repomap_kg.server.ops.query_python_summary", _make_record(
                PythonSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", python_observations=3,
                package_files={"pyproject": 1}, packaging={}, tests={}, frameworks={}, references={}, redactions={},
                diagnostics=nested_sensitive_metadata, generic_python={}, generic_config={"source": nested_sensitive_metadata},
                dogfooding={}, safety={"no_execution": True},
            ), lambda: repomap_python_summary(graph_id="private-visible")),
            ("terraform", "repomap_kg.server.ops.query_terraform_summary", _make_record(
                TerraformSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", terraform_observations=4,
                terraform_files=2, file_families={}, terraform={}, references={}, tfvars={"sensitive": nested_sensitive_metadata},
                redactions={}, diagnostics=nested_sensitive_metadata, generic_config={}, safety={"no_execution": True},
            ), lambda: repomap_terraform_summary(graph_id="private-visible")),
            ("openapi", "repomap_kg.server.ops.query_openapi_summary", _make_record(
                OpenAPISummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", openapi_observations=5,
                openapi_documents=1, spec_families={"openapi3": 1}, openapi={}, methods={}, references={"source": nested_sensitive_metadata},
                redactions={}, diagnostics={}, generic_config={}, safety={"no_fetch": True},
            ), lambda: repomap_openapi_summary(graph_id="private-visible")),
            ("js_framework", "repomap_kg.server.ops.query_js_framework_summary", _make_record(
                JSFrameworkSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", framework_observations=6,
                framework_profiles={"node": 1}, node=nested_sensitive_metadata, express={}, nest={}, next={}, jest={}, jquery={},
                generic_js={}, diagnostics={}, safety={"no_execution": True},
            ), lambda: repomap_js_framework_summary(graph_id="private-visible")),
        ]

        with self.patch_ops_config(config_path):
            for label, patch_target, patch_val, call_fn in cases:
                with self.subTest(summary=label):
                    with patch(patch_target, return_value=patch_val):
                        payload = call_fn()
                    self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(payload["graph"])
                    self.assertEqual(payload["summary"]["root_path"], "[private-root]")
                    self.assert_no_synthetic_private_root(payload, secret_token, credentialed_url)

    def test_mcp_harden3_search_payloads_redact_secret_like_metadata(self):
        from repomap_kg.server.mcp import (
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
        )

        config_path = self.write_visible_ops_config()
        secret_token = "mcp-harden3-secret-value"
        credentialed_url = "https://user:password@example.invalid/private.git"
        nodes_payload = {
            "results": [{"canonical_key": "python.module:private.visible", "kind": "python.module", "display_name": "private.visible",
                         "metadata": {"api_key": secret_token, "repository_url": credentialed_url}}],
            "total": 1,
        }
        obs_payload = {
            "results": [{"ordinal": 1, "kind": "command.reference", "path": "synthetic/private.txt",
                         "source_id": "synthetic/private.txt#command:1",
                         "metadata": {"token": secret_token, "repository_url": credentialed_url, "raw": "synthetic public command text"}}],
            "total": 1,
        }
        files_payload = {
            "results": [{"path": "src/private_visible.py", "language": "python",
                         "metadata": {"password": secret_token, "repository_url": credentialed_url}}],
            "total": 1,
        }
        cases = [
            ("nodes", lambda: repomap_search_nodes(graph_id="private-visible", query="private"), nodes_payload, None),
            ("observations", lambda: repomap_search_observations(graph_id="private-visible", query="command", include_raw=False), obs_payload, False),
            ("files", lambda: repomap_search_files(graph_id="private-visible", query="private"), files_payload, None),
        ]

        with self.patch_ops_config(config_path):
            for target_name, call_fn, ret_payload, include_raw in cases:
                with self.subTest(target=target_name):
                    with patch("repomap_kg.server.ops.query_mcp_search", return_value=ret_payload) as query:
                        payload = call_fn()
                    self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(payload["graph"])
                    self.assertEqual(payload["target"], target_name)
                    self.assertEqual(payload["result_count"], 1)
                    self.assert_no_synthetic_private_root(payload, secret_token, credentialed_url)
                    self.assertIn("[REDACTED]", json.dumps(payload, sort_keys=True))
                    if include_raw is not None:
                        self.assert_raw_payload_policy(payload, include_raw=bool(include_raw))
                        self.assertFalse(query.call_args.kwargs["include_raw"])
