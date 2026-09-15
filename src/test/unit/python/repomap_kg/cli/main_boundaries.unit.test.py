"""Unit tests for CLI main formatting, argument parsing, and metadata helpers."""

from __future__ import annotations

from argparse import Namespace
import unittest

from repomap_kg.cli.main import (
    HOST_CATEGORY_KEY_PREFIX,
    canonical_edge_identity_metadata_from_args,
    canonical_host_mutator_category,
    canonical_metadata_text_values,
    format_cli_table_row,
    psql_args_from_args,
    render_host_mutator_table_value,
)
from repomap_kg.storage import StorageSchemaError


class CliMainBoundariesUnitTests(unittest.TestCase):
    """Test CLI helper formatting, category extraction, and argument mapping."""

    def test_render_host_mutator_table_value_types(self):
        self.assertEqual(render_host_mutator_table_value(None), "")
        self.assertEqual(render_host_mutator_table_value(True), "true")
        self.assertEqual(render_host_mutator_table_value(False), "false")
        self.assertEqual(render_host_mutator_table_value(["a", "b", 3]), "a,b,3")
        self.assertEqual(render_host_mutator_table_value(42), "42")
        self.assertEqual(render_host_mutator_table_value("plain"), "plain")

    def test_format_cli_table_row_alignment(self):
        row = {"col1": "val1", "col2": "val2"}
        columns = ("col1", "col2")
        widths = {"col1": 10, "col2": 10}
        rendered = format_cli_table_row(row, columns, widths)
        self.assertEqual(rendered, "val1        val2      ")

    def test_canonical_host_mutator_category(self):
        prefix = HOST_CATEGORY_KEY_PREFIX
        self.assertEqual(
            canonical_host_mutator_category(f"{prefix}system-packages"),
            "system-packages",
        )
        self.assertIsNone(canonical_host_mutator_category("non_matching_key"))

    def test_canonical_metadata_text_values_deduplication(self):
        metadata = {
            "single": "val1",
            "multi": ["val2", "val1", 123, "val3"],  # 123 is non-string
            "other": 456,
        }
        values = canonical_metadata_text_values(
            metadata, ("single", "multi", "other", "absent")
        )
        self.assertEqual(values, ("val1", "val2", "val3"))

    def test_canonical_edge_identity_metadata_from_args(self):
        # Valid JSON object
        args_valid = Namespace(identity_metadata_json='{"key": "value"}')
        payload = canonical_edge_identity_metadata_from_args(args_valid)
        self.assertEqual(payload, {"key": "value"})

        # Invalid JSON
        args_bad_json = Namespace(identity_metadata_json="not-json")
        with self.assertRaises(StorageSchemaError):
            canonical_edge_identity_metadata_from_args(args_bad_json)

        # JSON that is not a dict
        args_not_dict = Namespace(identity_metadata_json="[1, 2, 3]")
        with self.assertRaises(StorageSchemaError):
            canonical_edge_identity_metadata_from_args(args_not_dict)

    def test_psql_args_from_args(self):
        args_full = Namespace(
            pg_host="localhost",
            pg_port="5432",
            pg_user="repo_user",
            pg_database="repomap_test",
        )
        args_list = psql_args_from_args(args_full)
        self.assertEqual(
            args_list,
            ["-h", "localhost", "-p", "5432", "-U", "repo_user", "-d", "repomap_test"],
        )

        args_empty = Namespace(pg_host="", pg_port=None, pg_user="", pg_database="")
        self.assertEqual(psql_args_from_args(args_empty), [])


if __name__ == "__main__":
    unittest.main()
