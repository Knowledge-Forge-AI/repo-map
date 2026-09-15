"""Configuration, models, and utility helpers for Postgres containers."""

from __future__ import annotations

import os
import re
import secrets
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Callable

from repomap_test_support.resource_ledger import RunIdentity


DEFAULT_TEST_POSTGRES_PORT = 55433
DEFAULT_TEST_POSTGRES_RUNTIME = "docker"
TEST_POSTGRES_IMAGE = (
    "postgres:16-alpine@sha256:"
    "e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
)
TEST_POSTGRES_USER = "repo_map_test"
TEST_POSTGRES_DATABASE = "repomap_test"

SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def safe_run_id_text(value: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "", value.lower())
    return (safe or uuid.uuid4().hex)[:24]


def is_local_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def redact_secret_text(value: str) -> str:
    redacted = value
    for key in ("POSTGRES_PASSWORD", "PGPASSWORD", "password", "secret", "token"):
        redacted = re.sub(
            rf"({re.escape(key)}=)[^\s]+",
            r"\1[REDACTED]",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def redacted_command(command: list[str]) -> str:
    from repomap_test_support import postgres_container as owner

    return " ".join(owner.redact_secret_text(part) for part in command)


def bounded_text(value: str, limit: int = 1200) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def run(
    command: list[str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    try:
        return subprocess.run(
            command,
            check=True,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as error:
        raise AssertionError(
            f"command failed: {command}\n"
            f"stdout:\n{error.stdout}\n"
            f"stderr:\n{error.stderr}"
        ) from error


@dataclass(frozen=True)
class PostgresContainerConfig:
    runtime: str = DEFAULT_TEST_POSTGRES_RUNTIME
    host_port: int = DEFAULT_TEST_POSTGRES_PORT
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    password: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    image: str = TEST_POSTGRES_IMAGE
    user: str = TEST_POSTGRES_USER
    database: str = TEST_POSTGRES_DATABASE
    bind_host: str = "127.0.0.1"
    readiness_timeout_seconds: float = 30.0
    resource_identity: RunIdentity | None = None

    def __post_init__(self) -> None:
        from repomap_test_support import postgres_container as owner

        safe_run_id = owner.safe_run_id_text(self.run_id)
        if safe_run_id != self.run_id:
            object.__setattr__(self, "run_id", safe_run_id)
        if self.runtime not in ("docker", "podman"):
            raise ValueError("pg container runtime must be docker or podman")
        if self.bind_host != "127.0.0.1":
            raise ValueError("pg container bind host must be 127.0.0.1")
        if self.host_port == 5432:
            raise ValueError("pg container test port must not default to 5432")


@dataclass(frozen=True)
class PostgresContainerDatabase:
    host: str
    port: int
    user: str
    database: str
    psql_command: str
    password: str | None = field(default=None, repr=False)

    @property
    def socket_dir(self) -> str:
        return self.host

    @property
    def psql_args(self) -> list[str]:
        return [
            "-h",
            self.host,
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            self.database,
        ]

    def psql_scalar(self, sql: str) -> str:
        command = [
            self.psql_command,
            *self.psql_args,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        from repomap_test_support import postgres_container as owner

        result = owner.run(command, sql)
        lines = [line for line in result.stdout.splitlines() if line]
        return lines[-1] if lines else ""

    def create_database(self, database: str) -> PostgresContainerDatabase:
        """Create and return one isolated disposable database connection."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", database):
            raise ValueError("test database name is invalid")
        self.psql_scalar(f'CREATE DATABASE "{database}";')
        return PostgresContainerDatabase(
            host=self.host,
            port=self.port,
            user=self.user,
            database=database,
            psql_command=self.psql_command,
            password=self.password,
        )


def build_psql_wrapper_script(
    *,
    password: str,
    runtime: str,
    container_name: str,
) -> str:
    return f"""\
#!/usr/bin/env python3
import os
import subprocess
import sys

args = sys.argv[1:]
normalized = []
stdin_payload = None
i = 0
while i < len(args):
    if args[i] == "-h" and i + 1 < len(args):
        normalized.extend(["-h", "127.0.0.1"])
        i += 2
    elif args[i] == "-p" and i + 1 < len(args):
        normalized.extend(["-p", "5432"])
        i += 2
    elif args[i] == "-f" and i + 1 < len(args):
        with open(args[i + 1], "rb") as source_file:
            content = source_file.read()
        stdin_payload = (stdin_payload or b"") + content + b"\\n"
        i += 2
    elif args[i].startswith("--file="):
        with open(args[i].split("=", 1)[1], "rb") as source_file:
            content = source_file.read()
        stdin_payload = (stdin_payload or b"") + content + b"\\n"
        i += 1
    else:
        normalized.append(args[i])
        i += 1

env = os.environ.copy()
env["PGPASSWORD"] = {password!r}
command = [
    {runtime!r},
    "exec",
    "-i",
    "-e",
    "PGPASSWORD",
    {container_name!r},
    "psql",
    *normalized,
]
if stdin_payload is None:
    result = subprocess.run(command, env=env)
else:
    result = subprocess.run(command, env=env, input=stdin_payload)
raise SystemExit(result.returncode)
"""
