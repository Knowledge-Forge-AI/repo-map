from __future__ import annotations

from contextlib import contextmanager
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
    from repomap_kg.storage.authority import RefreshResult
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import main
from repomap_kg.ops.refresh import OpsRefreshGraphResult


_CONFIG = """\
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
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "/placeholder/server-memory"
mode = "read_only"
"""


def test_scale13_parser_keeps_staging_event_descriptor_hidden() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "ops",
            "refresh-graph",
            "--repo-map-home",
            "/placeholder/home",
            "--graph",
            "fixture",
            "--staging-event-fd",
            "9",
        ]
    )
    assert args.staging_event_fd == 9
    assert "staging-event-fd" not in parser.format_help()


def test_scale13_direct_dispatch_constructs_actual_path_measurements() -> None:
    frames: list[tuple[str, dict[str, object]]] = []
    channel = SimpleNamespace(
        send=lambda category, payload: frames.append((category, payload)),
        close=lambda: frames.append(("closed", {})),
    )

    @contextmanager
    def admission(_home):
        yield

    def refresh_side_effect(_config, _graph, **kwargs):
        measurements = kwargs["staging_measurements"]
        with measurements.phase("refresh.source_discovery"):
            pass
        return OpsRefreshGraphResult(
            graph_id="fixture",
            repository_name="fixture",
            privacy="public-dev",
            enabled=True,
            mcp_visible=False,
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            result=cast("RefreshResult", "success"),
            repository_id=1,
            run_id=1,
            files=1,
            observations=1,
        )

    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "repo.rp.toml").write_text(_CONFIG, encoding="utf-8")
        with (
            patch(
                "repomap_kg.cli.staging_event_channel_from_inherited_fd",
                return_value=channel,
            ),
            patch("repomap_kg.cli.refresh_graph", side_effect=refresh_side_effect),
            patch(
                "repomap_kg.cli.maintenance_activity_for_home",
                side_effect=admission,
            ),
            patch("sys.stdout", new=io.StringIO()),
        ):
            exit_code = main(
                [
                    "ops",
                    "refresh-graph",
                    "--repo-map-home",
                    directory,
                    "--graph",
                    "fixture",
                    "--staging-event-fd",
                    "9",
                    "--json",
                ]
            )

    assert exit_code == 0
    assert [category for category, _payload in frames] == [
        "phase",
        "phase",
        "closed",
    ]


def test_scale13_dispatch_closes_channel_when_config_loading_fails() -> None:
    closed: list[bool] = []
    channel = SimpleNamespace(send=lambda *_args: None, close=lambda: closed.append(True))

    with (
        patch(
            "repomap_kg.cli.staging_event_channel_from_inherited_fd",
            return_value=channel,
        ),
        patch("sys.stderr", new=io.StringIO()),
    ):
        exit_code = main(
            [
                "ops",
                "refresh-graph",
                "--config",
                "/missing/config.rp.toml",
                "--graph",
                "fixture",
                "--staging-event-fd",
                "9",
            ]
        )

    assert exit_code == 1
    assert closed == [True]
