"""PostgreSQL matrix for every configured canonical/source reader (ADR 0068)."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from repomap_kg.storage import StorageSchemaError, apply_migrations, default_rdbms_root, run_psql
from repomap_kg.storage.canonical_readback_rows import (
    canonical_edge_evidence_record_from_storage_payload,
    canonical_edge_explanation_from_storage_payload,
    canonical_edge_record_from_storage_payload,
    canonical_neighborhood_from_storage_payload,
    canonical_node_record_from_storage_payload,
)
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
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
    ({n+2}, {repository_id}, 1, 'feed.category:shared', 'feed.category', '{marker}', '{{}}', 'extracted'),
    ({n+3}, {repository_id}, 1, 'external.url:{marker}', 'external.url', '{marker}', '{{}}', 'extracted');
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


def _assert_selected(database, root, marker, excluded, expected_run_id):
    results = _read_all(database, root, marker)
    for name, result in results.items():
        encoded = json.dumps(result)
        assert marker in encoded, (name, result)
        assert excluded not in encoded, (name, result)
    assert results["status"]["root_path"] == root
    assert results["status"]["repository_name"] == marker
    assert results["status"]["latest_run_id"] == expected_run_id
    assert (results["status"]["runs"], results["status"]["files"], results["status"]["raw_observations"], results["status"]["canonical_nodes"], results["status"]["canonical_edges"], results["status"]["canonical_evidence"]) == (1, 0, 1, 4, 3, 1)
    expected_nodes = [
        ("external.url:" + marker, "external.url", marker, {}),
        ("feed.author:shared", "feed.author", marker, {}),
        ("feed.category:shared", "feed.category", marker, {}),
        (ITEM, "feed.item", marker, {"title": marker, "marker": marker}),
    ]
    assert [(row["canonical_key"], row["kind"], row["display_name"], row["metadata"]) for row in results["nodes"]] == expected_nodes
    expected_edges = [
        (ITEM, "references", "external.url:" + marker, HASH, {"scope": "link", "marker": marker}),
        (ITEM, "references", "feed.author:shared", HASH, {}),
        (ITEM, "references", "feed.category:shared", HASH, {}),
    ]
    assert [(row["source_key"], row["edge_kind"], row["target_key"], row["identity_metadata_hash"], row["metadata"]) for row in results["edges"]] == expected_edges
    edge = results["edge_explanation"]["edge"]
    assert (edge["source_key"], edge["edge_kind"], edge["target_key"], edge["identity_metadata_hash"], edge["metadata"]) == expected_edges[0]
    assert len(results["edge_explanation"]["evidence"]) == 1
    evidence = results["edge_explanation"]["evidence"][0]
    assert (evidence["evidence_key"], evidence["link_kind"], evidence["path"], evidence["extractor"], evidence["extractor_version"], evidence["confidence"]) == ("evidence:shared", "extracted", "feed.xml", "fixture", "1", "extracted")
    assert evidence["metadata"] == {"title": marker, "marker": marker}
    assert evidence["raw_observation"] == {"run_id": expected_run_id, "ordinal": 0, "payload_hash": HASH, "kind": "feed.item", "source_id": "fixture-feed"}
    neighborhood = results["neighborhood"]
    center = neighborhood["center"]
    assert (center["canonical_key"], center["kind"], center["display_name"], center["metadata"]) == expected_nodes[-1]
    assert [(row["canonical_key"], row["kind"], row["display_name"], row["metadata"]) for row in neighborhood["nodes"]] == expected_nodes[:3]
    assert [(row["source_key"], row["edge_kind"], row["target_key"], row["identity_metadata_hash"], row["metadata"]) for row in neighborhood["edges"]] == expected_edges
    item = results["items"][0]
    assert (item["item_key"], item["title"], item["link_targets"], item["authors"], item["categories"], item["source_run_id"], item["artifact_id"], item["artifact_path"]) == (ITEM, marker, ["external.url:" + marker], [marker], [marker], marker, marker, marker + ".xml")
    assert [(row["source_item_key"], row["relation"], row["target_key"], row["source_run_id"], row["artifact_id"], row["artifact_path"]) for row in results["references"]] == [(ITEM, "references", target, marker, marker, marker + ".xml") for target in ("external.url:" + marker, "feed.author:shared", "feed.category:shared")]


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
        _assert_selected(database, ROOT, "current", "legacy", expected_run_id=20)
        with pytest.raises(StorageSchemaError, match="duplicate key"):
            _execute(database, """
INSERT INTO repositories(name, root_path, repository_identity)
VALUES ('collision', '/workspace/collision', 'repo1:fixture');
""")

        # Lower-ID legacy content with colliding keys cannot leak into current data.
        _insert_repository(database, 10, "legacy", ROOT, None)
        _assert_selected(database, ROOT, "current", "legacy", expected_run_id=20)
        _assert_selected(database, "/workspace/relocated-config", "current", "legacy", expected_run_id=20)
        _execute(database, "UPDATE repositories SET root_path = '/workspace/stored-b' WHERE id = 20;")
        _assert_selected(database, ROOT, "current", "legacy", expected_run_id=20)

        # Content filtering must not cause selection to fall back to the legacy row.
        _execute(database, """
DELETE FROM canonical_edges WHERE repository_id = 20;
DELETE FROM canonical_nodes WHERE repository_id = 20;
DELETE FROM canonical_evidence WHERE repository_id = 20;
DELETE FROM raw_observations WHERE repository_id = 20;
""")
        _assert_empty(database, ROOT)
        _execute(database, "DELETE FROM repositories WHERE id = 20;")
        _assert_selected(database, ROOT, "legacy", "current", expected_run_id=10)

        # An unrelated identity at the physical root is ineligible as fallback.
        _execute(database, "UPDATE repositories SET repository_identity = 'repo1:unrelated' WHERE id = 10;")
        _assert_empty(database, ROOT)


def test_canonical_reader_pagination_and_neighborhood_directions() -> None:
    with temporary_postgres() as database:
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
        _insert_repository(database, 20, "current", ROOT, IDENTITY)

        with pytest.raises(StorageSchemaError, match="neighborhood direction must be one of both, in, out"):
            build_canonical_neighborhood_query_sql(ROOT, node=ITEM, direction="unsupported")
        expected_center = (ITEM, "feed.item", "current")
        expected_neighbors = [
            ("external.url:current", "external.url", "current"),
            ("feed.author:shared", "feed.author", "current"),
            ("feed.category:shared", "feed.category", "current"),
        ]
        expected_edges = [
            (ITEM, "references", "external.url:current", HASH),
            (ITEM, "references", "feed.author:shared", HASH),
            (ITEM, "references", "feed.category:shared", HASH),
        ]

        def assert_neighborhood(payload, nodes, edges):
            center = payload["center"]
            assert (center["canonical_key"], center["kind"], center["display_name"]) == expected_center
            assert [(row["canonical_key"], row["kind"], row["display_name"]) for row in payload["nodes"]] == nodes
            assert [(row["source_key"], row["edge_kind"], row["target_key"], row["identity_metadata_hash"]) for row in payload["edges"]] == edges

        sql_both = build_canonical_neighborhood_query_sql(ROOT, node=ITEM, direction="both", repository_identity=IDENTITY)
        both_res = execute_json_readback(sql_both, psql_args=database.psql_args, psql_command=database.psql_command, label="both", expected_shape="object")
        assert_neighborhood(both_res, expected_neighbors, expected_edges)

        sql_out = build_canonical_neighborhood_query_sql(ROOT, node=ITEM, direction="out", repository_identity=IDENTITY)
        out_res = execute_json_readback(sql_out, psql_args=database.psql_args, psql_command=database.psql_command, label="out", expected_shape="object")
        assert_neighborhood(out_res, expected_neighbors, expected_edges)

        sql_in = build_canonical_neighborhood_query_sql(ROOT, node=ITEM, direction="in", repository_identity=IDENTITY)
        in_res = execute_json_readback(sql_in, psql_args=database.psql_args, psql_command=database.psql_command, label="in", expected_shape="object")
        assert_neighborhood(in_res, [], [])

        sql_paginated = build_canonical_neighborhood_query_sql(
            ROOT, node=ITEM, direction="both", node_limit=2, node_offset=0, edge_limit=1, edge_offset=0, repository_identity=IDENTITY,
        )
        pag_res = execute_json_readback(sql_paginated, psql_args=database.psql_args, psql_command=database.psql_command, label="pag", expected_shape="object")
        assert_neighborhood(pag_res, expected_neighbors[:2], expected_edges[:1])


def test_canonical_readback_row_parsers_and_publication_contracts() -> None:
    with temporary_postgres() as database:
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
        _insert_repository(database, 20, "current", ROOT, IDENTITY)
        results = _read_all(database, ROOT, "current")

        node_rec = canonical_node_record_from_storage_payload(
            {row["canonical_key"]: row for row in results["nodes"]}[ITEM]
        )
        assert node_rec.canonical_key == ITEM
        assert node_rec.kind == "feed.item"
        assert node_rec.display_name == "current"
        assert node_rec.metadata == {"title": "current", "marker": "current"}

        edge_rec = canonical_edge_record_from_storage_payload(results["edges"][0])
        assert edge_rec.source_key == ITEM
        assert edge_rec.edge_kind == "references"
        assert edge_rec.target_key == "external.url:current"
        assert edge_rec.identity_metadata_hash == HASH
        assert edge_rec.metadata == {"scope": "link", "marker": "current"}

        edge_exp = canonical_edge_explanation_from_storage_payload(results["edge_explanation"])
        edge_payload = edge_exp.to_dict()["edge"]
        assert (edge_payload["source_key"], edge_payload["edge_kind"], edge_payload["target_key"], edge_payload["identity_metadata_hash"]) == (ITEM, "references", "external.url:current", HASH)
        assert len(edge_exp.evidence) == 1
        assert edge_exp.evidence[0].evidence_key == "evidence:shared"
        assert edge_exp.evidence[0].path == "feed.xml"
        assert edge_exp.evidence[0].extractor == "fixture"

        neigh = canonical_neighborhood_from_storage_payload(results["neighborhood"])
        neigh_payload = neigh.to_dict()
        assert (neigh_payload["center"]["canonical_key"], neigh_payload["center"]["kind"], neigh_payload["center"]["display_name"]) == (ITEM, "feed.item", "current")
        assert [(row["canonical_key"], row["kind"], row["display_name"]) for row in neigh_payload["nodes"]] == [("external.url:current", "external.url", "current"), ("feed.author:shared", "feed.author", "current"), ("feed.category:shared", "feed.category", "current")]
        assert [(row["source_key"], row["edge_kind"], row["target_key"], row["identity_metadata_hash"]) for row in neigh_payload["edges"]] == [(ITEM, "references", "external.url:current", HASH), (ITEM, "references", "feed.author:shared", HASH), (ITEM, "references", "feed.category:shared", HASH)]
        assert len(neigh.edges) == 3

        ev_rec = canonical_edge_evidence_record_from_storage_payload(results["edge_explanation"]["evidence"][0])
        assert ev_rec.evidence_key == "evidence:shared"
        assert ev_rec.link_kind == "extracted"
        assert ev_rec.path == "feed.xml"

        assert read_latest_receipt_bearing_publication(
            database.psql_args, psql_command=database.psql_command,
        ) is None
        assert read_run_publication(
            database.psql_args, job_id="missing-op", attempt=1, psql_command=database.psql_command,
        ) is None
