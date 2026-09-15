import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import main
from repomap_kg.coordinator.local_mode import CoordinatorModeError


def test_refresh_graph_parser_keeps_direct_mode_as_default():
    args = build_parser().parse_args(
        ["ops", "refresh-graph", "--config", "ops.toml", "--graph", "repo-map"]
    )
    assert args.mode == "direct"
    assert args.idempotency_key is None


def test_refresh_graph_help_explains_explicit_coordinator_prerequisite(capsys):
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["ops", "refresh-graph", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "existing service" in output
    assert "never" in output
    assert "falls" in output
    assert "back" in output


def test_explicit_coordinator_mode_emits_durable_terminal_result():
    stdout = io.StringIO()
    expected = {
        "command": "refresh-graph",
        "mode": "coordinator",
        "result": "success",
        "replayed": False,
        "job": {"job_id": "job-1", "graph_id": "repo-map", "state": "succeeded"},
    }
    with patch("repomap_kg.cli.run_coordinator_refresh", return_value=expected) as run:
        with redirect_stdout(stdout):
            exit_code = main(
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
                    "--coordinator-wait-seconds",
                    "30",
                    "--json",
                ]
            )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == expected
    run.assert_called_once_with(
        "/placeholder/home",
        "repo-map",
        "manual-refresh-001",
        wait_timeout_seconds=30,
    )


@pytest.mark.parametrize(
    "extra, category",
    [
        (["--config", "ops.toml"], "coordinator_requires_repo_map_home"),
        (["--repo-map-home", "/placeholder/home"], "coordinator_requires_idempotency_key"),
        (
            [
                "--repo-map-home",
                "/placeholder/home",
                "--idempotency-key",
                "manual-refresh-001",
                "--psql-command",
                "psql",
            ],
            "coordinator_rejects_psql_command",
        ),
    ],
)
def test_coordinator_mode_rejects_ambient_or_client_selected_authority(extra, category):
    stderr = io.StringIO()
    with patch("repomap_kg.cli.run_coordinator_refresh") as run:
        with redirect_stderr(stderr):
            exit_code = main(
                ["ops", "refresh-graph", "--mode", "coordinator", "--graph", "repo-map", *extra]
            )
    assert exit_code == 1
    assert category in stderr.getvalue()
    run.assert_not_called()


def test_unavailable_coordinator_never_falls_back_to_direct_refresh():
    stderr = io.StringIO()
    with (
        patch(
            "repomap_kg.cli.run_coordinator_refresh",
            side_effect=CoordinatorModeError("coordinator_unavailable"),
        ),
        patch("repomap_kg.cli.refresh_graph") as direct,
        redirect_stderr(stderr),
    ):
        exit_code = main(
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
    assert exit_code == 1
    assert "coordinator_unavailable" in stderr.getvalue()
    direct.assert_not_called()


def test_foreground_coordinator_launch_emits_ready_json():
    stdout = io.StringIO()
    ready = {
        "command": "coordinator-serve",
        "mode": "coordinator",
        "result": "ready",
        "startup_recovery": {"scanned": 0, "resolved": 0, "pending": 0},
    }

    def serve(home, callback):
        assert home == "/placeholder/home"
        callback(ready)

    with patch("repomap_kg.cli.serve_configured_coordinator", side_effect=serve):
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "coordinator-serve",
                    "--repo-map-home",
                    "/placeholder/home",
                    "--json",
                ]
            )
    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == ready
