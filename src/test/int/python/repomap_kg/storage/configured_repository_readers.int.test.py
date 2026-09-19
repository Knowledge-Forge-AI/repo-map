"""PostgreSQL matrix for every configured canonical/source reader (ADR 0068)."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from repomap_kg.storage import StorageSchemaError, apply_migrations, default_rdbms_root, run_psql
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_kg.storage.sql_canonical import (
    build_canonical_edge_query_sql,
    build_canonical_neighborhood_query_sql,
    build_canonical_node_query_sql,
    build_canonical_storage_summary_query_sql,
    build_explain_canonical_edge_query_sql,
)
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.sql_sources import (
    build_ingested_source_query_sql,
    build_source_feed_item_explanation_query_sql,
    build_source_feed_item_query_sql,
    build_source_reference_query_sql,
    build_source_run_query_sql,
    build_source_summary_query_sql,
)
from repomap_test_support.postgres_harness import temporary_postgres


ROOT = "/workspace/fixture"
IDENTITY = "repo1:fixture"
ITEM = "feed.item:shared"
HASH = "0" * 64


def _execute(database, sql):
    run_psql(
        [database.psql_command, *database.psql_args, "-X", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )


def _insert_repository(database, repository_id, marker, root, identity):
    """Give both repositories identical keys but distinguishable content."""
    metadata = sql_literal(json.dumps({
        "source_id_configured": "fixture-feed", "source_type": "feed.rss",
        "source_display_name": marker, "source_policy_status": "allowed",
        "source_run_id": marker, "source_artifact_id": marker,
        "source_artifact_path": marker + ".xml",
    }))
    node_metadata = sql_literal(json.dumps({"title": marker, "marker": marker}))
    edge_metadata = sql_literal(json.dumps({"scope": "link", "marker": marker}))
    quoted_identity = "NULL" if identity is None else sql_literal(identity)
    n = repository_id * 10
    _execute(database, f"""
INSERT INTO repositories(id, name, root_path, repository_identity)
VALUES ({repository_id}, '{marker}', {sql_literal(root)}, {quoted_identity});
INSERT INTO runs(id, repository_id, status) VALUES ({repository_id}, {repository_id}, 'complete');
INSERT INTO raw_observations
    (id, repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash)
VALUES ({repository_id}, {repository_id}, {repository_id}, 0, 1, 'feed.item', 'fixture-feed',
        'feed.xml', jsonb_build_object('metadata', {metadata}::jsonb), repeat('0', 64));
INSERT INTO canonical_nodes
    (id, repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
VALUES
    ({n}, {repository_id}, 1, '{ITEM}', 'feed.item', '{marker}', {node_metadata}::jsonb, 'extracted'),
    ({n+1}, {repository_id}, 1, 'feed.author:shared', 'feed.author', '{marker}', '{{}}', 'extracted'),
    ({n+2}, {repository_id}, 1, 'feed.category:shared', 'feed.category', '{marker}', '{{}}', 'extracted');
INSERT INTO canonical_edges
    (id, repository_id, graph_key_version, source_canonical_key, edge_kind,
     target_canonical_key, identity_metadata_hash, metadata_json, confidence)
VALUES
    ({n}, {repository_id}, 1, '{ITEM}', 'references', 'external.url:{marker}', '{HASH}', {edge_metadata}::jsonb, 'extracted'),
    ({n+1}, {repository_id}, 1, '{ITEM}', 'references', 'feed.author:shared', '{HASH}', '{{}}', 'extracted'),
    ({n+2}, {repository_id}, 1, '{ITEM}', 'references', 'feed.category:shared', '{HASH}', '{{}}', 'extracted');
INSERT INTO canonical_evidence
    (id, repository_id, run_id, graph_key_version, raw_observation_id, evidence_key,
     raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path,
     extractor, extractor_version, confidence, metadata_json)
VALUES ({repository_id}, {repository_id}, {repository_id}, 1, {repository_id}, 'evidence:shared',
        0, 1, 'feed.item', 'fixture-feed', 'feed.xml', 'fixture', '1', 'extracted', {node_metadata}::jsonb);
INSERT INTO canonical_node_evidence(canonical_node_id, canonical_evidence_id, link_kind)
VALUES ({n}, {repository_id}, 'extracted');
INSERT INTO canonical_edge_evidence(canonical_edge_id, canonical_evidence_id, link_kind)
VALUES ({n}, {repository_id}, 'extracted'), ({n+1}, {repository_id}, 'extracted'),
       ({n+2}, {repository_id}, 'extracted');
""")


def _read_all(database, root, marker):
    """Execute all eleven underlying queries with the same configured identity."""
    builders: dict[str, tuple[str, Literal["object", "array"]]] = {
        "status": (build_canonical_storage_summary_query_sql(root, repository_identity=IDENTITY), "object"),
        "nodes": (build_canonical_node_query_sql(root, repository_identity=IDENTITY), "array"),
        "edges": (build_canonical_edge_query_sql(root, repository_identity=IDENTITY), "array"),
        "edge_explanation": (build_explain_canonical_edge_query_sql(
            root, source_key=ITEM, kind="references", target_key="external.url:" + marker,
            identity_metadata_hash=HASH, repository_identity=IDENTITY,
        ), "object"),
        "neighborhood": (build_canonical_neighborhood_query_sql(root, node=ITEM, repository_identity=IDENTITY), "object"),
        "sources": (build_ingested_source_query_sql(root, repository_identity=IDENTITY), "array"),
        "summary": (build_source_summary_query_sql(root, source_id="fixture-feed", repository_identity=IDENTITY), "object"),
        "runs": (build_source_run_query_sql(root, source_id="fixture-feed", repository_identity=IDENTITY), "array"),
        "items": (build_source_feed_item_query_sql(root, source_id="fixture-feed", repository_identity=IDENTITY), "array"),
        "item_explanation": (build_source_feed_item_explanation_query_sql(root, item_key=ITEM, source_id="fixture-feed", repository_identity=IDENTITY), "object"),
        "references": (build_source_reference_query_sql(root, source_id="fixture-feed", repository_identity=IDENTITY), "array"),
    }
    return {
        name: execute_json_readback(
            sql, psql_args=database.psql_args, psql_command=database.psql_command,
            label=name, expected_shape=shape,
        )
        for name, (sql, shape) in builders.items()
    }


def _assert_selected(database, root, marker, excluded):
    results = _read_all(database, root, marker)
    for name, result in results.items():
        encoded = json.dumps(result)
        assert marker in encoded, (name, result)
        assert excluded not in encoded, (name, result)
    assert len(results["nodes"]) == 3
    assert len(results["edges"]) == 3
    assert len(results["edge_explanation"]["evidence"]) == 1
    assert len(results["items"]) == 1
    assert results["items"][0]["authors"] == [marker]
    assert results["items"][0]["categories"] == [marker]
    assert results["items"][0]["link_targets"] == ["external.url:" + marker]
    assert len(results["item_explanation"]["references"]) == 3
    assert len(results["references"]) == 3


def _assert_empty(database, root):
    results = _read_all(database, root, "current")
    for name in ("nodes", "edges", "sources", "runs", "items", "references"):
        assert results[name] == [], name
    assert results["edge_explanation"] == {"edge": None, "evidence": []}
    assert results["neighborhood"]["center"] is None
    assert results["item_explanation"]["item"] is None
    assert results["item_explanation"]["evidence"] == []
    assert results["item_explanation"]["references"] == []
    assert results["summary"]["feed_items"] == 0
    assert "legacy" not in json.dumps(results)


def test_all_configured_readers_keep_identity_across_portable_and_relocated_roots():
    with temporary_postgres() as database:
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
        _insert_repository(database, 20, "current", "graph:fixture", IDENTITY)
        _assert_selected(database, ROOT, "current", "legacy")
        with pytest.raises(StorageSchemaError, match="duplicate key"):
            _execute(database, """
INSERT INTO repositories(name, root_path, repository_identity)
VALUES ('collision', '/workspace/collision', 'repo1:fixture');
""")

        # Lower-ID legacy content with colliding keys cannot leak into current data.
        _insert_repository(database, 10, "legacy", ROOT, None)
        _assert_selected(database, ROOT, "current", "legacy")
        _assert_selected(database, "/workspace/relocated-config", "current", "legacy")
        _execute(database, "UPDATE repositories SET root_path = '/workspace/stored-b' WHERE id = 20;")
        _assert_selected(database, ROOT, "current", "legacy")

        # Content filtering must not cause selection to fall back to the legacy row.
        _execute(database, """
DELETE FROM canonical_edges WHERE repository_id = 20;
DELETE FROM canonical_nodes WHERE repository_id = 20;
DELETE FROM canonical_evidence WHERE repository_id = 20;
DELETE FROM raw_observations WHERE repository_id = 20;
""")
        _assert_empty(database, ROOT)
        _execute(database, "DELETE FROM repositories WHERE id = 20;")
        _assert_selected(database, ROOT, "legacy", "current")

        # An unrelated identity at the physical root is ineligible as fallback.
        _execute(database, "UPDATE repositories SET repository_identity = 'repo1:unrelated' WHERE id = 10;")
        _assert_empty(database, ROOT)
