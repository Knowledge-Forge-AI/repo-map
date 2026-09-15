"""Contracts for the outer RepoMap integration-test sandbox boundary."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping


ENV_ACTIVE = "_REPOMAP_TEST_SANDBOX_ACTIVE"
ENV_TOKEN = "_REPOMAP_TEST_SANDBOX_TOKEN"
ENV_SYSTEM_DEADLINE_EPOCH = "_REPOMAP_SYSTEM_DEADLINE_EPOCH"
ENV_SYSTEM_START_EPOCH = "_REPOMAP_SYSTEM_START_EPOCH"
INNER_DOCKER_HOST = "unix:///run/repomap-docker.sock"
INNER_DOCKER_SOCKET = Path("/run/repomap-docker.sock")
INNER_OWNER_PATH = Path("/run/repomap-test-sandbox-owner")
EXACT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
EXACT_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_TAG = "repomap-test-sandbox:py313-go125-docker294-v1"
IMAGE_OWNER_LABEL = "org.repomap.test.sandbox.image"
IMAGE_RECIPE_LABEL = "org.repomap.test.sandbox.recipe"
INNER_REPORT_ROOT = Path("/sandbox-report/report")
INNER_TEST_SCRATCH_ROOT = Path("/sandbox-scratch/test-scratch")
MAX_REPORT_ARCHIVE_BYTES = 72 * 1024 * 1024
MAX_REPORT_MEMBERS = 4096
MAX_REPORT_CONTENT_BYTES = 64 * 1024 * 1024
TEST_POSTGRES_IMAGE = (
    "postgres:16-alpine@sha256:"
    "e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
)
PRODUCTION_POSTGRES_IMAGE = (
    "postgres:16-bookworm@sha256:"
    "92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55"
)
ALPINE_PROBE_IMAGE = (
    "alpine:latest@sha256:"
    "28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b"
)
PYTHON_RELEASE_IMAGE = (
    "python:3.12-slim-bookworm@sha256:"
    "d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
)
GO_RELEASE_IMAGE = (
    "golang:1.25-bookworm@sha256:"
    "ea341baa9bd5ba6784f6d7161ace70544349a6242d54d34a0fbfd2c4d51c9d58"
)


@dataclass(frozen=True)
class HostSnapshot:
    containers: frozenset[str]
    images: frozenset[str]
    volumes: frozenset[str]
    networks: frozenset[str]


Runner = Callable[..., subprocess.CompletedProcess[str]]
Captured = Callable[..., subprocess.CompletedProcess[str]]
LogFollower = subprocess.Popen[bytes]
LogFollowerFactory = Callable[[list[str]], LogFollower]
Snapshotter = Callable[[Runner], HostSnapshot]
BoundaryProver = Callable[..., None]
ReportArchiveReader = Callable[[str, bool], bytes | None]


def active_sandbox(
    environ: Mapping[str, str] | None = None,
    *,
    marker_path: Path,
    host_socket_exists: bool | None,
    inner_socket_exists: bool | None,
    active_name: str = ENV_ACTIVE,
    token_name: str = ENV_TOKEN,
    docker_host: str = INNER_DOCKER_HOST,
    inner_socket: Path = INNER_DOCKER_SOCKET,
) -> bool:
    env = os.environ if environ is None else environ
    active = env.get(active_name)
    token = env.get(token_name)
    if active is None and token is None:
        return False
    if active != "1" or token is None or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        raise RuntimeError("invalid integration sandbox internal marker")
    try:
        recorded = marker_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("integration sandbox owner marker is unavailable") from error
    if recorded != token:
        raise RuntimeError("integration sandbox owner marker does not match")
    if env.get("DOCKER_HOST") != docker_host:
        raise RuntimeError("integration sandbox inner Docker authority is invalid")
    if inner_socket_exists is None:
        inner_socket_exists = inner_socket.is_socket()
    if not inner_socket_exists:
        raise RuntimeError("integration sandbox inner Docker socket is unavailable")
    if host_socket_exists is None:
        host_socket_exists = Path("/var/run/docker.sock").exists()
    if host_socket_exists:
        raise RuntimeError("host Docker socket path is present inside integration sandbox")
    return True


def outer_run_command(
    *,
    image_id: str,
    container_name: str,
    repo_root: Path,
    host_gid: int,
    argv: list[str],
    exact_id: re.Pattern[str] = EXACT_ID,
    inner_docker_host: str = INNER_DOCKER_HOST,
    start_epoch_name: str = ENV_SYSTEM_START_EPOCH,
    deadline_epoch_name: str = ENV_SYSTEM_DEADLINE_EPOCH,
) -> list[str]:
    if exact_id.fullmatch(image_id) is None:
        raise RuntimeError("sandbox image must be an exact Docker image ID")
    return [
        "docker",
        "run",
        "-d",
        "--privileged",
        "--cgroupns=host",
        "--name",
        container_name,
        "--label",
        "org.repomap.test.sandbox=true",
        "--label",
        "org.repomap.test.sandbox.backend=monolithic-dind-v1",
        "--tmpfs",
        "/var/lib/docker:rw,exec,nosuid,nodev,size=4g",
        "--tmpfs",
        "/sandbox-scratch:rw,exec,nosuid,nodev,size=8g",
        "--tmpfs",
        "/run:rw,nosuid,nodev,mode=0755,size=64m",
        "--mount",
        f"type=bind,src={repo_root},dst=/workspace-ro,readonly",
        "--env",
        "DOCKER_TLS_CERTDIR=",
        "--env",
        f"DOCKER_HOST={inner_docker_host}",
        *[
            token
            for name in (start_epoch_name, deadline_epoch_name)
            if name in os.environ
            for token in ("--env", f"{name}={os.environ[name]}")
        ],
        image_id,
        "docker-init",
        "--",
        "python3",
        "/workspace-ro/tools/test_sandbox_entrypoint.py",
        "--docker-group",
        str(host_gid),
        "--",
        *argv,
    ]
