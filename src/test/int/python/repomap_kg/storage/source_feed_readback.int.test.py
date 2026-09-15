import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.ingestion.source import FeedFetchResponse, ingest_feed_source
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
    query_canonical_node_records,
)
from repomap_test_support.storage_integration import (
    discovery_fixture,
    fixed_source_clock,
    source_fixture,
)
from repomap_test_support.source_ingestion_integration import (
    publish_acquisition_summary,
)


class StorageSourceFeedReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_feed_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("feed_static_basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "feed-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                document_exit, document_stdout, document_stderr = canonical_nodes("feed.document")
                channel_exit, channel_stdout, channel_stderr = canonical_nodes("feed.channel")
                item_exit, item_stdout, item_stderr = canonical_nodes("feed.item")
                author_exit, author_stdout, author_stderr = canonical_nodes("feed.author")
                category_exit, category_stdout, category_stderr = canonical_nodes("feed.category")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges("defines")
                references_exit, references_stdout, references_stderr = canonical_edges("references")
                references = (
                    json.loads(references_stdout) if references_exit == 0 else []
                )
                item_link_edge = next(
                    (
                        record
                        for record in references
                        if record["source_key"].startswith("feed.item:")
                        and record["target_key"]
                        == "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1"
                    ),
                    None,
                )
                if item_link_edge is not None:
                    explain_exit, explain_stdout, explain_stderr = run_repo_map_in_process(
                        "storage", "explain-canonical-edge", *storage_args,
                        "--source-key", item_link_edge["source_key"], "--kind", "references",
                        "--target-key", item_link_edge["target_key"], "--json",
                    )
                else:
                    explain_exit, explain_stdout, explain_stderr = 1, "", "missing feed item link edge"

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "feed.document",
                "feed.channel",
                "feed.item",
                "feed.link",
                "feed.enclosure",
                "feed.author",
                "feed.category",
                "feed.content",
                "feed.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fixture-feed-secret", discover_stdout)
        self.assertNotIn("throw new Error", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertTrue(
            {
                "feed.document:file%3Arss.xml",
                "feed.document:file%3Aatom.xml",
                "feed.document:file%3Afeed.json",
            }.issubset(document_keys)
        )

        self.assertEqual(channel_exit, 0, channel_stderr)
        self.assertGreaterEqual(len(json.loads(channel_stdout)), 3)
        self.assertEqual(item_exit, 0, item_stderr)
        items = json.loads(item_stdout)
        self.assertTrue(any(record["metadata"].get("duplicate_identity") for record in items))
        self.assertTrue(
            any(record["metadata"].get("identity_strength") == "weak" for record in items)
        )
        self.assertEqual(author_exit, 0, author_stderr)
        self.assertGreaterEqual(len(json.loads(author_stdout)), 2)
        self.assertEqual(category_exit, 0, category_stderr)
        self.assertGreaterEqual(len(json.loads(category_stdout)), 2)

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("feed.document:file%3Arss.xml", define_targets)
        self.assertTrue(any(target.startswith("feed.item:") for target in define_targets))

        self.assertEqual(references_exit, 0, references_stderr)
        reference_pairs = {
            (record["source_key"].split(":", 1)[0], record["target_key"])
            for record in references
        }
        self.assertIn(
            (
                "feed.item",
                "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
            ),
            reference_pairs,
        )
        self.assertIn(("feed.item", "file:media/rss-audio.mp3"), reference_pairs)
        self.assertTrue(
            any(target.startswith("feed.author:") for _, target in reference_pairs)
        )
        self.assertTrue(
            any(target.startswith("feed.category:") for _, target in reference_pairs)
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
        )
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "feed.link",
        )
        self.assertNotIn("fixture-feed-secret", explain_stdout)

    def test_sources_ingest_feed_loads_configured_feed_artifact(self):
        require_postgres_binaries()
        config_path = source_fixture("allowed-rss.toml")
        feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()
        calls = []

        def fetcher(config):
            calls.append(config.url)
            return FeedFetchResponse(
                status=200,
                headers={"content-type": "application/rss+xml"},
                body=feed_body,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir) / "fixture-repo"
            root_path.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = ingest_feed_source(
                    config_path,
                    root_path=root_path,
                    fetcher=fetcher,
                    clock=fixed_source_clock,
                )
                publication = publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture",
                    root_path=root_path,
                )
                q_rec = lambda fn, k: fn(postgres.psql_args, root_path=str(root_path), kind=k, psql_command=postgres.psql_command)
                documents = q_rec(query_canonical_node_records, "feed.document")
                items = q_rec(query_canonical_node_records, "feed.item")
                references = q_rec(query_canonical_edge_records, "references")
                raw_count = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual(summary.source_id, "example-rss-feed")
        self.assertEqual(publication.repository_id, 1)
        self.assertEqual(publication.files, 1)
        self.assertEqual(raw_count, str(summary.observations))
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0].canonical_key.startswith("feed.document:"))
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(
            any(
                edge.source_key.startswith("feed.item:")
                and edge.target_key.startswith("external.url:")
                for edge in references
            )
        )
        source_metadata = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id_configured": "example-rss-feed"', source_metadata)
        self.assertNotIn("fixture-secret", source_metadata)

    def test_mcp_read_only_source_feed_tools_read_rss2_loaded_rows(self):
        require_postgres_binaries()
        config_path = source_fixture("allowed-rss.toml")
        feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()
        calls = []

        def fetcher(config):
            calls.append(config.url)
            return FeedFetchResponse(
                status=200,
                headers={"content-type": "application/rss+xml"},
                body=feed_body,
            )

        from repomap_kg.server.mcp import (
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir) / "fixture-repo"
            root_path.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                summary = ingest_feed_source(
                    config_path,
                    root_path=root_path,
                    fetcher=fetcher,
                    clock=fixed_source_clock,
                )
                publish_acquisition_summary(
                    postgres,
                    summary,
                    repository_name="fixture",
                    root_path=root_path,
                )
                mcp_args = {
                    "root_path": str(root_path), "pg_host": str(postgres.socket_dir),
                    "pg_port": str(postgres.port), "pg_user": postgres.user,
                    "pg_database": postgres.database, "psql_command": postgres.psql_command,
                }
                sources = repomap_ingested_sources(**mcp_args, source_type="feed.rss")
                source_summary = repomap_source_summary(**mcp_args, source_id="example-rss-feed")
                runs = repomap_source_runs(**mcp_args, source_id="example-rss-feed")
                items = repomap_source_feed_items(**mcp_args, source_id="example-rss-feed")
                references = repomap_source_references(
                    **mcp_args, source_id="example-rss-feed", target_kind="external.url",
                )
                explanation = repomap_explain_source_feed_item(
                    **mcp_args, item_key=items[0]["item_key"], source_id="example-rss-feed",
                )

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual([record["source_id"] for record in sources], ["example-rss-feed"])
        self.assertEqual(sources[0]["source_type"], "feed.rss")
        self.assertEqual(sources[0]["policy_status"], "allowed_with_limits")
        self.assertGreaterEqual(sources[0]["canonical_feed_item_count"], 1)
        self.assertEqual(source_summary["source_id"], "example-rss-feed")
        self.assertEqual(source_summary["feed_documents"], 1)
        self.assertEqual(source_summary["feed_channels"], 1)
        self.assertGreaterEqual(source_summary["feed_items"], 1)
        self.assertEqual(runs[0]["source_run_id"], "20260630T120000Z")
        self.assertEqual(runs[0]["http_status"], 200)
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(items[0]["item_key"].startswith("feed.item:"))
        self.assertIn(items[0]["identity_strength"], {"strong", "weak", "structural"})
        self.assertTrue(
            all(reference["not_fetched"] for reference in references),
            references,
        )
        self.assertTrue(
            all(reference["target_key"].startswith("external.url:") for reference in references),
            references,
        )
        self.assertEqual(explanation["item"]["canonical_key"], items[0]["item_key"])
        self.assertEqual(explanation["source"]["source_id"], "example-rss-feed")
        serialized = json.dumps(
            {
                "sources": sources,
                "summary": source_summary,
                "runs": runs,
                "items": items,
                "references": references,
                "explanation": explanation,
            },
            sort_keys=True,
        )
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)
