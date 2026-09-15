import io
import json
import unittest
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main

class CliLocalOpsRuntimeDbUnitTests(unittest.TestCase):
    def test_local_runtime_and_db_json_commands_delegate_to_safe_helpers(self):
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
                    "unit-test",
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
                    "unit-test",
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
                    "upgrade-schema",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--backup-first",
                    "--yes",
                    "--reason",
                    "unit-test",
                    "--dry-run",
                    "--json",
                ),
                "upgrade_graph_schema",
                {"command": "upgrade-schema"},
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
                    "unit-test",
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
    def test_graph_schema_upgrade_owns_cross_plane_maintenance_window(self):
        events: list[str] = []

        @contextmanager
        def maintenance_window(home, database):
            self.assertEqual(home, "/tmp/repo-map-home")
            self.assertEqual(database, "repomap_test")
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        def upgrade(*args, **kwargs):
            self.assertEqual(events, ["enter"])
            return SimpleNamespace(
                to_jsonable=lambda: {"command": "upgrade-schema", "result": "ok"}
            )

        with (
            patch(
                "repomap_kg.cli.maintenance_window_for_graph_upgrade",
                side_effect=maintenance_window,
            ),
            patch("repomap_kg.cli.upgrade_graph_schema", side_effect=upgrade),
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main(
                [
                    "local",
                    "db",
                    "upgrade-schema",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--backup-first",
                    "--yes",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["enter", "exit"])

    def test_local_runtime_and_db_text_commands_delegate_to_formatters(self):
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
                    "upgrade-schema",
                    "--repo-map-home",
                    "/tmp/repo-map-home",
                    "--database",
                    "repomap_test",
                    "--backup-first",
                    "--yes",
                    "--dry-run",
                ),
                "upgrade_graph_schema",
                "format_graph_schema_upgrade_table",
                "db upgrade-schema ok",
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
