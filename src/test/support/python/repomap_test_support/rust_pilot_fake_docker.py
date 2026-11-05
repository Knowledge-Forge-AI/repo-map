"""Exact-command fake boundary for the T1 controller-to-semantics tests.

This is deliberately a test-support boundary, not a Docker or native parser
replacement.  It accepts only the reviewed argument vectors, runs the real
stdlib guest writer/readback/probe/helper text against a temporary tree, and
labels the kernel/Docker observations it synthesizes for T1.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult, run_bounded
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    LABEL_RUN,
    LABEL_SEQ,
    MEMORY_BYTES,
    PARSER_USER,
    PYTHON,
    PIDS_LIMIT,
    RUNTIME_ROOT,
    RUNTIME_TMPFS,
    SCRATCH,
    SCRATCH_TMPFS,
    SETUP_USER,
    Runner,
    create_arguments,
    exec_arguments,
)
from common_lore_index.extractors.rust_pilot.readback import decode_readback
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import guest_text

IMAGE = "sha256:" + "a" * 64
_PYTHON_FLAGS = ("-I", "-S", "-B")
_MOUNTS = (
    "1 0 0:1 / / ro,relatime - ext4 /dev/synthetic ro",
    f"2 1 0:2 / {RUNTIME_ROOT} rw,nosuid,nodev - tmpfs tmpfs rw,nosuid,nodev",
    f"3 1 0:3 / {SCRATCH} rw,noexec,nosuid,nodev - tmpfs tmpfs rw,noexec,nosuid,nodev",
)
_STATUS = (
    "Uid:\t10001\t10001\t10001\t10001",
    "Gid:\t10001\t10001\t10001\t10001",
    "CapInh:\t0000000000000000",
    "CapPrm:\t0000000000000000",
    "CapEff:\t0000000000000000",
    "CapBnd:\t0000000000000000",
    "CapAmb:\t0000000000000000",
    "NoNewPrivs:\t1",
    "Seccomp:\t2",
)


def _ok(stdout: bytes = b"", returncode: int = 0) -> ExecResult:
    return ExecResult(returncode, stdout, False, 0, "0" * 64, False, False, True, 0.0)


@dataclass
class _Container:
    root: Path
    scratch: Path
    run_id: str
    seq: int
    image_id: str
    arch: str
    removed: bool = False


class FakeDockerBridge:
    """A literal command dispatcher with real guest subprocesses underneath."""

    def __init__(self, root: Path, *,
                 guest_executor: Callable[..., ExecResult] | None = None) -> None:
        self.root = root
        self.docker_cli = "/usr/bin/docker"
        self.guest_executor = guest_executor
        self.root.mkdir(parents=True)
        self.calls: list[tuple[str, ...]] = []
        self.journal = self.calls
        self._containers: dict[str, _Container] = {}
        self._next_id = 1

    def __call__(
        self, argv: Sequence[str], stdin: bytes, stdout_limit: int, deadline: float,
        on_deadline: Callable[[float], None] | None, /, *,
        hard_end: float | None = None,
    ) -> ExecResult:
        if not argv or argv[0] != self.docker_cli:
            raise AssertionError(f"unexpected fake runner argv: {argv!r}")
        return self.run(
            argv[1:], stdin=stdin, stdout_limit=stdout_limit,
            deadline=deadline, hard_end=hard_end,
        )

    def as_runner(self) -> Runner:
        return self

    def _record(self, args: Sequence[str]) -> list[str]:
        vector = list(args)
        self.calls.append(tuple(vector))
        return vector

    def run(
        self,
        args: Sequence[str],
        *,
        stdin: bytes = b"",
        stdout_limit: int = 1_048_576,
        deadline: float = 20.0,
        kill_id: str | None = None,
        hard_end: float | None = None,
    ) -> ExecResult:
        """Dispatch only vectors emitted by DockerBoundary's closed API."""

        vector = self._record(args)
        if vector == ["version", "--format", "{{json .Server}}"]:
            return _ok(b'{"Os":"linux","Arch":"arm64"}')
        if vector == ["image", "inspect", IMAGE]:
            return _ok(json.dumps([{"Id": IMAGE, "Os": "linux", "Architecture": "arm64",
                                    "Config": {}}]).encode("ascii"))
        if vector[:1] == ["create"]:
            return self._create(vector)
        if vector[:1] == ["start"] and len(vector) == 2:
            self._require(vector[1])
            return _ok()
        if vector[:2] == ["container", "inspect"] and len(vector) == 3:
            return _ok(json.dumps([self._inspect(vector[2])], sort_keys=True).encode("ascii"))
        if vector[:1] == ["exec"]:
            return self._exec(vector, stdin, stdout_limit, deadline, hard_end)
        if vector[:3] == ["kill", "--signal", "KILL"] and len(vector) == 4:
            self._require(vector[3])
            return _ok()
        if vector[:3] == ["rm", "-f", "-v"] and len(vector) == 4:
            item = self._require(vector[3])
            if not item.removed:
                base = item.root.parent
                assert base.parent == self.root and base.name == vector[3] and not base.is_symlink()
                for path in (item.root, *item.root.rglob("*")):
                    if path.is_dir() and not path.is_symlink():
                        path.chmod(0o755)
                shutil.rmtree(base)
            item.removed = True
            return _ok(vector[3].encode("ascii") + b"\n")
        if (len(vector) == 7 and vector[:5] == ["container", "ls", "-a", "--no-trunc", "--filter"]
                and vector[5].startswith("id=") and vector[6] == "-q"):
            return self._absent(vector[5])
        if vector == ["image", "ls", "-q", "--no-trunc"]:
            return _ok(b"")
        if vector == ["volume", "ls", "-q"]:
            return _ok(b"")
        if (len(vector) == 7 and vector[:6] == ["container", "ls", "-a", "-q", "--no-trunc", "--filter"]
                and vector[6].startswith("label=")):
            run_id = vector[6].split("=", 2)[2]
            listed = [cid for cid, item in self._containers.items()
                      if item.run_id == run_id and not item.removed]
            return _ok(("\n".join(listed) + ("\n" if listed else "")).encode("ascii"))
        raise AssertionError(f"unexpected fake Docker vector: {vector!r}")

    def _create(self, vector: list[str]) -> ExecResult:
        if len(vector) < 2:
            raise AssertionError("short create vector")
        labels = [vector[index + 1] for index, value in enumerate(vector[:-1]) if value == "--label"]
        if len(labels) != 2 or "--platform" not in vector or "--entrypoint" not in vector:
            raise AssertionError(f"malformed create vector: {vector!r}")
        run_id = labels[0].split("=", 1)[1]
        seq = int(labels[1].split("=", 1)[1])
        arch = vector[vector.index("--platform") + 1].removeprefix("linux/")
        image_id = vector[vector.index("--entrypoint") + 2]
        if vector != create_arguments(run_id=run_id, seq=seq, docker_arch=arch, image_id=image_id):
            raise AssertionError("create vector drifted from the closed Docker contract")
        cid = f"{self._next_id:064x}"
        self._next_id += 1
        base = self.root / cid
        runtime_root, scratch = base / "runtime", base / "scratch"
        base.mkdir()
        runtime_root.mkdir()
        scratch.mkdir(mode=0o700)
        self._containers[cid] = _Container(runtime_root, scratch, run_id, seq, image_id, arch)
        return _ok(cid.encode("ascii") + b"\n")

    def _require(self, cid: str) -> _Container:
        if cid not in self._containers:
            raise AssertionError(f"unknown fake container: {cid}")
        return self._containers[cid]

    def _absent(self, selector: str) -> ExecResult:
        if not selector.startswith("id="):
            raise AssertionError(f"unexpected absence selector: {selector!r}")
        item = self._require(selector[3:])
        return _ok(b"" if item.removed else (selector[3:] + "\n").encode("ascii"))

    def _inspect(self, cid: str) -> dict[str, object]:
        item = self._require(cid)
        return {
            "Id": cid,
            "Image": item.image_id,
            "Name": f"/repomap-rust-pilot-{item.run_id[4:16]}-{item.seq:06d}",
            "State": {"Running": True, "OOMKilled": False},
            "Mounts": [],
            "HostConfig": {
                "ReadonlyRootfs": True, "NetworkMode": "none", "CapDrop": ["ALL"],
                "CapAdd": [], "SecurityOpt": ["no-new-privileges=true"], "Privileged": False,
                "PidsLimit": PIDS_LIMIT, "Memory": MEMORY_BYTES, "MemorySwap": MEMORY_BYTES,
                "AutoRemove": True, "Tmpfs": {RUNTIME_ROOT: RUNTIME_TMPFS, SCRATCH: SCRATCH_TMPFS},
                "Binds": [], "Mounts": [], "VolumesFrom": [], "Devices": [], "PidMode": "",
                "IpcMode": "none", "UTSMode": "",
            },
            "Config": {
                "User": PARSER_USER, "Entrypoint": [PYTHON],
                "Volumes": {}, "Labels": {LABEL_RUN: item.run_id, LABEL_SEQ: str(item.seq)},
            },
        }

    def _exec(
        self,
        vector: list[str],
        stdin: bytes,
        stdout_limit: int,
        deadline: float,
        hard_end: float | None,
    ) -> ExecResult:
        interactive = len(vector) > 1 and vector[1] == "-i"
        index = 2 if interactive else 1
        if vector[index] != "-u":
            raise AssertionError(f"missing exact exec user: {vector!r}")
        user = vector[index + 1]
        index += 2
        workdir = None
        if index < len(vector) and vector[index] == "-w":
            workdir = vector[index + 1]
            index += 2
        cid = vector[index]
        if vector[index + 1] != PYTHON:
            raise AssertionError(f"unexpected exec interpreter: {vector!r}")
        tail = tuple(vector[index + 2:])
        if vector != exec_arguments(cid, user=user, tail=tail, interactive=interactive, workdir=workdir):
            raise AssertionError("exec vector drifted from the closed Docker contract")
        return self._guest(self._require(cid), user, workdir, tail, stdin, stdout_limit, deadline, hard_end)

    def _guest(
        self,
        item: _Container,
        user: str,
        workdir: str | None,
        tail: tuple[str, ...],
        stdin: bytes,
        stdout_limit: int,
        deadline: float,
        hard_end: float | None,
    ) -> ExecResult:
        if tail[:4] == _PYTHON_FLAGS + ("-c",):
            source = tail[4]
            if user == SETUP_USER and workdir == "/":
                if self.guest_executor is not None:
                    return self.guest_executor("setup_writer", root=item.root, scratch=item.scratch,
                                               stdin=stdin)
                source = guest_text("setup_writer.py", item.root).decode("ascii")
                return run_bounded([sys.executable, *_PYTHON_FLAGS, "-c", source], stdin=stdin,
                                   stdout_limit=stdout_limit, deadline=deadline, hard_end=hard_end)
            if workdir is None and "Install readback" in source:
                if self.guest_executor is not None:
                    result = self.guest_executor("install_readback", root=item.root, scratch=item.scratch)
                    return _normalize_readback(result, item.root)
                source = guest_text("install_readback.py", item.root, item.scratch).decode("ascii")
                result = run_bounded([sys.executable, *_PYTHON_FLAGS, "-c", source],
                                     stdout_limit=stdout_limit, deadline=deadline, hard_end=hard_end)
                return _normalize_readback(result, item.root)
            if workdir is None and "Run-level runtime probe" in source:
                source = guest_text("runtime_probe.py", item.root).decode("ascii")
                guest_args = list(tail[5:])
                if self.guest_executor is not None:
                    result = self.guest_executor("runtime_probe", root=item.root, scratch=item.scratch,
                                                 argv=guest_args)
                    return result if "--cost-only" in guest_args else _normalize_probe(result)
                result = run_bounded([sys.executable, *_PYTHON_FLAGS, "-c", source, *guest_args],
                                     stdout_limit=stdout_limit, deadline=deadline, hard_end=hard_end)
                return result if "--cost-only" in guest_args else _normalize_probe(result)
        if workdir == SCRATCH and tail[:5] == _PYTHON_FLAGS + ("-X", "utf8"):
            if self.guest_executor is not None:
                return self.guest_executor("parse_helper", root=item.root, scratch=item.scratch, stdin=stdin)
            helper = (item.root / "helper" / "parse_helper.py").read_text(encoding="ascii")
            helper = helper.replace('RUNTIME_ROOT = "/opt/repomap-rust"',
                                    f"RUNTIME_ROOT = {str(item.root)!r}")
            return run_bounded([sys.executable, *_PYTHON_FLAGS, "-X", "utf8", "-c", helper],
                               stdin=stdin, stdout_limit=stdout_limit, deadline=deadline, hard_end=hard_end)
        raise AssertionError(f"unexpected guest exec shape: {tail!r}")


def _normalize_readback(result: ExecResult, runtime_root: Path) -> ExecResult:
    if not result.clean:
        return result
    decoded = decode_readback(result.stdout)
    output = bytearray()
    root = str(runtime_root)
    for entry in decoded.entries:
        path = entry.path
        if path == root:
            path = RUNTIME_ROOT
        elif path.startswith(root + "/"):
            path = RUNTIME_ROOT + path[len(root):]
        header = {"t": "entry", "path": path, "type": entry.kind, "mode": entry.mode,
                  "uid": 0, "gid": 0, "nlink": entry.nlink, "size": 0 if entry.data is None else len(entry.data)}
        output.extend(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n")
        if entry.data is not None:
            output.extend(entry.data)
    for value in (
        {"t": "mounts", "lines": list(_MOUNTS)},
        {"t": "status", "lines": list(_STATUS)},
        {"t": "scratch", "names": []},
        {"t": "ifaces", "names": ["lo"]},
        {"t": "end", "entries": len(decoded.entries)},
    ):
        output.extend(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n")
    return ExecResult(result.returncode, bytes(output), result.stdout_overflow, result.stderr_bytes,
                      result.stderr_sha256, result.stderr_overflow, result.timed_out, result.settled,
                      result.elapsed, result.io_failed, result.input_complete, result.callback_failed)


def _normalize_probe(result: ExecResult) -> ExecResult:
    if not result.clean:
        return result
    facts = json.loads(result.stdout)
    facts.update({
        "executable": PYTHON, "version": "3.13.12", "cache_tag": "cpython-313",
        "soabi": "cpython-313-aarch64-linux-gnu", "abiflags": "", "machine": "aarch64",
        "libc": ["glibc", "2.31"], "kernel": "synthetic-t1-kernel",
        "module_files": [f"{RUNTIME_ROOT}/site/tree_sitter/__init__.py",
                         f"{RUNTIME_ROOT}/site/tree_sitter_rust/__init__.py"],
    })
    data = (json.dumps(facts, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    return ExecResult(result.returncode, data, result.stdout_overflow, result.stderr_bytes,
                      result.stderr_sha256, result.stderr_overflow, result.timed_out, result.settled,
                      result.elapsed, result.io_failed, result.input_complete, result.callback_failed)


__all__ = ("FakeDockerBridge", "IMAGE")
