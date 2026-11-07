"""Parent-held Docker CLI boundary: exact vectors, inspection, settlement (5.1, 5.2, 8).

Docker access is a declared parent host privilege. Every client call goes
through one closed command journal with its own timeout; build, pull,
commit, prune and volume creation are not expressible. Containers are
addressed by their full 64-hex ID after creation. Removal exits are advisory;
only a successful exact-ID absence query proves cleanup. Foreign containers
are never removed and nothing is pruned.
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult, run_bounded

CLIENT_TIMEOUT = 20.0
SETTLEMENT_BUDGET = 15.0
ABSENCE_POLL = 0.25
CLIENT_STDOUT_LIMIT = 1_048_576
PYTHON = "/usr/local/bin/python3.13"
RUNTIME_ROOT = "/opt/repomap-rust"
SCRATCH = "/scratch"
PARSER_USER = "10001:10001"
SETUP_USER = "0:0"
RUNTIME_TMPFS = "rw,exec,nosuid,nodev,size=16m,mode=0755,uid=0,gid=0"
SCRATCH_TMPFS = "rw,noexec,nosuid,nodev,size=4m,mode=0700,uid=10001,gid=10001"
LABEL_RUN = "org.repomap.rust-pilot.run"
LABEL_SEQ = "org.repomap.rust-pilot.seq"
SLEEPER = "import time; time.sleep(75)"
MEMORY_BYTES = 512 * 1_048_576
PIDS_LIMIT = 32
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
RUN_ID = re.compile(r"rp1\.[0-9a-f]{16}")
ALLOWED_VERBS = (
    ("version",), ("image", "inspect"), ("create",), ("start",), ("container", "inspect"),
    ("exec",), ("kill",), ("rm",), ("container", "ls"), ("image", "ls"), ("volume", "ls"),
)

class Runner(Protocol):
    def __call__(self, argv: Sequence[str], stdin: bytes, stdout_limit: int, deadline: float,
                 on_deadline: Callable[[float], None] | None, /, *,
                 hard_end: float | None = None) -> ExecResult: ...


class DockerRefused(ContractError):
    """Categorical boundary refusal; the message is the closed code only."""


def default_runner(argv: Sequence[str], stdin: bytes, stdout_limit: int, deadline: float,
                   on_deadline: Callable[[float], None] | None, *,
                   hard_end: float | None = None) -> ExecResult:
    return run_bounded(argv, stdin=stdin, stdout_limit=stdout_limit, deadline=deadline,
                       on_deadline=on_deadline, settle=SETTLEMENT_BUDGET, hard_end=hard_end)


def container_name(run_id: str, seq: int) -> str:
    if RUN_ID.fullmatch(run_id) is None or type(seq) is not int or not 0 <= seq <= 999_999:
        raise DockerRefused("invalid_identity")
    return f"repomap-rust-pilot-{run_id[4:16]}-{seq:06d}"


def create_arguments(*, run_id: str, seq: int, docker_arch: str, image_id: str) -> list[str]:
    """Return the exact ``docker create`` argument vector of spec 5.2."""

    if IMAGE_ID.fullmatch(image_id) is None or docker_arch not in ("arm64", "amd64"):
        raise DockerRefused("invalid_identity")
    return [
        "create", "--rm", "--name", container_name(run_id, seq),
        "--label", f"{LABEL_RUN}={run_id}", "--label", f"{LABEL_SEQ}={seq}",
        "--platform", f"linux/{docker_arch}", "--pull", "never",
        "--network", "none", "--ipc", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
        "--pids-limit", str(PIDS_LIMIT), "--memory", "512m", "--memory-swap", "512m",
        "--ulimit", "core=0", "--ulimit", "nofile=64:64",
        "--user", PARSER_USER, "--workdir", SCRATCH, "--env", "LC_ALL=C.UTF-8",
        "--log-driver", "none", "--stop-timeout", "1",
        "--tmpfs", f"{RUNTIME_ROOT}:{RUNTIME_TMPFS}", "--tmpfs", f"{SCRATCH}:{SCRATCH_TMPFS}",
        "--entrypoint", PYTHON, image_id, "-I", "-S", "-B", "-c", SLEEPER,
    ]


def exec_arguments(container_id: str, *, user: str, tail: Sequence[str], interactive: bool,
                   workdir: str | None) -> list[str]:
    if CONTAINER_ID.fullmatch(container_id) is None or user not in (PARSER_USER, SETUP_USER):
        raise DockerRefused("invalid_identity")
    args = ["exec"] + (["-i"] if interactive else []) + ["-u", user]
    if workdir is not None:
        args += ["-w", workdir]
    return args + [container_id, PYTHON, *tail]


def _json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DockerRefused("inspect_unparseable") from None


def _single(data: bytes) -> dict[str, Any]:
    value = _json(data)
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise DockerRefused("inspect_unparseable")
    return value[0]


def _empty(value: object) -> bool:
    return value is None or value == [] or value == {} or value == ""


@dataclass(frozen=True)
class ServerFacts:
    os: str
    arch: str


@dataclass(frozen=True)
class ResidueSnapshot:
    images: frozenset[str]
    volumes: frozenset[str]
    labelled: frozenset[str]


def check_container_config(obj: dict[str, Any], *, container_id: str, image_id: str, run_id: str,
                           seq: int) -> None:
    """Refuse unless host-side inspection matches every spec 5.2 setting."""

    host = obj.get("HostConfig") or {}
    config = obj.get("Config") or {}
    labels = config.get("Labels") or {}
    pilot_labels = {key: value for key, value in labels.items() if key.startswith("org.repomap.rust-pilot.")}
    checks = (
        obj.get("Id") == container_id, obj.get("Image") == image_id,
        obj.get("Name") == "/" + container_name(run_id, seq),
        (obj.get("State") or {}).get("Running") is True,
        host.get("ReadonlyRootfs") is True, host.get("NetworkMode") == "none",
        host.get("CapDrop") == ["ALL"], _empty(host.get("CapAdd")),
        host.get("SecurityOpt") == ["no-new-privileges=true"], host.get("Privileged") is False,
        host.get("PidsLimit") == PIDS_LIMIT, host.get("Memory") == MEMORY_BYTES,
        host.get("MemorySwap") == MEMORY_BYTES, host.get("AutoRemove") is True,
        host.get("Tmpfs") == {RUNTIME_ROOT: RUNTIME_TMPFS, SCRATCH: SCRATCH_TMPFS},
        _empty(host.get("Binds")), _empty(host.get("Mounts")), _empty(host.get("VolumesFrom")),
        _empty(host.get("Devices")), _empty(host.get("PidMode")), host.get("IpcMode") == "none",
        _empty(host.get("UTSMode")), obj.get("Mounts") == [],
        config.get("User") == PARSER_USER, config.get("Entrypoint") == [PYTHON],
        pilot_labels == {LABEL_RUN: run_id, LABEL_SEQ: str(seq)},
    )
    if not all(checks):
        raise DockerRefused("container_config_mismatch")


class DockerBoundary:
    """One run's Docker client, journal and exact-ID operations."""

    def __init__(self, docker_cli: str, *, runner: Runner | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if (type(docker_cli) is not str or not os.path.isabs(docker_cli) or "\x00" in docker_cli):
            raise DockerRefused("invalid_client_path")
        self.docker_cli = docker_cli
        self._runner = runner or default_runner
        self._clock = clock
        self._sleep = sleep
        self._work_deadline: float | None = None
        self.journal: list[tuple[str, ...]] = []
        self._settlement_ends: dict[str, float] = {}
        self._uncertain_created: dict[str, tuple[str, int, str]] = {}

    def run(self, args: Sequence[str], *, stdin: bytes = b"", stdout_limit: int = CLIENT_STDOUT_LIMIT,
            deadline: float = CLIENT_TIMEOUT, kill_id: str | None = None,
            hard_end: float | None = None) -> ExecResult:
        verb = tuple(args[:2]) if args and args[0] in ("image", "container", "volume") else tuple(args[:1])
        if verb not in ALLOWED_VERBS:
            raise DockerRefused("command_refused")
        if verb == ("create",) and not _exact_create(args):
            raise DockerRefused("command_refused")
        if hard_end is not None:
            deadline = min(deadline, hard_end - self._clock())
            if deadline <= 0:
                raise DockerRefused("client_deadline_exhausted")
        self.journal.append(tuple(args))
        on_deadline = None if kill_id is None else functools.partial(self._bound_kill, kill_id)
        return self._runner([self.docker_cli, *args], stdin, stdout_limit, deadline, on_deadline,
                            hard_end=hard_end)

    def begin_settlement(self, container_id: str, *, budget: float = SETTLEMENT_BUDGET) -> float:
        if not 0 < budget <= SETTLEMENT_BUDGET:
            raise DockerRefused("invalid_settlement_budget")
        self._id(container_id)
        end = min(self._settlement_ends.get(container_id, float("inf")), self._clock() + budget)
        self._settlement_ends[container_id] = end
        return end

    def _bound_kill(self, container_id: str, client_cleanup_end: float) -> None:
        end = self.begin_settlement(container_id)
        self.kill(container_id, hard_end=min(end, client_cleanup_end))

    def limit_work_deadline(self, deadline: float | None) -> None:
        """Only shorten a numeric work window; settlement keeps its own cap."""

        if deadline is None:
            return
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise DockerRefused("invalid_work_deadline")
        self._work_deadline = deadline if self._work_deadline is None else min(self._work_deadline, deadline)

    def require_work_deadline(self) -> None:
        if self._work_deadline is not None and self._clock() >= self._work_deadline:
            raise DockerRefused("internal_deadline_exceeded")

    def server(self) -> ServerFacts:
        self.require_work_deadline()
        result = self.run(["version", "--format", "{{json .Server}}"])
        if not result.clean:
            raise DockerRefused("server_unavailable")
        value = _json(result.stdout)
        if type(value) is not dict or type(value.get("Os")) is not str or type(value.get("Arch")) is not str:
            raise DockerRefused("server_unavailable")
        return ServerFacts(value["Os"], value["Arch"])

    def check_image(self, image_id: str, docker_arch: str) -> None:
        self.require_work_deadline()
        if IMAGE_ID.fullmatch(image_id) is None:
            raise DockerRefused("invalid_identity")
        result = self.run(["image", "inspect", image_id])
        if not result.clean:
            raise DockerRefused("image_unavailable")
        obj = _single(result.stdout)
        config = obj.get("Config") or {}
        if (obj.get("Id") != image_id or obj.get("Os") != "linux"
                or obj.get("Architecture") != docker_arch or not _empty(config.get("Volumes"))):
            raise DockerRefused("image_mismatch")

    def create(self, *, run_id: str, seq: int, docker_arch: str, image_id: str,
               hard_end: float | None = None, owned: list[str] | None = None) -> str:
        self.require_work_deadline()
        result = self.run(create_arguments(run_id=run_id, seq=seq, docker_arch=docker_arch, image_id=image_id),
                          hard_end=hard_end)
        container_id = result.stdout.decode("ascii", "replace").strip()
        if CONTAINER_ID.fullmatch(container_id) is None:
            raise DockerRefused("create_failed")
        # Preserve the exact returned identity even when client IO failed. It
        # must still pass ownership inspection before any destructive cleanup.
        if owned is not None:
            owned.append(container_id)
        if not result.clean:
            self._uncertain_created[container_id] = (run_id, seq, image_id)
            raise DockerRefused("create_failed")
        return container_id

    def start(self, container_id: str, *, hard_end: float | None = None) -> None:
        self.require_work_deadline()
        if not self.run(["start", self._id(container_id)], hard_end=hard_end).clean:
            raise DockerRefused("start_failed")

    def inspect(self, container_id: str, *, hard_end: float | None = None) -> dict[str, Any]:
        result = self.run(["container", "inspect", self._id(container_id)], hard_end=hard_end)
        if not result.clean:
            raise DockerRefused("inspect_failed")
        return _single(result.stdout)

    def run_guest(self, container_id: str, *, user: str, tail: Sequence[str], stdin: bytes | None,
             stdout_limit: int, deadline: float, workdir: str | None = None,
             hard_end: float | None = None) -> ExecResult:
        self.require_work_deadline()
        args = exec_arguments(container_id, user=user, tail=tail, interactive=stdin is not None,
                              workdir=workdir)
        return self.run(args, stdin=stdin or b"", stdout_limit=stdout_limit, deadline=deadline,
                        kill_id=container_id, hard_end=hard_end)

    def observe_cost(self, container_id: str, runtime_probe_source: str, *, hard_end: float) -> ExecResult:
        """Fixed cost-only settlement action; never a setup or target parse."""

        if (type(hard_end) not in (int, float) or not math.isfinite(hard_end)
                or self._settlement_ends.get(container_id) != hard_end):
            raise DockerRefused("invalid_settlement_end")
        args = exec_arguments(container_id, user=PARSER_USER,
                              tail=("-I", "-S", "-B", "-c", runtime_probe_source, "--cost-only"),
                              interactive=False, workdir=None)
        return self.run(args, stdout_limit=4096, deadline=5, kill_id=container_id, hard_end=hard_end)

    def kill(self, container_id: str, *, hard_end: float | None = None) -> None:
        self.run(["kill", "--signal", "KILL", self._id(container_id)], hard_end=hard_end)

    def absent(self, container_id: str, *, hard_end: float | None = None) -> bool | None:
        """True only for a successful empty exact-ID query; None when unobservable."""

        result = self.run(["container", "ls", "-a", "--no-trunc", "--filter",
                           f"id={self._id(container_id)}", "-q"], hard_end=hard_end)
        if not result.clean:
            return None
        listed = result.stdout.decode("ascii", "replace").split()
        if not listed:
            return True
        return False if listed == [container_id] else None

    def settle(self, container_id: str, *, budget: float = SETTLEMENT_BUDGET) -> bool:
        """Kill, remove and poll exact-ID absence; return True only on proven absence."""

        end = self.begin_settlement(container_id, budget=budget)
        if container_id in self._uncertain_created:
            try:
                if self.absent(container_id, hard_end=end) is True:
                    return True
                doc = self.inspect(container_id, hard_end=end)
                run_id, seq, image_id = self._uncertain_created[container_id]
                labels = (doc.get("Config") or {}).get("Labels") or {}
                if (doc.get("Id") != container_id or doc.get("Image") != image_id
                        or doc.get("Name") != "/" + container_name(run_id, seq)
                        or labels.get(LABEL_RUN) != run_id or labels.get(LABEL_SEQ) != str(seq)):
                    return False
            except ContractError:
                return False
            del self._uncertain_created[container_id]
        for args in (["kill", "--signal", "KILL", self._id(container_id)],
                     ["rm", "-f", "-v", self._id(container_id)]):
            try:
                self.run(args, hard_end=end)
            except ContractError:
                pass
        while self._clock() < end:
            try:
                absent = self.absent(container_id, hard_end=end)
            except ContractError:
                absent = None
            if absent is True and self._clock() <= end:
                return True
            if self._clock() + ABSENCE_POLL > end:
                return False
            self._sleep(ABSENCE_POLL)
        return False

    def snapshot(self, run_id: str) -> ResidueSnapshot:
        if RUN_ID.fullmatch(run_id) is None:
            raise DockerRefused("invalid_identity")
        images = self.run(["image", "ls", "-q", "--no-trunc"])
        volumes = self.run(["volume", "ls", "-q"])
        labelled = self.run(["container", "ls", "-a", "-q", "--no-trunc", "--filter", f"label={LABEL_RUN}={run_id}"])
        if any(not item.clean for item in (images, volumes, labelled)):
            raise DockerRefused("snapshot_unavailable")
        return ResidueSnapshot(*(frozenset(item.stdout.decode("ascii", "replace").split())
                                 for item in (images, volumes, labelled)))

    @staticmethod
    def _id(container_id: str) -> str:
        if CONTAINER_ID.fullmatch(container_id) is None:
            raise DockerRefused("invalid_identity")
        return container_id


def _exact_create(args: Sequence[str]) -> bool:
    try:
        run_id = args[args.index("--label") + 1].removeprefix(LABEL_RUN + "=")
        seq = int(args[args.index("--label") + 3].removeprefix(LABEL_SEQ + "="))
        arch = args[args.index("--platform") + 1].removeprefix("linux/")
        return list(args) == create_arguments(run_id=run_id, seq=seq, docker_arch=arch, image_id=args[-6])
    except (ValueError, IndexError, ContractError):
        return False


def journal_violations(journal: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    """Return any journaled command outside the closed vocabulary (expected: none)."""

    bad = []
    for args in journal:
        verb = tuple(args[:2]) if args and args[0] in ("image", "container", "volume") else tuple(args[:1])
        if verb not in ALLOWED_VERBS or (verb == ("create",) and not _exact_create(args)):
            bad.append(" ".join(args[:2]))
    return tuple(bad)
