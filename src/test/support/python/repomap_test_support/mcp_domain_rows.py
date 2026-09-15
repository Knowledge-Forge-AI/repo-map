"""Public fixture rows for seeded-domain MCP readback contract tests.

This seed is not receipt-driven publication evidence.
"""

DOMAIN_ROWS_SQL = """
INSERT INTO repositories(name, root_path)
VALUES ('public-domain-repo', '/public/domain/repo');

INSERT INTO runs(repository_id, status, finished_at)
SELECT id, 'complete', CURRENT_TIMESTAMP FROM repositories
WHERE name = 'public-domain-repo';

INSERT INTO files(repository_id, path, language, role)
SELECT id, 'README.md', 'markdown', 'documentation' FROM repositories
WHERE name = 'public-domain-repo';

INSERT INTO files(repository_id, path, language, role)
SELECT id, 'src/main.py', 'python', 'source' FROM repositories
WHERE name = 'public-domain-repo';

INSERT INTO canonical_nodes(repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
SELECT r.id, 1, key, 'file', key, '{}'::jsonb, 'extracted'
FROM repositories r CROSS JOIN (VALUES ('file:README.md'), ('file:src/main.py')) AS keys(key)
WHERE r.name = 'public-domain-repo';

INSERT INTO canonical_edges(
    repository_id, graph_key_version, source_canonical_key, edge_kind,
    target_canonical_key, identity_metadata_json, identity_metadata_hash,
    metadata_json, confidence
)
SELECT r.id, 1, 'file:README.md', 'references', 'file:src/main.py',
       '{}'::jsonb, repeat('0', 64), '{}'::jsonb, 'extracted'
FROM repositories r WHERE r.name = 'public-domain-repo';
"""

from pathlib import Path
import tempfile
from unittest import TestCase

from repomap_kg.graph.keys import file_key, python_function_key, python_module_key
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.publication_readback import read_run_publication
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.portable_publication_fixtures import (
    publish_portable_bundle,
    seven_family_bundle,
)
from repomap_test_support.mcp_response_assertions import (
    McpResponse,
    McpRun,
    assert_mcp_page,
    json_bool_field,
    json_int_field,
    json_object_field,
    json_object_list_field,
    json_string_field,
    response_result,
    response_error_text,
    response_structured_content,
)


def run_portable_publication_mcp_readback_scenario(
    test_case: TestCase,
    run_mcp_fn: McpRun,
) -> None:
    """Execute domain queries over an admitted portable publication in temporary PostgreSQL."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )

        pub_bundle = seven_family_bundle(
            job_id="job-portable-pub",
            attempt=1,
            graph_id="portable-pub",
            repository_name="portable-pub-repo",
            file_path="pkg/main.py",
            module_name="pkg.main",
            function_name="serve",
        )
        pub_summary = publish_portable_bundle(
            postgres.psql_args,
            pub_bundle,
            repository_name="portable-pub-repo",
            root_path="/portable/domain/repo",
        )
        test_case.assertIsNotNone(pub_summary.publication_receipt)
        pub_record = read_run_publication(
            postgres.psql_args,
            job_id=pub_bundle.job_id,
            attempt=pub_bundle.attempt,
            psql_command=postgres.psql_command,
        )
        assert pub_record is not None
        assert pub_record.receipt.portable is not None
        test_case.assertEqual(pub_summary.publication_receipt, pub_record.receipt)
        test_case.assertEqual(pub_record.receipt.attempt.job_id, pub_bundle.job_id)
        test_case.assertEqual(pub_record.receipt.attempt.attempt, pub_bundle.attempt)
        test_case.assertEqual(pub_record.receipt.portable.candidate_id, pub_bundle.candidate_id)
        test_case.assertEqual(pub_record.receipt.portable.snapshot_manifest_id, pub_bundle.snapshot_manifest_id)
        test_case.assertGreater(pub_record.receipt.portable.singleton_fencing_epoch, 0)
        test_case.assertGreater(pub_record.receipt.portable.graph_lease_fencing_epoch, 0)
        pub_marker = pub_record.publication_authority_marker()
        test_case.assertEqual(
            pub_marker["latest_receipt_bearing_publication_identity"],
            f"run-{pub_record.run_id}",
        )
        test_case.assertEqual(pub_marker["graph_candidate_id"], pub_bundle.candidate_id)

        priv_postgres = postgres.create_database("portable_priv_db")
        apply_migrations(
            default_rdbms_root(),
            priv_postgres.psql_args,
            psql_command=priv_postgres.psql_command,
        )
        priv_bundle = seven_family_bundle(
            job_id="job-portable-priv",
            attempt=1,
            graph_id="portable-priv",
            repository_name="portable-priv-repo",
            privacy=PrivacyClassification.CANONICAL_PROVENANCE,
            file_path="secret/core.py",
            module_name="secret.core",
            function_name="encrypt",
        )
        priv_summary = publish_portable_bundle(
            priv_postgres.psql_args,
            priv_bundle,
            repository_name="portable-priv-repo",
            root_path="/private/portable/repo",
        )
        test_case.assertIsNotNone(priv_summary.publication_receipt)
        priv_record = read_run_publication(
            priv_postgres.psql_args,
            job_id=priv_bundle.job_id,
            attempt=priv_bundle.attempt,
            psql_command=priv_postgres.psql_command,
        )
        assert priv_record is not None
        assert priv_record.receipt.portable is not None
        test_case.assertEqual(priv_summary.publication_receipt, priv_record.receipt)
        test_case.assertEqual(priv_record.receipt.attempt.job_id, priv_bundle.job_id)
        test_case.assertEqual(priv_record.receipt.portable.candidate_id, priv_bundle.candidate_id)
        test_case.assertGreater(priv_record.receipt.portable.singleton_fencing_epoch, 0)
        test_case.assertGreater(priv_record.receipt.portable.graph_lease_fencing_epoch, 0)

        with tempfile.TemporaryDirectory(prefix="repomap-mcp-portable-") as tmpdir:
            cfg_path = Path(tmpdir) / "repomap.local.toml"
            cfg_path.write_text(
                f"""schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "PUBLIC_SAFE_PASSWORD"
[server_memory]
enabled = false
path = "/public/test-disabled-memory"
mode = "read_only"
[[graphs]]
id = "portable-pub"
name = "Portable Publication"
root_path = "/portable/domain/repo"
repository_name = "portable-pub-repo"
database = "{postgres.database}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "portable-priv"
name = "Portable Private"
root_path = "/private/portable/repo"
repository_name = "portable-priv-repo"
database = "{priv_postgres.database}"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
""",
                encoding="utf-8",
            )

            extra_env = {
                "REPOMAP_OPS_CONFIG": str(cfg_path),
                "REPOMAP_PSQL_COMMAND": postgres.psql_command,
            }

            def call(req_id: int, tool: str, args: dict[str, object]) -> dict[str, object]:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args},
                }

            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }
            responses = run_mcp_fn(
                [
                    init_req,
                    call(2, "repomap_projects", {}),
                    call(3, "repomap_canonical_nodes", {"project": "portable-pub", "limit": 10, "offset": 0}),
                    call(4, "repomap_canonical_nodes", {"project": "portable-pub", "limit": 1, "offset": 0}),
                    call(5, "repomap_canonical_nodes", {"project": "portable-pub", "limit": 1, "offset": 1}),
                    call(6, "repomap_canonical_nodes", {"project": "portable-pub", "limit": 1, "offset": 2}),
                    call(7, "repomap_canonical_edges", {"project": "portable-pub"}),
                    call(8, "repomap_canonical_neighborhood", {"project": "portable-pub", "node": "file:pkg/main.py"}),
                    call(9, "repomap_explain_canonical_edge", {
                        "project": "portable-pub",
                        "source_key": "file:pkg/main.py",
                        "kind": "defines",
                        "target_key": "python.module:pkg.main",
                        "evidence_limit": 1,
                        "evidence_offset": 0,
                    }),
                    call(10, "repomap_canonical_nodes", {"project": "portable-priv", "limit": 10, "offset": 0}),
                    call(11, "repomap_canonical_nodes", {"project": "portable-pub", "limit": 201}),
                    call(12, "repomap_canonical_edges", {"project": "portable-pub", "offset": 100}),
                    call(13, "repomap_canonical_nodes", {"project": "portable-priv", "include_source": True}),
                    call(14, "repomap_status", {"project": "portable-pub"}),

                ],
                extra_env,
            )

            resp_by_id: dict[int, McpResponse] = {r["id"]: r for r in responses}

            # 1. Verify repomap_projects response with privacy markers
            proj_resp = resp_by_id[2]
            test_case.assertNotIn("error", proj_resp)
            proj_data = response_structured_content(proj_resp)
            graphs = json_object_list_field(proj_data, "graphs")
            graph_ids = [json_string_field(graph, "graph_id") for graph in graphs]
            test_case.assertIn("portable-pub", graph_ids)
            test_case.assertIn("portable-priv", graph_ids)
            priv_graph = next(
                graph for graph in graphs if json_string_field(graph, "graph_id") == "portable-priv"
            )
            test_case.assertTrue(json_bool_field(priv_graph, "private"))
            test_case.assertEqual(json_string_field(priv_graph, "privacy"), "private-ops")
            test_case.assertEqual(json_string_field(priv_graph, "root_path_display"), "[private-root]")
            warnings = json_object_list_field(priv_graph, "warnings")
            test_case.assertEqual(json_string_field(warnings[0], "code"), "private-graph-visible")

            # 2. Verify repomap_canonical_nodes returned from accepted publication
            nodes_resp = resp_by_id[3]
            test_case.assertNotIn("error", nodes_resp)
            nodes_data = response_structured_content(nodes_resp)
            test_case.assertIn("items", nodes_data)
            node_items = json_object_list_field(nodes_data, "items")
            node_keys = {json_string_field(item, "canonical_key") for item in node_items}
            test_case.assertIn(file_key("pkg/main.py"), node_keys)
            test_case.assertIn(python_module_key("pkg.main"), node_keys)
            test_case.assertIn(python_function_key("pkg.main", "serve"), node_keys)
            assert_mcp_page(
                test_case, nodes_data,
                limit=10, offset=0, returned=len(node_items),
                truncated=False, next_offset=None,
            )

            # Source-blind privacy: ensure no raw source content leaked in metadata
            for item in node_items:
                test_case.assertNotIn("source_code", item)
                test_case.assertNotIn("raw_content", item)

            # 3. Verify pagination contracts
            p1_data = response_structured_content(resp_by_id[4])
            test_case.assertEqual(len(json_object_list_field(p1_data, "items")), 1)
            assert_mcp_page(test_case, p1_data, limit=1, offset=0, returned=1, truncated=True, next_offset=1)

            p2_data = response_structured_content(resp_by_id[5])
            test_case.assertEqual(len(json_object_list_field(p2_data, "items")), 1)
            assert_mcp_page(test_case, p2_data, limit=1, offset=1, returned=1, truncated=True, next_offset=2)

            p3_data = response_structured_content(resp_by_id[6])
            test_case.assertEqual(len(json_object_list_field(p3_data, "items")), 1)
            assert_mcp_page(test_case, p3_data, limit=1, offset=2, returned=1, truncated=False, next_offset=None)

            # 4. Verify repomap_canonical_edges
            edges_resp = resp_by_id[7]
            test_case.assertNotIn("error", edges_resp)
            edges_data = response_structured_content(edges_resp)
            test_case.assertIn("items", edges_data)
            edges = json_object_list_field(edges_data, "items")
            test_case.assertGreaterEqual(len(edges), 2)
            edge_tuples = {
                (
                    json_string_field(edge, "source_key"),
                    json_string_field(edge, "edge_kind"),
                    json_string_field(edge, "target_key"),
                )
                for edge in edges
            }
            test_case.assertIn((file_key("pkg/main.py"), "defines", python_module_key("pkg.main")), edge_tuples)
            test_case.assertIn((file_key("pkg/main.py"), "defines", python_function_key("pkg.main", "serve")), edge_tuples)

            # 5. Verify repomap_canonical_neighborhood
            neighborhood_resp = resp_by_id[8]
            test_case.assertNotIn("error", neighborhood_resp)
            neighborhood_data = response_structured_content(neighborhood_resp)
            neigh_result = json_object_field(neighborhood_data, "result")
            center = json_object_field(neigh_result, "center")
            test_case.assertEqual(json_string_field(center, "canonical_key"), file_key("pkg/main.py"))

            # 6. Verify repomap_explain_canonical_edge with evidence readback
            explain_resp = resp_by_id[9]
            test_case.assertNotIn("error", explain_resp)
            explain_data = response_structured_content(explain_resp)
            explain_result = json_object_field(explain_data, "result")
            test_case.assertIn("edge", explain_result)
            explain_edge = json_object_field(explain_result, "edge")
            test_case.assertEqual(json_string_field(explain_edge, "source_key"), file_key("pkg/main.py"))
            test_case.assertEqual(json_string_field(explain_edge, "target_key"), python_module_key("pkg.main"))
            test_case.assertIn("evidence", explain_result)
            test_case.assertGreaterEqual(
                len(json_object_list_field(explain_result, "evidence")),
                1,
            )

            # 7. Verify private graph nodes readback with preserved source-blind privacy
            priv_nodes_resp = resp_by_id[10]
            test_case.assertNotIn("error", priv_nodes_resp)
            priv_nodes_data = response_structured_content(priv_nodes_resp)
            priv_node_keys = {
                json_string_field(item, "canonical_key")
                for item in json_object_list_field(priv_nodes_data, "items")
            }
            test_case.assertIn(file_key("secret/core.py"), priv_node_keys)

            # Independent adverse reads use the same accepted publication, without seeded rows.
            bounds = response_result(resp_by_id[11])
            test_case.assertIs(json_bool_field(bounds, "isError"), True)
            test_case.assertIn("limit must be between 1 and 200", response_error_text(resp_by_id[11]))
            exhausted = response_structured_content(resp_by_id[12])
            test_case.assertEqual(json_object_list_field(exhausted, "items"), [])
            assert_mcp_page(test_case, exhausted, limit=50, offset=100, returned=0, truncated=False, next_offset=None)
            source_refusal = response_result(resp_by_id[13])
            test_case.assertIs(json_bool_field(source_refusal, "isError"), True)
            test_case.assertIn("unexpected argument(s): include_source", response_error_text(resp_by_id[13]))
            status = response_structured_content(resp_by_id[14])
            test_case.assertEqual(json_string_field(status, "repository_name"), "portable-pub-repo")
            counts = json_object_field(status, "counts")
            test_case.assertEqual(json_int_field(counts, "files"), 1)
            test_case.assertGreater(json_int_field(counts, "canonical_evidence"), 0)
            test_case.assertIs(json_bool_field(status, "read_only"), True)
            # Reads and refused requests cannot replace the accepted receipt or authority.
            after_record = read_run_publication(
                postgres.psql_args, job_id=pub_bundle.job_id, attempt=pub_bundle.attempt,
                psql_command=postgres.psql_command,
            )
            assert after_record is not None
            test_case.assertEqual(after_record.receipt, pub_record.receipt)
            test_case.assertEqual(after_record.publication_authority_marker(), pub_marker)
