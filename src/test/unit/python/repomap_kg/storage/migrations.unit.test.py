import subprocess
import tempfile
import unittest
import re
from pathlib import Path
from unittest.mock import patch

from repomap_kg import storage as storage_facade
from repomap_kg.storage import rows as storage_rows, sql as storage_sql
from repomap_kg.storage import canonical as storage_canonical
from repomap_kg.graph.edge_kinds import CANONICAL_EDGE_KINDS
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    discover_migrations,
)

GO9_CANONICAL_EDGE_KINDS = frozenset(
    {
        "benchmarks",
        "constructs",
        "declares",
        "defers",
        "embeds",
        "examples",
        "fuzzes",
        "instantiates",
        "method_of",
        "panics",
        "receives",
        "recovers",
        "replaces_module",
        "requires_module",
        "returns",
        "selects",
        "sends",
        "starts_goroutine",
        "workspace_uses",
    }
)

def _canonical_edge_kind_sets_from_sql(sql: str) -> tuple[frozenset[str], ...]:
    constraint_sets = []
    for match in re.finditer(r"edge_kind\s+IN\s*\((?P<values>[^;]+?)\)", sql, re.S):
        values = frozenset(re.findall(r"'([a-z_]+)'", match.group("values")))
        if values:
            constraint_sets.append(values)
    return tuple(constraint_sets)

class StorageMigrationUnitTests(unittest.TestCase):
    def test_ref4_storage_facade_reexports_split_helper_modules(self):
        self.assertIs(
            storage_facade.canonical_node_record_from_storage_payload,
            storage_rows.canonical_node_record_from_storage_payload,
        )
        self.assertIs(
            storage_facade.build_canonical_node_query_sql,
            storage_sql.build_canonical_node_query_sql,
        )
        self.assertIs(
            storage_facade.query_canonical_node_records,
            storage_canonical.query_canonical_node_records,
        )

    def test_default_rdbms_root_points_to_main_resources(self):
        root = default_rdbms_root()

        self.assertEqual(root.name, "rdbms")
        self.assertEqual(root.parent.name, "resources")

    def test_discover_migrations_reads_include_all_and_changesets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text(
                """
--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables
CREATE TABLE repositories(id BIGSERIAL PRIMARY KEY);
"""
            )

            migrations = discover_migrations(root)

        self.assertEqual(len(migrations), 1)
        self.assertEqual(migrations[0].path, migration)
        self.assertEqual(
            migrations[0].changeset_id,
            "slair:2026_06_28-001-core-create_graph_tables",
        )

    def test_schema_edge_kind_migration_matches_current_canonical_model(self):
        migration_path = (
            default_rdbms_root()
            / "2026"
            / "07"
            / "12-002-core-add-go-source-instance-edge-kind.sql"
        )
        migrations = discover_migrations(None)
        discovered_paths = {migration.path for migration in migrations}

        self.assertIn(migration_path, discovered_paths)

        sql = migration_path.read_text(encoding="utf-8")
        constraint_sets = _canonical_edge_kind_sets_from_sql(sql)

        self.assertGreaterEqual(len(constraint_sets), 2)
        self.assertEqual(constraint_sets[0], CANONICAL_EDGE_KINDS)
        self.assertEqual(constraint_sets[-1], CANONICAL_EDGE_KINDS - {"instance_of"})

    def test_discover_migrations_rejects_unformatted_sql(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text("CREATE TABLE repositories(id BIGINT);\n")

            with self.assertRaisesRegex(StorageSchemaError, "formatted sql"):
                discover_migrations(root)

    def test_discover_migrations_rejects_missing_include_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            root.mkdir()
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )

            with self.assertRaisesRegex(StorageSchemaError, "missing includeAll"):
                discover_migrations(root)

    def test_discover_migrations_rejects_missing_changeset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: 2026
      relativeToChangelogFile: true
"""
            )
            migration.write_text("--liquibase formatted sql\nSELECT 1;\n")

            with self.assertRaisesRegex(StorageSchemaError, "missing a changeset"):
                discover_migrations(root)

    def test_apply_migrations_wraps_psql_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "rdbms"
            migration = root / "2026" / "06" / "28-001-core-create_graph_tables.sql"
            migration.parent.mkdir(parents=True)
            (root / "changelog.yaml").write_text(
                """
databaseChangeLog:
  - includeAll:
      path: "2026"
      relativeToChangelogFile: true
"""
            )
            migration.write_text(
                """
--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables
SELECT 1;
"""
            )
            error = subprocess.CalledProcessError(
                2,
                ["/bin/psql"],
                output="",
                stderr="relation already exists\n",
            )

            with patch("repomap_kg.storage.subprocess.run", side_effect=error):
                with self.assertRaisesRegex(
                    StorageSchemaError,
                    "relation already exists",
                ):
                    apply_migrations(root, ["-d", "postgres"], psql_command="/bin/psql")
