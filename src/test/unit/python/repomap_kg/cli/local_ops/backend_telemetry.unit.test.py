from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
    from repomap_kg.storage.authority import RefreshResult
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import main
from repomap_kg.ops.refresh import OpsRefreshGraphResult
from repomap_kg.storage.backend_telemetry import ConnectionTelemetryError


def test_direct_refresh_parser_accepts_private_backend_telemetry_fds() -> None:
    args = build_parser().parse_args(
        [
            "ops",
            "refresh-graph",
            "--config",
            "fixture.toml",
            "--graph",
            "fixture",
            "--backend-telemetry-fd",
            "9",
            "--backend-telemetry-ack-fd",
            "10",
        ]
    )

    assert args.mode == "direct"
    assert args.backend_telemetry_fd == 9
    assert args.backend_telemetry_ack_fd == 10


def test_refresh_help_does_not_expose_private_backend_telemetry_fds(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["ops", "refresh-graph", "--help"])

    assert raised.value.code == 0
    assert "backend-telemetry" not in capsys.readouterr().out


def test_direct_refresh_forwards_private_backend_telemetry_to_staged_load(
    tmp_path,
) -> None:
    config_path = tmp_path / "ops.toml"
    config_path.write_text(
        """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "fixture"
name = "Fixture"
root_path = "/placeholder/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "/placeholder/server-memory"
mode = "read_only"
""",
        encoding="utf-8",
    )
    telemetry = object()
    result = OpsRefreshGraphResult(
        graph_id="fixture",
        repository_name="fixture",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        root_path_display="/placeholder/fixture",
        root_path_expanded="/placeholder/fixture",
        result=cast("RefreshResult", "success"),
        repository_id=1,
        run_id=2,
        files=1,
        observations=1,
    )

    with (
        patch(
            "repomap_kg.cli.telemetry_from_inherited_fds",
            return_value=telemetry,
        ) as create_telemetry,
        patch("repomap_kg.cli.refresh_graph", return_value=result) as refresh,
        redirect_stdout(io.StringIO()),
    ):
        exit_code = main(
            [
                "ops",
                "refresh-graph",
                "--config",
                str(config_path),
                "--graph",
                "fixture",
                "--backend-telemetry-fd",
                "9",
                "--backend-telemetry-ack-fd",
                "10",
                "--json",
            ]
        )

    assert exit_code == 0
    create_telemetry.assert_called_once_with(9, 10)
    assert refresh.call_args.kwargs["backend_telemetry"] is telemetry
    assert refresh.call_args.kwargs["ingestion_mode"] == "staged"


def test_coordinator_mode_rejects_private_backend_telemetry_fds() -> None:
    stderr = io.StringIO()
    with (
        patch("repomap_kg.cli.run_coordinator_refresh") as coordinator,
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
                "fixture",
                "--idempotency-key",
                "fixture-request",
                "--backend-telemetry-fd",
                "9",
                "--backend-telemetry-ack-fd",
                "10",
            ]
        )

    assert exit_code == 1
    assert "coordinator_rejects_backend_telemetry" in stderr.getvalue()
    coordinator.assert_not_called()


def test_direct_telemetry_setup_error_does_not_disclose_the_fds() -> None:
    stderr = io.StringIO()
    with (
        patch(
            "repomap_kg.cli.telemetry_from_inherited_fds",
            side_effect=ConnectionTelemetryError("backend telemetry channel is unavailable"),
        ),
        redirect_stderr(stderr),
    ):
        exit_code = main(
            [
                "ops",
                "refresh-graph",
                "--config",
                "fixture.toml",
                "--graph",
                "fixture",
                "--backend-telemetry-fd",
                "9",
                "--backend-telemetry-ack-fd",
                "10",
            ]
        )

    assert exit_code == 1
    assert "9" not in stderr.getvalue()
    assert "10" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("arguments", "missing_fd"),
    [
        (["--backend-telemetry-fd", "9"], "9"),
        (["--backend-telemetry-ack-fd", "10"], "10"),
    ],
)
def test_direct_refresh_rejects_an_unpaired_private_telemetry_fd(
    arguments: list[str],
    missing_fd: str,
) -> None:
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = main(
            [
                "ops",
                "refresh-graph",
                "--config",
                "fixture.toml",
                "--graph",
                "fixture",
                *arguments,
            ]
        )

    assert exit_code == 1
    assert missing_fd not in stderr.getvalue()
