import unittest
from dataclasses import replace

import pytest

from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.ops.refresh_graphs import _result_from_graph
from repomap_kg.ops.reports import (
    _private_safe_root_path_display,
    _status_from_graph,
    refresh_result_to_jsonable,
    refresh_status_to_jsonable,
)
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


@pytest.mark.parametrize('privacy', ['public-dev', 'private-ops', 'private-memory', 'private-config', 'sensitive-local'])
def test_existing_refresh_projection_distinguishes_root_privacy_from_config_path(tmp_path, privacy):
    """Characterize the current operator projection; no shareable mode is implied."""
    path = tmp_path / 'operator.toml'
    root = tmp_path / 'workspace'
    path.write_text(VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / 'private'))
    config = load_ops_config(path)
    graph = replace(config.graphs[0], privacy=privacy)
    config = replace(config, graphs=(graph,))
    result = _result_from_graph(graph, database='fixture', result='success', files=7)
    status = _status_from_graph(graph, database='fixture', repository_exists=True)
    payloads = (
        refresh_result_to_jsonable(config, (result,), command='refresh'),
        refresh_status_to_jsonable(config, {graph.id: status}),
    )
    expected = str(root) if privacy == 'public-dev' else '[private-root]'
    for payload in payloads:
        assert payload['config_path'] == str(path)
        row = payload['graphs'][0]
        assert row['root_path_display'] == expected
        assert row['root_path_expanded'] == expected
        assert row['graph_id'] == graph.id
        if privacy != 'public-dev':
            assert str(root) not in str(payload)
    assert payloads[0]['graphs'][0]['files'] == 7


def test_existing_refresh_projection_multi_source_empty_root_and_independent_config_path(tmp_path):
    """Characterize that multi-source bindings present empty root display, [multi-source] repository, and independent config_path."""
    path = tmp_path / "operator.toml"
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    path.write_text(
        f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"

[[graphs]]
id = "multi-graph"
name = "Multi Graph"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap"

[[graphs.source_bindings]]
schema_version = 1
binding_id = "{graph_source_binding_id('multi-graph', 'entry')}"
source_definition_id = "src1:entry"
alias = "entry"
revision = 1
kind = "folder"
root_path = "{entry}"
repository_name = "fixture-entry"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"
input_name = "entry"
exclude_paths = []

[[graphs.source_bindings]]
schema_version = 1
binding_id = "{graph_source_binding_id('multi-graph', 'composition')}"
source_definition_id = "src1:composition"
alias = "composition"
revision = 1
kind = "folder"
root_path = "{composition}"
repository_name = "fixture-composition"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"
input_name = "composition"
exclude_paths = []

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""
    )
    config = load_ops_config(path)
    graph = config.graphs[0]
    result = _result_from_graph(graph, database="repomap", result="success", files=2)
    status = _status_from_graph(graph, database="repomap", repository_exists=True)
    payloads = (
        refresh_result_to_jsonable(config, (result,), command="refresh"),
        refresh_status_to_jsonable(config, {graph.id: status}),
    )
    for payload in payloads:
        assert payload["config_path"] == str(path)
        row = payload["graphs"][0]
        assert row["graph_id"] == "multi-graph"
        assert row["repository_name"] == "[multi-source]"
        assert row["root_path_display"] == ""
        assert row["root_path_expanded"] == ""
        assert str(entry) not in str(payload)
        assert str(composition) not in str(payload)
    assert payloads[0]["graphs"][0]["files"] == 2

class OpsReportBoundariesUnitTests(unittest.TestCase):
    def test_private_safe_root_path_display(self):
        public_graph = OpsGraphConfig(
            id="g1",
            name="public_graph",
            root_path="/tmp/root",
            root_path_expanded="/tmp/root",
            repository_name="repo",
            privacy="public",
            enabled=True,
            mcp_visible=True,
            extractor_profile="default",
            refresh_policy="manual",
        )
        private_graph = OpsGraphConfig(
            id="g2",
            name="private_graph",
            root_path="/tmp/root",
            root_path_expanded="/tmp/root",
            repository_name="repo",
            privacy="private-ops",
            enabled=True,
            mcp_visible=True,
            extractor_profile="default",
            refresh_policy="manual",
        )
        self.assertEqual(_private_safe_root_path_display(public_graph, "/tmp/root/file.py"), "/tmp/root/file.py")
        self.assertEqual(_private_safe_root_path_display(private_graph, "/tmp/root/file.py"), "[private-root]")

if __name__ == "__main__":
    unittest.main()
