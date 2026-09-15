from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_kg.runtime.plan import LocalRuntimePlan
from repomap_kg.runtime.schema_manifest import query_schema_manifest
from repomap_kg.runtime.schema_upgrade import (
    GraphSchemaUpgradeResult,
    bootstrap_schema_ledger,
    format_graph_schema_upgrade_table,
    query_schema_ledger,
    schema_ledger_exists,
    upgrade_graph_schema,
)
from repomap_kg.storage import StorageSchemaError, discover_migrations


def _plan() -> LocalRuntimePlan:
    tmp = Path("/tmp")
    return LocalRuntimePlan(
        tmp, None, LocalRuntimeIdentity.from_home(tmp), "docker", "127.0.0.1", 5432, "127.0.0.1", False, 8080, "repomap", "repo_map_test",
    )


class TestGraphSchemaUpgradeUnit:
    @staticmethod
    def unexpected_runner(command, **kwargs):
        raise AssertionError(command)

    def test_dry_run_and_formatter_are_bounded_without_runtime_access(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)
        result = upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            dry_run=True,
            command_runner=self.unexpected_runner,
        )

        assert result.result == "dry_run"
        assert result.schema_after == "planned"
        assert "planned_actions=" in format_graph_schema_upgrade_table(result)
        assert "planned_actions=" not in format_graph_schema_upgrade_table(
            GraphSchemaUpgradeResult("success", "current", "current")
        )

    @pytest.mark.parametrize(
        ("target_exists", "ledger_exists", "reference_exists", "message"),
        [
            (False, False, False, "does not exist"),
            (True, True, False, "exact-current"),
            (True, False, True, "reference database already exists"),
        ],
    )
    def test_upgrade_refuses_invalid_target_states_before_backup(
        self,
        tmp_path: Path,
        target_exists: bool,
        ledger_exists: bool,
        reference_exists: bool,
        message: str,
    ) -> None:
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)
        existence = [target_exists]
        if target_exists and not ledger_exists:
            existence.append(reference_exists)

        with (
            patch(
                "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container"
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.database_exists",
                side_effect=existence,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.schema_ledger_exists",
                return_value=ledger_exists,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
                return_value=tuple(
                    (
                        migration.ordinal,
                        migration.changeset_id,
                        migration.relative_path,
                        migration.checksum,
                    )
                    for migration in discover_migrations()
                ),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade._repository_identity_target",
                return_value=None,
            ),
            patch("repomap_kg.runtime.schema_upgrade.dump_database") as backup,
        ):
            with pytest.raises(LocalDbBackupError, match=message):
                upgrade_graph_schema(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=True,
                    timestamp="20260716T120002Z",
                    command_runner=self.unexpected_runner,
                )

        backup.assert_not_called()

    def test_schema_query_helpers_parse_bounded_results_and_reject_bad_ledger(
        self,
    ) -> None:
        plan = _plan()

        with patch(
            "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"t\n", stderr=b""),
        ):
            assert schema_ledger_exists(plan, "repomap", self.unexpected_runner)

        ledger_stdout = b"1\ttest:one\t2026/one.sql\t" + (b"a" * 64) + b"\n"
        with patch(
            "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=ledger_stdout, stderr=b""
            ),
        ):
            rows = query_schema_ledger(plan, "repomap", self.unexpected_runner)
        assert rows == ((1, "test:one", "2026/one.sql", "a" * 64),)

        with patch(
            "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=b"invalid\n", stderr=b""
            ),
        ):
            with pytest.raises(LocalDbBackupError, match="invalid row"):
                query_schema_ledger(plan, "repomap", self.unexpected_runner)

        with patch(
            "repomap_kg.runtime.schema_manifest.run_container_command",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=b"one\n\ntwo\n", stderr=b""
            ),
        ):
            assert query_schema_manifest(plan, "repomap", self.unexpected_runner
            ) == ("one", "two")

    def test_ledger_bootstrap_translates_catalog_errors_and_streams_sql(self) -> None:
        plan = _plan()
        runner = self.unexpected_runner

        with patch(
            "repomap_kg.runtime._schema_upgrade_ledger._default_graph_schema_ledger_bootstrap_sql",
            side_effect=StorageSchemaError("catalog unavailable"),
        ):
            with pytest.raises(LocalDbBackupError, match="catalog unavailable"):
                bootstrap_schema_ledger(plan, "repomap", runner)

        with (
            patch(
                "repomap_kg.runtime._schema_upgrade_ledger._default_graph_schema_ledger_bootstrap_sql",
                return_value="BEGIN;\nCOMMIT;\n",
            ),
            patch(
                "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command"
            ) as execute,
        ):
            bootstrap_schema_ledger(plan, "repomap", runner)

        assert execute.call_args.kwargs["input_data"] == b"BEGIN;\nCOMMIT;\n"

    def test_upgrade_backs_up_before_exact_match_adoption_and_cleans_reference(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)
        identity = LocalRuntimeIdentity.from_home(home)
        events: list[str] = []
        backup_path = home / "backups" / "verified"
        backup = SimpleNamespace(
            plan=SimpleNamespace(
                backup_path=backup_path,
                backup_id="public-backup-id",
            )
        )
        inspection = SimpleNamespace(
            checksum_verified=True,
            dump_summaries=(object(),),
            manifest={"restore_supported": True},
        )
        expected_ledger = tuple(
            (
                migration.ordinal,
                migration.changeset_id,
                migration.relative_path,
                migration.checksum,
            )
            for migration in discover_migrations()
        )

        def record(name: str, value=None):
            def action(*args, **kwargs):
                events.append(name)
                return value

            return action

        def _fingerprint(*_args: object, **_kwargs: object) -> tuple[str, ...]:
            events.append("fingerprint")
            return ("exact-schema",)

        with (
            patch(
                "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container",
                record("inspect-runtime", object()),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.database_exists",
                side_effect=[True, False],
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.schema_ledger_exists",
                return_value=False,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.dump_database",
                record("backup", backup),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.inspect_backup",
                record("verify-backup", inspection),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.create_database",
                record("create-reference"),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.apply_source_schema",
                record("initialize-reference"),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.query_schema_manifest",
                side_effect=_fingerprint,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.bootstrap_schema_ledger",
                record("bootstrap-ledger"),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
                record("verify-ledger", expected_ledger),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.drop_runtime_database",
                record("drop-reference"),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.reconcile_graph_database_roles",
                record("reconcile-roles"),
            ),
        ):
            result = upgrade_graph_schema(
                home,
                database="repomap",
                backup_first=True,
                confirmed=True,
                timestamp="20260716T120000Z",
                command_runner=self.unexpected_runner,
            )

        assert result.result == "success"
        assert result.backup_verified
        assert result.rollback_available
        assert result.schema_before == "supported-preledger"
        assert result.schema_after == "current"
        assert events.index("backup") < events.index("create-reference")
        assert events.index("verify-backup") < events.index("bootstrap-ledger")
        assert events.index("drop-reference") < events.index("reconcile-roles")
        assert events[-1] == "reconcile-roles"
        assert identity.home_hash not in result.to_jsonable().values()

    def test_upgrade_refuses_unknown_schema_without_bootstrap_and_keeps_backup(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)
        backup = SimpleNamespace(
            plan=SimpleNamespace(
                backup_path=home / "backups" / "verified",
                backup_id="public-backup-id",
            )
        )
        inspection = SimpleNamespace(
            checksum_verified=True,
            dump_summaries=(object(),),
            manifest={"restore_supported": True},
        )

        with (
            patch(
                "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container",
                return_value=object(),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.database_exists",
                side_effect=[True, False],
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.schema_ledger_exists",
                return_value=False,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.dump_database",
                return_value=backup,
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.inspect_backup",
                return_value=inspection,
            ),
            patch("repomap_kg.runtime.schema_upgrade.create_database"),
            patch("repomap_kg.runtime.schema_upgrade.apply_source_schema"),
            patch(
                "repomap_kg.runtime.schema_upgrade.query_schema_manifest",
                side_effect=[("unknown",), ("expected",)],
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.bootstrap_schema_ledger"
            ) as bootstrap,
            patch("repomap_kg.runtime.schema_upgrade.drop_runtime_database") as drop,
        ):
            with pytest.raises(LocalDbBackupError, match="not a supported pre-ledger"):
                upgrade_graph_schema(
                    home,
                    database="repomap",
                    backup_first=True,
                    confirmed=True,
                    timestamp="20260716T120001Z",
                    command_runner=self.unexpected_runner,
                )

        bootstrap.assert_not_called()
        drop.assert_called_once()

    @pytest.mark.parametrize(
        ("backup_first", "confirmed", "message"),
        [
            (False, True, "backup-first"),
            (True, False, "confirmation"),
        ],
    )
    def test_upgrade_requires_backup_first_and_confirmation_before_runtime_access(
        self,
        tmp_path: Path,
        backup_first: bool,
        confirmed: bool,
        message: str,
    ) -> None:
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)

        with pytest.raises(LocalDbBackupError, match=message):
            upgrade_graph_schema(
                home,
                database="repomap",
                backup_first=backup_first,
                confirmed=confirmed,
                command_runner=self.unexpected_runner,
            )
