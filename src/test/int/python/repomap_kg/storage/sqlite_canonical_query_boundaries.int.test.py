"""Guarded SQLite Local boundary contracts for canonical queries and edge explanation."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from repomap_kg.storage import StorageSchemaError
from repomap_kg.storage.sqlite_local.queries import (
    canonical_edge_explanation,
    canonical_edges,
    canonical_neighborhood,
    canonical_nodes,
)
from repomap_kg.storage.sqlite_local.schema import PUBLICATION_ABSENT, LocalStoreError
from repomap_test_support.navigation_search_fixtures import BETA_DOC, GRAPH, navigation_home
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, refusal, structured, tool


def test_canonical_nodes_by_key_and_prefix_and_window_boundaries(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database) as connection:
        # Exact canonical_key lookup:
        by_key = canonical_nodes(
            connection, kind=None, canonical_key=BETA_DOC, path_prefix=None,
            graph_key_version=1, limit=10, offset=0,
        )
        assert len(by_key) == 1 and by_key[0].canonical_key == BETA_DOC

        # Non-existent canonical_key:
        absent_key = canonical_nodes(
            connection, kind=None, canonical_key="doc.page:nonexistent", path_prefix=None,
            graph_key_version=1, limit=10, offset=0,
        )
        assert absent_key == ()

        # Prefix lookup:
        by_prefix = canonical_nodes(
            connection, kind=None, canonical_key=None, path_prefix="root/docs/",
            graph_key_version=1, limit=20, offset=0,
        )
        assert by_prefix and all(node.canonical_key.startswith("file:root/docs/") for node in by_prefix)

        # Window validation: limit required when offset is non-zero:
        with pytest.raises(StorageSchemaError, match="limit is required when offset is non-zero"):
            canonical_nodes(
                connection, kind=None, canonical_key=None, path_prefix=None,
                graph_key_version=1, limit=None, offset=5,
            )

        # Window validation: negative offset:
        with pytest.raises(StorageSchemaError, match="offset must be a non-negative integer"):
            canonical_nodes(
                connection, kind=None, canonical_key=None, path_prefix=None,
                graph_key_version=1, limit=10, offset=-1,
            )

    # MCP boundary checks over stdio harness:
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [
        initialize(),
        tool(2, "repomap_canonical_nodes", {"project": GRAPH, "limit": 0}),
        tool(3, "repomap_canonical_nodes", {"project": GRAPH, "limit": 10, "offset": -1}),
        tool(4, "repomap_canonical_nodes", {"project": GRAPH, "limit": 2}),
    ]
    responses = harness.mcp(home, requests)
    assert "limit must be between 1 and 200" in refusal(responses, 2)
    assert "offset must be a non-negative integer" in refusal(responses, 3)
    valid = structured(responses, 4)
    assert len(valid["items"]) == 2
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_canonical_edge_explanation_and_missing_edge_boundary(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database) as connection:
        # Explanation for missing edge:
        missing_exp = canonical_edge_explanation(
            connection, graph_key_version=1,
            source_key="doc.page:absent_source",
            kind="references",
            target_key="doc.page:absent_target",
            identity_metadata_hash="0000000000000000000000000000000000000000000000000000000000000000",
            evidence_limit=10, evidence_offset=0,
        )
        assert missing_exp.edge is None
        assert missing_exp.evidence == ()

        # Explanation for an existing edge:
        edge_row = connection.execute(
            "SELECT source_canonical_key, target_canonical_key, edge_kind, identity_metadata_hash "
            "FROM canonical_edges WHERE graph_key_version = 1 LIMIT 1"
        ).fetchone()
        assert edge_row is not None
        present_exp = canonical_edge_explanation(
            connection, graph_key_version=1,
            source_key=edge_row[0],
            kind=edge_row[2],
            target_key=edge_row[1],
            identity_metadata_hash=edge_row[3],
            evidence_limit=10, evidence_offset=0,
        )
        assert present_exp.edge is not None
        assert present_exp.edge.source_key == edge_row[0]

    # Stdio MCP verification: missing edge explanation returns edge: None:
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [
        initialize(),
        tool(2, "repomap_explain_canonical_edge", {
            "project": GRAPH,
            "source_key": "doc.page:absent_source",
            "kind": "references",
            "target_key": "doc.page:absent_target",
            "identity_metadata": {},
        }),
        tool(3, "repomap_canonical_edges", {"project": GRAPH, "limit": 1}),
    ]
    responses = harness.mcp(home, requests)
    exp_result = structured(responses, 2)["result"]
    assert exp_result["edge"] is None and exp_result["evidence"] == []
    edges_result = structured(responses, 3)
    assert len(edges_result["items"]) == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_canonical_neighborhood_refused_directions_depth_and_windows(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database) as connection:
        # Refused depth != 1:
        with pytest.raises(StorageSchemaError, match="storage neighborhood only supports depth 1"):
            canonical_neighborhood(
                connection, node=BETA_DOC, direction="both", depth=2,
                graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
            )

        # Refused direction:
        with pytest.raises(StorageSchemaError, match="neighborhood direction must be one of both, in, out"):
            canonical_neighborhood(
                connection, node=BETA_DOC, direction="diagonal", depth=1,
                graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
            )

        # Direction in and out:
        in_neigh = canonical_neighborhood(
            connection, node=BETA_DOC, direction="in", depth=1,
            graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
        )
        assert in_neigh.center is not None and in_neigh.center.canonical_key == BETA_DOC

        out_neigh = canonical_neighborhood(
            connection, node=BETA_DOC, direction="out", depth=1,
            graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
        )
        assert out_neigh.center is not None and out_neigh.center.canonical_key == BETA_DOC

        # Absent node:
        absent = canonical_neighborhood(
            connection, node="doc.page:absent_node", direction="both", depth=1,
            graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
        )
        assert absent.center is None and absent.nodes == () and absent.edges == ()

        # Window validation:
        with pytest.raises(StorageSchemaError, match="limit is required when offset is non-zero"):
            canonical_neighborhood(
                connection, node=BETA_DOC, direction="both", depth=1,
                graph_key_version=1, node_limit=None, node_offset=2, edge_limit=10, edge_offset=0,
            )

    # MCP refusal continuity:
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [
        initialize(),
        tool(2, "repomap_canonical_neighborhood", {"project": GRAPH, "node": BETA_DOC, "depth": 2}),
        tool(3, "repomap_canonical_neighborhood", {"project": GRAPH, "node": BETA_DOC, "direction": "diagonal"}),
        tool(4, "repomap_canonical_neighborhood", {"project": GRAPH, "node": BETA_DOC, "direction": "both"}),
    ]
    responses = harness.mcp(home, requests)
    assert "storage neighborhood only supports depth 1" in refusal(responses, 2)
    assert "direction must be one of both, in, out" in refusal(responses, 3)
    valid = structured(responses, 4)["result"]
    assert valid["center"]["canonical_key"] == BETA_DOC
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_sqlite_publication_absent_storage_refusal(tmp_path: Path) -> None:
    _home, database = navigation_home(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM accepted_publication")
        with pytest.raises(LocalStoreError, match=PUBLICATION_ABSENT):
            canonical_nodes(
                connection, kind=None, canonical_key=None, path_prefix=None,
                graph_key_version=1, limit=10, offset=0,
            )
        with pytest.raises(LocalStoreError, match=PUBLICATION_ABSENT):
            canonical_edges(
                connection, source_key=None, kind=None, target_key=None,
                graph_key_version=1, limit=10, offset=0,
            )
        with pytest.raises(LocalStoreError, match=PUBLICATION_ABSENT):
            canonical_neighborhood(
                connection, node=BETA_DOC, direction="both", depth=1,
                graph_key_version=1, node_limit=10, node_offset=0, edge_limit=10, edge_offset=0,
            )
