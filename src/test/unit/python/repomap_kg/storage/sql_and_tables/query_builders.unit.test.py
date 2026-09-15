import unittest

from repomap_kg.storage import (
    build_canonical_storage_summary_query_sql,
    build_email_summary_query_sql,
    build_js_summary_query_sql,
    build_ruby_summary_query_sql,
)


class StorageSqlBuilderUnitTests(unittest.TestCase):
    def test_canonical_summary_counts_only_retained_runtime_families(self):
        sql = build_canonical_storage_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        for table in (
            "runs",
            "files",
            "raw_observations",
            "canonical_nodes",
            "canonical_edges",
            "canonical_evidence",
        ):
            self.assertIn(f"COUNT(*) FROM {table}", sql)
        self.assertIn("'latest_run_id'", sql)
        self.assertIn("'raw_observations_total'", sql)
        self.assertIn("'latest_run_raw_observations'", sql)
        self.assertNotIn("COUNT(*) FROM nodes ", sql)
        self.assertNotIn("COUNT(*) FROM edges ", sql)
        self.assertNotIn("COUNT(*) FROM evidence ", sql)

    def test_ruby_summary_counts_current_graph_and_source_facts(self):
        sql = build_ruby_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'ruby.file')", sql)
        self.assertIn("canonical_edges.edge_kind = 'references'", sql)
        self.assertIn("raw_observations.kind = 'ruby.gem_dependency'", sql)
        self.assertIn("'no_execution', true", sql)

    def test_js_summary_counts_current_graph_and_source_facts(self):
        sql = build_js_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("COUNT(*) FILTER (WHERE kind = 'js.file')", sql)
        self.assertIn("canonical_edges.edge_kind = 'references'", sql)
        self.assertIn("raw_observations.kind = 'js.import'", sql)
        self.assertIn("'no_execution', true", sql)

    def test_email_summary_keeps_privacy_markers(self):
        sql = build_email_summary_query_sql("/tmp/fixture's repo")

        self.assertIn("fixture''s repo", sql)
        self.assertIn("canonical_nodes.kind LIKE 'email.%'", sql)
        self.assertIn("raw_observations.kind = 'email.address'", sql)
        self.assertIn("'no_provider_api', true", sql)
        self.assertIn("'no_body_text', true", sql)
