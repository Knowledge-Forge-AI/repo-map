import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    build_canonical_edge_query_sql,
    build_canonical_neighborhood_query_sql,
    build_canonical_node_query_sql,
    build_explain_canonical_edge_query_sql,
    public_embedded_read_result_to_jsonable,
    public_read_page,
)
from repomap_kg.storage.canonical import (
    query_canonical_edge_records,
    query_canonical_node_records,
)


class StorageCanonicalPaginationUnitTests(unittest.TestCase):
    def test_canonical_sql_orders_before_limit_and_offset(self):
        nodes_sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            limit=50,
            offset=10,
        )
        edges_sql = build_canonical_edge_query_sql(
            "/tmp/fixture",
            limit=7,
            offset=3,
        )

        self.assertLess(
            nodes_sql.index("ORDER BY canonical_nodes.canonical_key"),
            nodes_sql.index("LIMIT 50 OFFSET 10"),
        )
        self.assertLess(
            edges_sql.index("ORDER BY canonical_edges.source_canonical_key"),
            edges_sql.index("LIMIT 7 OFFSET 3"),
        )

    def test_canonical_sql_preserves_unbounded_storage_default(self):
        nodes_sql = build_canonical_node_query_sql("/tmp/fixture")
        edges_sql = build_canonical_edge_query_sql("/tmp/fixture")

        self.assertNotIn("LIMIT", nodes_sql)
        self.assertNotIn("OFFSET", nodes_sql)
        self.assertNotIn("LIMIT", edges_sql)
        self.assertNotIn("OFFSET", edges_sql)

    def test_canonical_sql_rejects_invalid_pagination(self):
        with self.assertRaisesRegex(
            StorageSchemaError,
            "limit must be a positive integer",
        ):
            build_canonical_node_query_sql("/tmp/fixture", limit=0)
        with self.assertRaisesRegex(
            StorageSchemaError,
            "offset must be a non-negative integer",
        ):
            build_canonical_edge_query_sql("/tmp/fixture", limit=1, offset=-1)

    def test_canonical_queries_forward_pagination_to_sql(self):
        with patch(
            "repomap_kg.storage.canonical.execute_json_readback",
            return_value=[],
        ) as execute:
            query_canonical_node_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                limit=9,
                offset=4,
            )
            nodes_sql = execute.call_args.args[0]
            query_canonical_edge_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                limit=8,
                offset=2,
            )
            edges_sql = execute.call_args.args[0]

        self.assertIn("LIMIT 9 OFFSET 4", nodes_sql)
        self.assertIn("LIMIT 8 OFFSET 2", edges_sql)

    def test_arch7a2_embedded_collections_order_before_independent_windows(self):
        neighborhood_sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            node_limit=3,
            node_offset=4,
            edge_limit=5,
            edge_offset=6,
        )
        explanation_sql = build_explain_canonical_edge_query_sql(
            "/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata_hash="0" * 64,
            evidence_limit=7,
            evidence_offset=8,
        )

        self.assertIn(
            "ORDER BY canonical_nodes.canonical_key LIMIT 3 OFFSET 4",
            neighborhood_sql,
        )
        self.assertIn(
            "canonical_edges.identity_metadata_hash LIMIT 5 OFFSET 6",
            neighborhood_sql,
        )
        self.assertIn(
            "canonical_edge_evidence.link_kind LIMIT 7 OFFSET 8",
            explanation_sql,
        )

    def test_arch7a2_embedded_collection_reports_bounded_truncation(self):
        page = public_read_page(("first", "lookahead"), limit=1, offset=4)

        payload = public_embedded_read_result_to_jsonable(
            {"evidence": list(page.items)},
            result_kind="canonical_edge_explanation",
            collection_pages={"evidence": page},
        )

        self.assertEqual(payload["result"]["evidence"], ["first"])
        self.assertEqual(
            payload["collections"]["evidence"],
            {
                "limit": 1,
                "offset": 4,
                "returned": 1,
                "truncated": True,
                "next_offset": 5,
            },
        )
        self.assertEqual(
            payload["diagnostics"],
            [
                {
                    "code": "result_truncated",
                    "collection": "evidence",
                    "message": "additional results are available",
                }
            ],
        )
