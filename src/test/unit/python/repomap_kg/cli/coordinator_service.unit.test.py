import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import main
from repomap_kg.service_package.operations import (
    ServiceActionResult,
    ServicePackageError,
)


@pytest.mark.parametrize(
    "action",
    [
        "install",
        "status",
        "start",
        "stop",
        "restart",
        "upgrade",
        "uninstall",
        "render",
        "validate",
    ],
)
def test_neutral_coordinator_service_actions_require_one_repo_map_home(action):
    args = build_parser().parse_args(
        [
            "ops",
            "coordinator-service",
            action,
            "--repo-map-home",
            "/placeholder/home",
        ]
    )
    assert args.ops_command == "coordinator-service"
    assert args.coordinator_service_action == action
    assert args.repo_map_home == "/placeholder/home"
    assert not hasattr(args, "platform")
    assert not hasattr(args, "executable")


@pytest.mark.parametrize("option", ["--platform", "--executable", "--launchctl"])
def test_service_cli_exposes_no_native_or_executable_selection(option):
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(
            [
                "ops",
                "coordinator-service",
                "status",
                "--repo-map-home",
                "/placeholder/home",
                option,
                "synthetic-value",
            ]
        )
    assert raised.value.code == 2


def test_service_action_emits_public_safe_json():
    stdout = io.StringIO()
    result = ServiceActionResult(
        action="install",
        platform="darwin",
        artifact="launchd_plist",
        service_identity="org.repomap.coordinator",
        installed=True,
        active=False,
        enabled=None,
        changed=True,
    )
    with patch(
        "repomap_kg.cli.run_coordinator_service_action",
        return_value=result,
    ) as run:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-service",
                    "install",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--json",
                ]
            )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == result.as_dict()
    assert "/placeholder/home" not in stdout.getvalue()
    run.assert_called_once_with("install", "/placeholder/home")


def test_render_is_an_explicit_non_mutating_raw_definition_surface():
    stdout = io.StringIO()
    definition = "[Service]\nExecStart=synthetic\n"
    with patch(
        "repomap_kg.cli.run_coordinator_service_action",
        return_value=definition,
    ) as run:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-service",
                    "render",
                    "--repo-map-home",
                    "/placeholder/home",
                ]
            )

    assert exit_code == 0
    assert stdout.getvalue() == definition
    run.assert_called_once_with("render", "/placeholder/home")


def test_service_errors_are_bounded_and_path_sanitized():
    stderr = io.StringIO()
    with patch(
        "repomap_kg.cli.run_coordinator_service_action",
        side_effect=ServicePackageError(
            "service_definition_unsafe /Users/example/private-definition"
        ),
    ):
        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "ops",
                    "coordinator-service",
                    "status",
                    "--repo-map-home",
                    "/placeholder/home",
                ]
            )

    assert exit_code == 1
    assert "service_definition_unsafe" in stderr.getvalue()
    assert "/Users/example" not in stderr.getvalue()
    assert "[redacted-path]" in stderr.getvalue()


def test_packaged_foreground_scrubs_ambient_authority_before_start():
    observed = {}

    def serve(_home, callback, *, psql_path):
        observed["environment"] = dict(os.environ)
        observed["psql_path"] = psql_path
        callback(
            {
                "command": "coordinator-serve",
                "result": "ready",
                "startup_recovery": {
                    "scanned": 0,
                    "resolved": 0,
                    "pending": 0,
                    "route_changed": 0,
                    "unavailable": 0,
                },
            }
        )

    with patch.dict(
        os.environ,
        {
            "LANG": "C.UTF-8",
            "HOME": "/placeholder/home",
            "DATABASE_PASSWORD": "synthetic-secret",
            "UNRELATED": "value",
        },
        clear=True,
    ):
        with patch("repomap_kg.cli.serve_configured_coordinator", side_effect=serve):
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "ops",
                        "coordinator-serve",
                        "--repo-map-home",
                        "/placeholder/home",
                        "--service-package-environment",
                        "--service-package-psql",
                        "/placeholder/bin/psql",
                        "--json",
                    ]
                )

    assert exit_code == 0
    assert observed == {
        "environment": {"LANG": "C.UTF-8"},
        "psql_path": "/placeholder/bin/psql",
    }


def test_container_foreground_accepts_fixed_psql_and_bounded_startup_wait():
    observed = {}

    def serve(_home, callback, *, psql_path, startup_wait_seconds):
        observed["environment"] = dict(os.environ)
        observed["psql_path"] = psql_path
        observed["startup_wait_seconds"] = startup_wait_seconds
        callback(
            {
                "command": "coordinator-serve",
                "result": "ready",
                "startup_recovery": {
                    "scanned": 0,
                    "resolved": 0,
                    "pending": 0,
                    "route_changed": 0,
                    "unavailable": 0,
                },
            }
        )

    with patch.dict(os.environ, {"REPOMAP_HOME": "/repo-map-home"}, clear=True):
        with patch("repomap_kg.cli.serve_configured_coordinator", side_effect=serve):
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "ops",
                        "coordinator-serve",
                        "--repo-map-home",
                        "/repo-map-home",
                        "--service-package-psql",
                        "/usr/lib/postgresql/16/bin/psql",
                        "--startup-wait-seconds",
                        "75",
                        "--json",
                    ]
                )

    assert exit_code == 0
    assert observed == {
        "environment": {"REPOMAP_HOME": "/repo-map-home"},
        "psql_path": "/usr/lib/postgresql/16/bin/psql",
        "startup_wait_seconds": 75,
    }


def test_coordinator_health_renders_non_json_not_ready_status():
    payload = {"result": "not_ready", "status": "unavailable"}
    stdout = io.StringIO()
    with (
        patch("repomap_kg.cli.coordinator_health", return_value=payload) as health,
        patch(
            "repomap_kg.cli.format_coordinator_health_table",
            return_value="coordinator unavailable",
        ),
        redirect_stdout(stdout),
    ):
        exit_code = main(
            [
                "ops",
                "coordinator-health",
                "--repo-map-home",
                "/placeholder/home",
            ]
        )

    assert exit_code == 1
    assert stdout.getvalue() == "coordinator unavailable\n"
    health.assert_called_once_with("/placeholder/home")


def test_service_package_environment_requires_fixed_psql():
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "ops",
                "coordinator-serve",
                "--repo-map-home",
                "/placeholder/home",
                "--service-package-environment",
            ]
        )

    assert exit_code == 1
    assert stderr.getvalue() == (
        "ERROR: coordinator_service_package_contract_invalid\n"
    )


def test_foreground_without_packaged_psql_renders_recovery_table():
    stdout = io.StringIO()

    def serve(_home, callback):
        callback(
            {
                "startup_recovery": {
                    "scanned": 2,
                    "resolved": 1,
                    "pending": 1,
                    "route_changed": 0,
                    "unavailable": 0,
                }
            }
        )

    with (
        patch("repomap_kg.cli.serve_configured_coordinator", side_effect=serve),
        redirect_stdout(stdout),
    ):
        exit_code = main(
            [
                "ops",
                "coordinator-serve",
                "--repo-map-home",
                "/placeholder/home",
            ]
        )

    assert exit_code == 0
    assert stdout.getvalue() == (
        "RepoMap local coordinator ready\n"
        "startup_recovery_scanned=2\n"
        "startup_recovery_resolved=1\n"
        "startup_recovery_pending=1\n"
        "startup_recovery_route_changed=0\n"
        "startup_recovery_unavailable=0\n"
    )


def test_coordinator_connection_failure_does_not_invoke_service_packaging():
    with (
        patch(
            "repomap_kg.cli.run_coordinator_refresh",
            side_effect=RuntimeError("coordinator_unavailable"),
        ),
        patch("repomap_kg.cli.run_coordinator_service_action") as service_action,
        redirect_stderr(io.StringIO()),
    ):
        with pytest.raises(RuntimeError, match="coordinator_unavailable"):
            main(
                [
                    "ops",
                    "refresh-graph",
                    "--mode",
                    "coordinator",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--graph",
                    "repo-map",
                    "--idempotency-key",
                    "manual-refresh-001",
                ]
            )
    service_action.assert_not_called()
