import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.extractors.config.generic import extract_config_file_observations


class PublicBranchConfigRuntimeCliIntegrationTests(unittest.TestCase):
    def test_yaml_inline_collection_contracts_are_preserved(self):
        observations = extract_config_file_observations(
            "inline.yaml",
            """
empty_list: []
empty_map: {}
inline:
  values: [one, "two, too", {nested: [true, false, null, ~, -7, 3.14], quoted: 'yes'}, [inner, list]]
  mapping: {alpha: one, beta: [x, y], gamma: {nested: value}}
  trailing: [one, two,]
""",
        )
        duplicate = extract_config_file_observations(
            "inline-duplicate.yaml",
            "inline: {a: one, a: two}\n",
        )
        malformed = extract_config_file_observations(
            "inline-malformed.yaml",
            "inline: [one, {nested: bad]]\n",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertEqual(observations[0].metadata["format"], "yaml")
        self.assertEqual(pointer_by_path["/empty_list"].metadata["value_type"], "array")
        self.assertEqual(pointer_by_path["/empty_map"].metadata["value_type"], "object")
        self.assertEqual(pointer_by_path["/inline/values"].metadata["value_type"], "array")
        self.assertEqual(pointer_by_path["/inline/mapping"].metadata["value_type"], "object")
        self.assertEqual(
            pointer_by_path["/inline/mapping/alpha"].metadata["value_summary"],
            "one",
        )
        self.assertEqual(
            pointer_by_path["/inline/mapping/gamma/nested"].metadata["value_summary"],
            "value",
        )
        self.assertEqual(pointer_by_path["/inline/trailing"].metadata["value_type"], "array")
        self.assertEqual([item.kind for item in duplicate], ["config.parse_error"])
        self.assertEqual(duplicate[0].metadata["error_kind"], "duplicate-yaml-key")
        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-yaml")

    def test_local_runtime_and_db_cli_json_contracts_are_preserved(self):
        def result(command):
            return SimpleNamespace(
                to_jsonable=lambda: {"command": command, "result": "ok"}
            )

        cases = (
            (
                ("local", "setup", "--repo-map-home", "/tmp/repo-map-home", "--json"),
                "setup_local_runtime",
                {"command": "setup"},
            ),
            (
                ("local", "up", "--repo-map-home", "/tmp/repo-map-home", "--dry-run", "--json"),
                "up_local_runtime",
                {"command": "up"},
            ),
            (
                ("local", "down", "--repo-map-home", "/tmp/repo-map-home", "--dry-run", "--json"),
                "down_local_runtime",
                {"command": "down"},
            ),
            (
                (
                    "local",
                    "status",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--check-containers",
                    "--json",
                ),
                "query_local_runtime_status",
                {"command": "status"},
            ),
            (
                (
                    "local",
                    "db",
                    "dump",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap",
                    "--reason",
                    "int-test",
                    "--dry-run",
                    "--json",
                ),
                "dump_database",
                {"command": "dump"},
            ),
            (
                (
                    "local",
                    "db",
                    "dump-all",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--reason",
                    "int-test",
                    "--dry-run",
                    "--json",
                ),
                "dump_all_databases",
                {"command": "dump-all"},
            ),
            (
                (
                    "local",
                    "db",
                    "backups",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--json",
                ),
                "list_backups",
                {"command": "backups"},
            ),
            (
                (
                    "local",
                    "db",
                    "backup-info",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "backup-id",
                    "--json",
                ),
                "read_backup_info",
                {"command": "backup-info"},
            ),
            (
                (
                    "local",
                    "db",
                    "init",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--from-source",
                    "--dry-run",
                    "--json",
                ),
                "init_database_from_source",
                {"command": "init-source"},
            ),
            (
                (
                    "local",
                    "db",
                    "init",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--from-dump",
                    "backup-id",
                    "--dry-run",
                    "--json",
                ),
                "init_database_from_dump",
                {"command": "init-dump"},
            ),
            (
                (
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--backup-first",
                    "--yes",
                    "--reason",
                    "int-test",
                    "--dry-run",
                    "--json",
                ),
                "drop_database",
                {"command": "drop"},
            ),
        )

        for argv, helper_name, payload in cases:
            with self.subTest(helper=helper_name):
                stdout = io.StringIO()
                with patch(
                    f"repomap_kg.cli.{helper_name}",
                    return_value=result(payload["command"]),
                ) as helper:
                    with redirect_stdout(stdout):
                        exit_code = main(list(argv))

                self.assertEqual(exit_code, 0)
                self.assertEqual(json.loads(stdout.getvalue()), payload | {"result": "ok"})
                helper.assert_called_once()

    def test_local_runtime_and_db_cli_text_contracts_are_preserved(self):
        def result(command):
            return SimpleNamespace(command=command, result="ok")

        cases = (
            (
                ("local", "setup", "--repo-map-home", "/tmp/repo-map-home"),
                "setup_local_runtime",
                "format_local_runtime_table",
                "local setup ok",
            ),
            (
                ("local", "up", "--repo-map-home", "/tmp/repo-map-home", "--dry-run"),
                "up_local_runtime",
                "format_local_runtime_table",
                "local up ok",
            ),
            (
                ("local", "down", "--repo-map-home", "/tmp/repo-map-home", "--dry-run"),
                "down_local_runtime",
                "format_local_runtime_table",
                "local down ok",
            ),
            (
                ("local", "status", "--repo-map-home", "/tmp/repo-map-home"),
                "query_local_runtime_status",
                "format_local_runtime_table",
                "local status ok",
            ),
            (
                (
                    "local",
                    "db",
                    "dump",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap",
                    "--dry-run",
                ),
                "dump_database",
                "format_backup_result_table",
                "db dump ok",
            ),
            (
                (
                    "local",
                    "db",
                    "dump-all",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--dry-run",
                ),
                "dump_all_databases",
                "format_backup_result_table",
                "db dump-all ok",
            ),
            (
                ("local", "db", "backups", "--repo-map-home", "/tmp/repo-map-home"),
                "list_backups",
                "format_backup_listing_table",
                "db backups ok",
            ),
            (
                (
                    "local",
                    "db",
                    "backup-info",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "backup-id",
                ),
                "read_backup_info",
                "format_backup_info_table",
                "db backup-info ok",
            ),
            (
                (
                    "local",
                    "db",
                    "init",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--from-source",
                    "--dry-run",
                ),
                "init_database_from_source",
                "format_init_result_table",
                "db init ok",
            ),
            (
                (
                    "local",
                    "db",
                    "drop",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--backup-first",
                    "--yes",
                    "--dry-run",
                ),
                "drop_database",
                "format_drop_result_table",
                "db drop ok",
            ),
        )

        for argv, helper_name, formatter_name, table_text in cases:
            with self.subTest(helper=helper_name):
                stdout = io.StringIO()
                command = " ".join(argv[:3])
                with (
                    patch(
                        f"repomap_kg.cli.{helper_name}",
                        return_value=result(command),
                    ) as helper,
                    patch(
                        f"repomap_kg.cli.{formatter_name}",
                        return_value=table_text,
                    ) as formatter,
                    redirect_stdout(stdout),
                ):
                    exit_code = main(list(argv))

                self.assertEqual(exit_code, 0)
                self.assertEqual(stdout.getvalue().strip(), table_text)
                helper.assert_called_once()
                formatter.assert_called_once()
