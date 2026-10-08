"""Integration tests for Slice 8 Group S8-B: Operations Readback Connector and Topology Decision."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
import unittest
from unittest import mock

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.readback import (
    MISSING_DATABASE_MESSAGE,
    MissingDatabaseReadbackError,
    OpsPsqlExecution,
    _OpsContainerReadbackPlan,
    execute_ops_json_readback,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


class OperationalError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None = None


class ConnectionError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None = "08006"


def _make_container_internal_config(root_dir: Path) -> Any:
    home = root_dir / "home"
    repo = root_dir / "repo"
    home.mkdir(parents=True, exist_ok=True)
    repo.mkdir(parents=True, exist_ok=True)
    (home / "repomap.rpl.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=repo, private_root=repo / "priv")
        .replace('host = "127.0.0.1"', 'host = "postgres"'),
        encoding="utf-8",
    )
    return load_ops_config_home(home)


class Slice8ReadbackTopologyIntegrationTests(unittest.TestCase):
    """Integration scenarios for operational readback connectors, fallback boundaries, and topology hints."""

    def test_s8_b01_readback_eligible_host_failure_with_unavailable_container_plan(self) -> None:
        """Eligible host connectivity failure augments error with container topology hint when fallback is unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))
            unavailable_hint = " No container was available."
            empty_plan = _OpsContainerReadbackPlan(execution=None, unavailable_hint=unavailable_hint)

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    side_effect=OSError("host connection refused"),
                ) as mock_run:
                    with mock.patch(
                        "repomap_kg.ops.readback._resolve_container_readback_plan",
                        return_value=empty_plan,
                    ) as mock_plan:
                        with self.assertRaises(StorageSchemaError) as cm:
                            execute_ops_json_readback(
                                config,
                                database="repomap",
                                sql="SELECT 1",
                                label="probe_b01",
                                expected_shape="object",
                                mode="host_then_container",
                            )
                        self.assertIn("No container was available", str(cm.exception))
                        mock_plan.assert_called_once_with(config, allow_loopback_host=True)
                        self.assertEqual(mock_run.call_count, 1)

    def test_s8_b02_readback_eligible_host_failure_with_controlled_container_fallback(self) -> None:
        """Eligible host failure successfully falls back to container psql execution returning expected payload."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))
            container_exec = OpsPsqlExecution(
                command="podman",
                args_prefix=("exec", "-i", "repomap-postgres", "psql"),
            )
            valid_plan = _OpsContainerReadbackPlan(execution=container_exec, unavailable_hint="")

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                mock_proc = subprocess.CompletedProcess(
                    args=["podman", "exec", "-i", "repomap-postgres", "psql"],
                    returncode=0,
                    stdout='{"readback_status": "container_ok"}',
                    stderr="",
                )
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    side_effect=[
                        OSError("host connect refused"),
                        mock_proc,
                    ],
                ) as mock_run:
                    with mock.patch(
                        "repomap_kg.ops.readback._resolve_container_readback_plan",
                        return_value=valid_plan,
                    ):
                        result = execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="probe_b02",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                    self.assertEqual(result, {"readback_status": "container_ok"})
                    self.assertEqual(mock_run.call_count, 2)
                    fallback_argv = mock_run.call_args_list[1].args[0]
                    self.assertEqual(fallback_argv[0], "podman")
                    self.assertEqual(
                        list(fallback_argv[1:5]),
                        ["exec", "-i", "repomap-postgres", "psql"],
                    )

    def test_s8_b03_readback_query_syntax_and_shape_error_suppresses_fallback(self) -> None:
        """SQL syntax errors and JSON shape mismatches do not trigger container fallback planning or execution."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                # 1. SQL syntax error
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    side_effect=StorageSchemaError("psql failed with code 1: ERROR: syntax error at or near 'SELEC'"),
                ) as mock_run:
                    with mock.patch("repomap_kg.ops.readback._resolve_container_readback_plan") as mock_plan:
                        with self.assertRaises(StorageSchemaError) as cm_syntax:
                            execute_ops_json_readback(
                                config,
                                database="repomap",
                                sql="SELEC 1",
                                label="syntax_probe",
                                expected_shape="object",
                                mode="host_then_container",
                            )
                        self.assertIn("syntax error", str(cm_syntax.exception))
                        mock_plan.assert_not_called()
                        self.assertEqual(mock_run.call_count, 1)

                # 2. Shape mismatch (expected array, received object)
                shape_proc = subprocess.CompletedProcess(
                    args=["psql"],
                    returncode=0,
                    stdout='{"single_record": 1}',
                    stderr="",
                )
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    return_value=shape_proc,
                ) as mock_run_shape:
                    with mock.patch("repomap_kg.ops.readback._resolve_container_readback_plan") as mock_plan_shape:
                        with self.assertRaises(StorageSchemaError) as cm_shape:
                            execute_ops_json_readback(
                                config,
                                database="repomap",
                                sql="SELECT 1",
                                label="shape_probe",
                                expected_shape="array",
                                mode="host_then_container",
                            )
                        self.assertIn("psql did not return shape_probe as a json array", str(cm_shape.exception).lower())
                        mock_plan_shape.assert_not_called()
                        self.assertEqual(mock_run_shape.call_count, 1)

    def test_s8_b04_readback_psycopg_database_presence_diagnosis_attribution(self) -> None:
        """psycopg connect failure invokes database presence diagnosis and attributes absent database."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psycopg"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                os.environ.pop("PGCONNECT_TIMEOUT", None)
                os.environ.pop("PGOPTIONS", None)

                with mock.patch("repomap_kg.storage.readback_driver._import_psycopg") as mock_import:
                    mock_psycopg = mock.MagicMock()
                    mock_import.return_value = mock_psycopg

                    # Case A: Database is diagnosed as absent in maintenance catalog
                    mock_cursor_absent = mock.MagicMock()
                    mock_cursor_absent.fetchone.return_value = (False,)
                    mock_conn_absent = mock.MagicMock()
                    mock_conn_absent.cursor.return_value.__enter__.return_value = mock_cursor_absent
                    mock_conn_absent.__enter__.return_value = mock_conn_absent

                    mock_psycopg.connect.side_effect = [
                        OperationalError("could not connect to server"),
                        mock_conn_absent,
                    ]

                    with self.assertRaises(MissingDatabaseReadbackError) as cm_absent:
                        execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="presence_probe",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                    self.assertEqual(str(cm_absent.exception), MISSING_DATABASE_MESSAGE)

                    # Case B: Database exists in catalog, so error remains connection failure
                    mock_cursor_exists = mock.MagicMock()
                    mock_cursor_exists.fetchone.return_value = (True,)
                    mock_conn_exists = mock.MagicMock()
                    mock_conn_exists.cursor.return_value.__enter__.return_value = mock_cursor_exists
                    mock_conn_exists.__enter__.return_value = mock_conn_exists

                    mock_psycopg.connect.side_effect = [
                        OperationalError("could not connect to server"),
                        mock_conn_exists,
                    ]

                    with self.assertRaises(StorageSchemaError) as cm_exists:
                        execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="presence_probe_2",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                    self.assertIn("psycopg connection failed for presence_probe_2", str(cm_exists.exception))

    def test_s8_b05_readback_psycopg_error_guidance_without_container_fallback(self) -> None:
        """In psycopg mode, connectivity failure augments error with guidance without attempting container fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psycopg"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                with mock.patch("repomap_kg.storage.readback_driver._import_psycopg") as mock_import:
                    mock_psycopg = mock.MagicMock()
                    mock_import.return_value = mock_psycopg
                    mock_psycopg.connect.side_effect = ConnectionError("psycopg connection refused")

                    with mock.patch("repomap_kg.ops.readback._resolve_container_readback_plan") as mock_plan:
                        with self.assertRaises(StorageSchemaError) as cm:
                            execute_ops_json_readback(
                                config,
                                database="repomap",
                                sql="SELECT 1",
                                label="psycopg_guidance_probe",
                                expected_shape="object",
                                mode="host_then_container",
                            )
                        self.assertIn("Direct DB host-port exposure is disabled", str(cm.exception))
                        mock_plan.assert_not_called()

    def test_s8_b06_readback_custom_psql_command_and_selector_routing_contract(self) -> None:
        """Explicit psql_command parameter routes directly and satisfies array shape contract."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_container_internal_config(Path(tmp))

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                mock_proc = subprocess.CompletedProcess(
                    args=["/opt/custom/bin/psql-v16"],
                    returncode=0,
                    stdout='[{"row_id": 1}, {"row_id": 2}]',
                    stderr="",
                )
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    return_value=mock_proc,
                ) as mock_run:
                    result = execute_ops_json_readback(
                        config,
                        database="repomap",
                        sql="SELECT row_id FROM test_table",
                        label="custom_cmd_probe",
                        expected_shape="array",
                        mode="host_only",
                        psql_command="/opt/custom/bin/psql-v16",
                    )
                    self.assertEqual(result, [{"row_id": 1}, {"row_id": 2}])
                    self.assertEqual(mock_run.call_count, 1)
                    self.assertEqual(mock_run.call_args.args[0][0], "/opt/custom/bin/psql-v16")

            # Conflicting connector selectors raise StorageSchemaError
            with mock.patch.dict(
                "os.environ",
                {PG_CONNECTOR_ENV: "psql", READBACK_DRIVER_ENV: "psycopg"},
            ):
                with self.assertRaises(StorageSchemaError) as cm_conflict:
                    execute_ops_json_readback(
                        config,
                        database="repomap",
                        sql="SELECT 1",
                        label="conflict_probe",
                        expected_shape="object",
                        mode="host_only",
                    )
                self.assertIn("conflicting postgresql connector selectors", str(cm_conflict.exception).lower())


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
