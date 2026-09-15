import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.coordinator.local_lifecycle import CoordinatorControlError


def test_coordinator_control_status_returns_nonzero_when_absent():
    stdout = io.StringIO()
    payload = {
        "command": "coordinator-control-status",
        "result": "unavailable",
        "database_available": False,
        "schema_compatible": None,
        "schema_version": None,
    }
    with patch("repomap_kg.cli.coordinator_control_status", return_value=payload) as status:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-control-status",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--json",
                ]
            )
    assert exit_code == 1
    assert json.loads(stdout.getvalue()) == payload
    status.assert_called_once_with("/placeholder/home")


def test_coordinator_control_init_is_explicit_and_reports_ready():
    stdout = io.StringIO()
    payload = {
        "command": "coordinator-control-init",
        "result": "ready",
        "database_created": True,
        "schema_version": 1,
    }
    with patch("repomap_kg.cli.initialize_coordinator_control", return_value=payload) as init:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-control-init",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--json",
                ]
            )
    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == payload
    init.assert_called_once_with("/placeholder/home")


def test_coordinator_control_upgrade_delegates_backup_confirmation_and_dry_run():
    stdout = io.StringIO()
    payload = {
        "command": "coordinator-control-upgrade",
        "result": "planned",
        "backup_verified": False,
    }
    with patch(
        "repomap_kg.cli.upgrade_coordinator_control", return_value=payload
    ) as upgrade:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-control-upgrade",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--backup-first",
                    "--yes",
                    "--reason",
                    "unit-test",
                    "--dry-run",
                    "--json",
                ]
            )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == payload
    upgrade.assert_called_once_with(
        "/placeholder/home",
        backup_first=True,
        confirmed=True,
        dry_run=True,
        reason="unit-test",
    )


def test_coordinator_control_failure_is_bounded():
    stderr = io.StringIO()
    with patch(
        "repomap_kg.cli.initialize_coordinator_control",
        side_effect=CoordinatorControlError("coordinator_control_init_failed"),
    ):
        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "ops",
                    "coordinator-control-init",
                    "--repo-map-home",
                    "/placeholder/home",
                ]
            )
    assert exit_code == 1
    assert stderr.getvalue() == "ERROR: coordinator_control_init_failed\n"
