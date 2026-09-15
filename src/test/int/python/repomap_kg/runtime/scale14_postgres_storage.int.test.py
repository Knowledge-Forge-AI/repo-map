from __future__ import annotations

import socket
from pathlib import Path
import re
import subprocess
import time

import pytest

pytestmark = pytest.mark.requires_build_profile

from repomap_kg.runtime.backup import init_database_from_source
from repomap_kg.runtime.local import (
    down_local_runtime,
    setup_local_runtime,
    up_local_runtime,
)
from repomap_kg.runtime.plan import build_local_runtime_plan
from scale14_postgres_storage import PostgresStorageAuthority


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_postgres(plan) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        completed = subprocess.run(
            (
                plan.container_runtime,
                "exec",
                plan.identity.postgres_container,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                plan.user,
                "-d",
                plan.database,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            shell=False,
        )
        if completed.returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError("disposable PostgreSQL runtime did not become ready")


def test_scale14_exact_pgdata_authority_on_disposable_local_runtime(
    tmp_path: Path,
) -> None:
    home = tmp_path / "public-safe-runtime"
    setup_local_runtime(home)
    repository = home / "repo-map"
    repository.mkdir()
    repository.joinpath("app.py").write_text(
        "def public_fixture() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    config_path = home / "repomap.rpl.toml"
    config = config_path.read_text(encoding="utf-8")
    config = re.sub(
        r"^server_host_port = \d+",
        f"server_host_port = {_available_port()}",
        config,
        flags=re.MULTILINE,
    )
    config = re.sub(
        r"^host_port = \d+",
        f"host_port = {_available_port()}",
        config,
        flags=re.MULTILINE,
    )
    config_path.write_text(config, encoding="utf-8")
    setup_local_runtime(home)
    started = False
    try:
        result = up_local_runtime(home)
        started = result.result == "started"
        plan = build_local_runtime_plan(home)
        _wait_for_postgres(plan)
        authority = PostgresStorageAuthority(plan)
        baseline = authority.capture_baseline()

        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + """

[[graphs]]
id = "scale14-storage"
name = "SCALE14 Storage"
root_path = "./repo-map"
repository_name = "scale14-storage"
database = "repomap_scale14_storage"
privacy = "public-dev"
enabled = false
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
""",
            encoding="utf-8",
        )
        expanded_plan = build_local_runtime_plan(home)
        database = next(
            name for name in expanded_plan.graph_databases if name not in plan.graph_databases
        )
        initialized = init_database_from_source(home, database=database)
        current = authority.capture()

        assert initialized.result == "success"
        assert initialized.database_created is True
        assert initialized.schema_ready is True
        assert baseline.availability == "available"
        assert current.availability == "available"
        assert current.delta_bytes is not None and current.delta_bytes > 0
        assert current.free_bytes is not None and current.free_bytes > 0
        assert current.sampling_elapsed_ns < 1_000_000_000
        assert current.scope == "owned_postgresql_pgdata"
    finally:
        if started:
            stopped = down_local_runtime(home)
            assert stopped.result == "stopped"
