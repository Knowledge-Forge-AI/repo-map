import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.ops.graph_files import (
    GraphFileFilters,
    GraphFilePage,
    OpsRefreshError,
    build_graph_file_query_sql,
    graph_file_record_from_payload,
    query_graph_files,
)
from repomap_kg.storage import StorageSchemaError


def _payload(*, key="file:src/app.py", metadata=None, observed=1, links=None):
    if metadata is None:
        metadata = {
            "language": "python",
            "role": "source",
            "generated": False,
            "executable": False,
            "content_hash": "private-hash",
        }
    return {
        "canonical_key": key,
        "graph_key_version": 1,
        "confidence": "extracted",
        "conflict": False,
        "metadata": metadata,
        "evidence_count": 3,
        "file_observation_count": observed,
        "link_kinds": links or ["observed"],
        "internal_id": 99,
    }


class GraphFileRecordUnitTests(unittest.TestCase):
    def test_record_projection_is_bounded_deterministic_and_private_safe(self):
        record = graph_file_record_from_payload(
            _payload(
                metadata={
                    "language": [f"language-{index:02d}" for index in range(25)],
                    "role": "source",
                    "generated": [True, False],
                    "executable": False,
                    "content_hash": "private-hash",
                },
                links=[f"link-{index:02d}" for index in range(22)],
            )
        )

        payload = record.to_jsonable()
        self.assertEqual(payload["canonical_key"], "file:src/app.py")
        self.assertEqual(payload["path"], "src/app.py")
        self.assertEqual(payload["observation_state"], "observed")
        self.assertEqual(len(payload["languages"]), 20)
        self.assertEqual(payload["candidate_overflow"]["languages"], 5)
        self.assertEqual(payload["generated_states"], [False, True])
        self.assertIn("generated_states", payload["ambiguous_fields"])
        self.assertEqual(len(payload["evidence"]["link_kinds"]), 20)
        self.assertEqual(payload["evidence"]["link_kind_overflow"], 2)
        self.assertNotIn("content_hash", str(payload))
        self.assertNotIn("internal_id", str(payload))

    def test_referenced_record_uses_empty_inventory_candidates(self):
        record = graph_file_record_from_payload(
            _payload(metadata={}, observed=0, key="file:docs/missing.md")
        )

        payload = record.to_jsonable()
        self.assertEqual(payload["observation_state"], "referenced")
        self.assertEqual(payload["languages"], [])
        self.assertEqual(payload["roles"], [])
        self.assertEqual(payload["generated_states"], [])
        self.assertEqual(payload["executable_states"], [])

    def test_record_decodes_a_valid_percent_encoded_file_key_path(self):
        record = graph_file_record_from_payload(
            _payload(key="file:docs/a%20b%25.md")
        )

        self.assertEqual(record.canonical_key, "file:docs/a%20b%25.md")
        self.assertEqual(record.path, "docs/a b%.md")


class GraphFileSqlUnitTests(unittest.TestCase):
    def test_sql_reads_canonical_evidence_and_filters_before_pagination(self):
        sql = build_graph_file_query_sql(
            "stable-repository' OR TRUE --",
            filters=GraphFileFilters(
                path_prefix="src",
                language="python",
                role="source",
                generated="exclude",
                executable="only",
                observation_state="observed",
                ambiguity="exclude",
            ),
            limit=50,
            offset=7,
        )

        self.assertIn("canonical_nodes", sql)
        self.assertIn("canonical_node_evidence", sql)
        self.assertIn("canonical_evidence", sql)
        self.assertNotIn("FROM files ", sql)
        self.assertNotIn("JOIN files ", sql)
        self.assertNotIn("raw_observations", sql)
        self.assertNotIn("stable-repository' OR", sql)
        self.assertLess(sql.index("WHERE"), sql.index("ORDER BY canonical_key"))
        self.assertIn("ORDER BY canonical_key LIMIT 51 OFFSET 7", sql)

        for field in (
            "binding_id",
            "binding_alias",
            "binding_role",
            "snapshot_id",
            "candidate_id",
            "source_relative_path",
        ):
            self.assertIn(f"metadata_json->'{field}'", sql)
            self.assertIn(f"'{field}', {field}", sql)

    def test_sql_rejects_invalid_filters_and_pagination(self):
        cases = (
            (GraphFileFilters(path="a", path_prefix="a"), 50, 0),
            (GraphFileFilters(generated="invalid"), 50, 0),
            (GraphFileFilters(), 0, 0),
            (GraphFileFilters(), 201, 0),
            (GraphFileFilters(), 50, -1),
        )
        for filters, limit, offset in cases:
            with self.subTest(filters=filters, limit=limit, offset=offset):
                with self.assertRaises(StorageSchemaError):
                    build_graph_file_query_sql(
                        "stable-repository",
                        filters=filters,
                        limit=limit,
                        offset=offset,
                    )


class GraphFileQueryUnitTests(unittest.TestCase):
    def test_query_routes_one_enabled_graph_and_trims_has_more_record(self):
        graph = SimpleNamespace(
            id="public",
            repository_name="stable-repository",
            readback_unsupported_classification=None,
            enabled=True,
        )
        config = SimpleNamespace(graphs=(graph,))
        with (
            patch(
                "repomap_kg.ops.graph_files.graph_database",
                return_value="private-database",
            ),
            patch(
                "repomap_kg.ops.graph_files.execute_ops_json_readback",
                return_value=[
                    _payload(key="file:a"),
                    _payload(key="file:b"),
                    _payload(key="file:c"),
                ],
            ) as execute,
        ):
            page = query_graph_files(
                cast(OpsConfig, config),
                "public",
                filters=GraphFileFilters(),
                limit=2,
                offset=3,
                psql_command="fixture-psql",
            )

        self.assertIsInstance(page, GraphFilePage)
        self.assertEqual([record.canonical_key for record in page.records], ["file:a", "file:b"])
        self.assertTrue(page.has_more)
        self.assertEqual(page.offset, 3)
        self.assertEqual(execute.call_args.kwargs["database"], "private-database")
        self.assertEqual(execute.call_args.kwargs["psql_command"], "fixture-psql")
        self.assertIn("LIMIT 3 OFFSET 3", execute.call_args.kwargs["sql"])

    def test_query_rejects_disabled_graph_before_storage(self):
        graph = SimpleNamespace(
            id="disabled",
            repository_name="stable-repository",
            enabled=False,
        )
        config = SimpleNamespace(graphs=(graph,))
        with patch(
            "repomap_kg.ops.graph_files.execute_ops_json_readback"
        ) as execute:
            with self.assertRaisesRegex(OpsRefreshError, "disabled"):
                query_graph_files(
                    cast(OpsConfig, config),
                    "disabled",
                    filters=GraphFileFilters(),
                    limit=50,
                    offset=0,
                )
        execute.assert_not_called()

    def test_query_sanitizes_storage_failure_to_graph_scope(self):
        graph = SimpleNamespace(
            id="public",
            repository_name="stable-repository",
            readback_unsupported_classification=None,
            enabled=True,
        )
        config = SimpleNamespace(graphs=(graph,))
        with (
            patch(
                "repomap_kg.ops.graph_files.graph_database",
                return_value="private-database",
            ),
            patch(
                "repomap_kg.ops.graph_files.execute_ops_json_readback",
                side_effect=StorageSchemaError(
                    "failed at /Users/private using private-database"
                ),
            ),
        ):
            with self.assertRaisesRegex(
                OpsRefreshError,
                "graph 'public' file readback failed$",
            ) as raised:
                query_graph_files(
                    cast(OpsConfig, config),
                    "public",
                    filters=GraphFileFilters(),
                    limit=50,
                    offset=0,
                )
        self.assertNotIn("private", str(raised.exception))
