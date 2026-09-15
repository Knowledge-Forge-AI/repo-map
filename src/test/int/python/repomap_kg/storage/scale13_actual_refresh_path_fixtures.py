from __future__ import annotations
import hashlib
import os
from pathlib import Path
import sys
import psycopg
from scale12_operation_state import (
    ActiveOperationState,
    operation_event_from_payload,
)
from scale13_phase_state import PhaseAttributionState



def _required_row(cursor: psycopg.Cursor[tuple[object, ...]]) -> tuple[object, ...]:
    row = cursor.fetchone()
    assert row is not None
    return row


def _write_fixture(root: Path) -> None:
    root.mkdir()
    root.joinpath("app.py").write_text(
        "from pathlib import Path\n\ndef load(path: Path) -> str:\n    return path.read_text()\n",
        encoding="utf-8",
    )
    root.joinpath("README.md").write_text("# Public fixture\n", encoding="utf-8")


def _fixture_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.iterdir()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_lifecycle_frames(frames) -> None:
    phases = PhaseAttributionState()
    operations = ActiveOperationState()
    for frame in frames:
        if frame.category == "phase":
            phases.accept(frame.payload)
        elif frame.category == "operation":
            operations.accept(operation_event_from_payload(frame.payload))
    phases.close()
    operations.close()


def _assert_bounded_lifecycle_gaps(frames) -> None:
    last_terminal_offset: int | None = None
    for frame in frames:
        if frame.category not in {"phase", "operation"}:
            continue
        offset = frame.payload["monotonic_offset_ns"]
        if frame.payload["event_category"] == "started":
            if last_terminal_offset is not None:
                assert 0 <= offset - last_terminal_offset < 500_000_000
            continue
        last_terminal_offset = offset


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_config(home: Path, root: Path, postgres) -> None:
    home.mkdir()
    home.joinpath("repo.rp.toml").write_text(
        f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = {_toml_string(str(postgres.socket_dir))}
port = {postgres.port}
database = {_toml_string(postgres.database)}
user = {_toml_string(postgres.user)}
password_env = "REPOMAP_SCALE13_UNUSED_PASSWORD"

[[graphs]]
id = "public-fixture"
name = "Public Fixture"
root_path = {_toml_string(str(root))}
repository_name = "public-fixture"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "server-memory.jsonl"
mode = "read_only"
""",
        encoding="utf-8",
    )


def _actual_refresh_argv(
    home: Path,
    postgres,
    event_fd: int | None,
    *,
    test_control_code: str | None = None,
    control_ready_fd: int | None = None,
    backend_event_fd: int | None = None,
    backend_ack_fd: int | None = None,
) -> tuple[str, ...]:
    product_arguments = (
        "ops",
        "refresh-graph",
        "--config",
        str(home / "repo.rp.toml"),
        "--graph",
        "public-fixture",
        "--psql-command",
        postgres.psql_command,
        "--json",
    )
    arguments: tuple[str, ...] = (sys.executable, "-m", "repomap_kg", *product_arguments)
    if event_fd is None:
        return arguments
    arguments = (*arguments, "--staging-event-fd", str(event_fd))
    if backend_event_fd is not None and backend_ack_fd is not None:
        arguments = (
            *arguments,
            "--backend-telemetry-fd",
            str(backend_event_fd),
            "--backend-telemetry-ack-fd",
            str(backend_ack_fd),
        )
    if test_control_code is None:
        return arguments
    readiness_arguments: tuple[str, ...] = ()
    if control_ready_fd is not None:
        readiness_arguments = (
            "--control-ready-fd",
            str(control_ready_fd),
            "--expected-parent-pid",
            str(os.getpid()),
        )
    return (
        sys.executable,
        "-m",
        "repomap_test_support.scale14_actual_refresh_child",
        "--cancel-code",
        test_control_code,
        "--wait-seconds",
        "3",
        *readiness_arguments,
        "--",
        *arguments[3:],
    )
