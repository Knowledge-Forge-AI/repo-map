import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    maintenance_window_for_graph_upgrade,
)
from repomap_kg.runtime.backup import (
    drop_database,
    dump_database,
    init_database_from_dump,
    init_database_from_source,
)
from repomap_kg.runtime.backup_commands import (
    planned_create_database_command,
    planned_drop_database_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError
from repomap_kg.runtime.plan import LocalRuntimePlan, build_local_runtime_plan
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema


class Arch7C1ExactLifecycleAllowlistUnitTests(unittest.TestCase):
    def test_lifecycle_dry_runs_refuse_unrelated_safe_database_before_io(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)

            def unexpected_runner(*args, **kwargs):
                raise AssertionError("unauthorized lifecycle reached container IO")

            operations = (
                lambda: dump_database(
                    home,
                    database="unrelated_db",
                    dry_run=True,
                    command_runner=unexpected_runner,
                ),
                lambda: init_database_from_source(
                    home,
                    database="unrelated_db",
                    dry_run=True,
                    command_runner=unexpected_runner,
                ),
                lambda: init_database_from_dump(
                    home,
                    database="unrelated_db",
                    backup="missing-backup",
                    dry_run=True,
                    command_runner=unexpected_runner,
                ),
                lambda: drop_database(
                    home,
                    database="unrelated_db",
                    backup_first=True,
                    dry_run=True,
                    command_runner=unexpected_runner,
                ),
                lambda: upgrade_graph_schema(
                    home,
                    database="unrelated_db",
                    backup_first=True,
                    dry_run=True,
                    command_runner=unexpected_runner,
                ),
            )

            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(LocalDbBackupError) as raised:
                        operation()
                    self.assertEqual(
                        raised.exception.diagnostics[0].code,
                        "database-not-owned",
                    )

    def test_graph_and_control_databases_are_owned_lifecycle_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            plan = build_local_runtime_plan(home)

            results = tuple(
                dump_database(home, database=database, dry_run=True)
                for database in plan.owned_databases
            )

        self.assertEqual(
            tuple(result.plan.database for result in results),
            plan.owned_databases,
        )
        self.assertNotIn(plan.maintenance_database, plan.owned_databases)

    def test_graph_upgrade_window_rejects_unowned_target_before_locking(self):
        events: list[str] = []

        class FakeAuthority:
            graph_databases = ("repomap",)

            @contextmanager
            def maintenance_window(self, *, graph_databases):
                events.append("entered")
                yield

        with patch(
            "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
            return_value=FakeAuthority(),
        ):
            with self.assertRaises(MaintenanceUnavailableError):
                with maintenance_window_for_graph_upgrade(
                    "/tmp/repo-map-home",
                    "unrelated_db",
                ):
                    self.fail("unowned maintenance window opened")

        self.assertEqual(events, [])

    def test_database_ddl_commands_use_resolved_maintenance_target(self):
        plan = cast(
            LocalRuntimePlan,
            SimpleNamespace(
                container_runtime="docker",
                identity=SimpleNamespace(postgres_container="repomap-postgres"),
                user="repomap",
                maintenance_database="maintenance_db",
            ),
        )

        create_command = planned_create_database_command(plan)
        drop_command = planned_drop_database_command(plan, "repomap")

        self.assertEqual(create_command[create_command.index("-d") + 1], "maintenance_db")
        self.assertEqual(drop_command[drop_command.index("-d") + 1], "maintenance_db")

    def test_control_lifecycle_uses_resolved_maintenance_target(self):
        databases: list[str] = []
        authority = object.__new__(LocalControlAuthority)
        authority._database = "repomap_control"
        authority._graph_databases = ("repomap",)
        authority._maintenance_database = "maintenance_db"

        class FakeConnection:
            def execute(self, *args, **kwargs):
                return SimpleNamespace(fetchone=lambda: (True,))

        @contextmanager
        def connect(database, *, autocommit=False):
            databases.append(database)
            yield FakeConnection()

        setattr(authority, "_connect", connect)

        self.assertTrue(authority.reference_database_exists("repomap_control"))
        self.assertEqual(databases, ["maintenance_db"])

    def test_control_authority_refuses_unowned_database_before_connection(self):
        authority = object.__new__(LocalControlAuthority)
        authority._database = "repomap_control"
        authority._graph_databases = ("repomap",)
        authority._maintenance_database = "maintenance_db"
        setattr(
            authority,
            "_connect",
            lambda *args, **kwargs: self.fail(
                "unowned control lifecycle target reached database IO"
            ),
        )

        with self.assertRaises(CoordinatorControlError):
            authority.reference_database_exists("unrelated_db")
        with self.assertRaises(CoordinatorControlError):
            authority.control_store_for("unrelated_db")
        with self.assertRaises(MaintenanceUnavailableError):
            with authority.maintenance_window(graph_databases=("unrelated_db",)):
                self.fail("unowned maintenance window opened")


if __name__ == "__main__":
    unittest.main()
