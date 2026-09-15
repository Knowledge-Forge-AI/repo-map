import subprocess
import unittest
import json
import os
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    query_canonical_neighborhood,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

class StorageCanonicalQueryUnitTests(unittest.TestCase):
    def test_query_canonical_records_parse_psql_json_arrays(self):
        node_payload = json.dumps(
            [
                {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ]
        )
        edge_hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        edge_payload = json.dumps(
            [
                {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": edge_hash,
                    "metadata": {},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ]
        )

        with patch.dict(os.environ, {READBACK_DRIVER_ENV: "psql"}):
            with patch("repomap_kg.storage.subprocess.run") as run:
                run.side_effect = [
                    subprocess.CompletedProcess(["psql"], 0, stdout=node_payload + "\n"),
                    subprocess.CompletedProcess(["psql"], 0, stdout=edge_payload + "\n"),
                ]

                nodes = query_canonical_node_records(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    kind="tool",
                )
                edges = query_canonical_edge_records(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    kind="executes",
                    target_key="tool:nix",
                )

        self.assertEqual(nodes[0].canonical_key, "tool:nix")
        self.assertEqual(edges[0].target_key, "tool:nix")
        self.assertIn("canonical_nodes", run.call_args_list[0].kwargs["input"])
        self.assertIn("canonical_edges", run.call_args_list[1].kwargs["input"])
    def test_query_canonical_edge_explanation_parses_psql_json_object(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload = json.dumps(
            {
                "edge": {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": hash_text,
                    "metadata": {},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "evidence": [],
            }
        )

        with patch.dict(os.environ, {READBACK_DRIVER_ENV: "psql"}):
            with patch("repomap_kg.storage.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["psql"],
                    0,
                    stdout=payload + "\n",
                )

                record = query_canonical_edge_explanation(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    source_key="file:bin/tool",
                    kind="executes",
                    target_key="tool:nix",
                    identity_metadata_hash=hash_text,
                )

        assert record.edge is not None
        self.assertEqual(record.edge.target_key, "tool:nix")
        self.assertEqual(record.evidence, ())
        sql = run.call_args.kwargs["input"]
        self.assertIn("canonical_edges", sql)
        self.assertIn(f"canonical_edges.identity_metadata_hash = '{hash_text}'", sql)
    def test_query_canonical_neighborhood_parses_psql_json_object(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload = json.dumps(
            {
                "center": {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "nodes": [
                    {
                        "canonical_key": "file:bin/tool",
                        "graph_key_version": 1,
                        "kind": "file",
                        "display_name": "bin/tool",
                        "confidence": "extracted",
                        "conflict": False,
                        "metadata": {},
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
                "edges": [
                    {
                        "source_key": "file:bin/tool",
                        "edge_kind": "executes",
                        "target_key": "tool:nix",
                        "graph_key_version": 1,
                        "identity_metadata": {},
                        "identity_metadata_hash": hash_text,
                        "metadata": {},
                        "confidence": "extracted",
                        "conflict": False,
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
            }
        )

        previous_pg_connector_present = PG_CONNECTOR_ENV in os.environ
        previous_pg_connector = os.environ.get(PG_CONNECTOR_ENV)
        previous_driver_present = READBACK_DRIVER_ENV in os.environ
        previous_driver = os.environ.get(READBACK_DRIVER_ENV)
        os.environ.pop(PG_CONNECTOR_ENV, None)
        os.environ[READBACK_DRIVER_ENV] = "psql"
        try:
            with patch("repomap_kg.storage.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ["psql"],
                    0,
                    stdout=payload + "\n",
                )

                record = query_canonical_neighborhood(
                    ["-d", "postgres"],
                    root_path="/tmp/fixture",
                    node="tool:nix",
                    direction="in",
                )
        finally:
            if previous_pg_connector_present:
                if previous_pg_connector is None:
                    raise AssertionError(
                        f"{PG_CONNECTOR_ENV} was present without a string value"
                    )
                os.environ[PG_CONNECTOR_ENV] = previous_pg_connector
            else:
                os.environ.pop(PG_CONNECTOR_ENV, None)
            if previous_driver_present:
                if previous_driver is None:
                    raise AssertionError(
                        f"{READBACK_DRIVER_ENV} was present without a string value"
                    )
                os.environ[READBACK_DRIVER_ENV] = previous_driver
            else:
                os.environ.pop(READBACK_DRIVER_ENV, None)

        self.assertEqual(
            PG_CONNECTOR_ENV in os.environ,
            previous_pg_connector_present,
        )
        self.assertEqual(os.environ.get(PG_CONNECTOR_ENV), previous_pg_connector)
        self.assertEqual(
            READBACK_DRIVER_ENV in os.environ,
            previous_driver_present,
        )
        self.assertEqual(os.environ.get(READBACK_DRIVER_ENV), previous_driver)

        assert record.center is not None
        self.assertEqual(record.center.canonical_key, "tool:nix")
        self.assertEqual(record.nodes[0].canonical_key, "file:bin/tool")
        self.assertEqual(record.edges[0].target_key, "tool:nix")
        sql = run.call_args.kwargs["input"]
        self.assertIn("canonical_nodes", sql)
        self.assertIn("canonical_edges", sql)
    def test_query_canonical_neighborhood_rejects_depth_above_one(self):
        with self.assertRaisesRegex(
            StorageSchemaError,
            "neighborhood only supports depth 1",
        ):
            query_canonical_neighborhood(
                [],
                root_path="/tmp/fixture",
                node="tool:nix",
                depth=2,
            )
