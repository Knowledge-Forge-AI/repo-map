"""Bound one sandbox's backing-space measurement to its outer Docker layer.

The binding is valid for the owner invocation: its token, mount and schema are
rechecked on every read, while its issuance only rejects negative or future
handoffs. Each capacity read still takes a fresh filesystem measurement. This
is cooperative invocation ownership, not hostile-code isolation. No CLI or
environment input supplies a capacity number or a measurement path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Callable

from test_sandbox_report import write_sandbox_diagnostic


GIB = 1024**3
BINDING_PATH = Path("/run/repomap-test-sandbox-capacity")
OWNER_PATH = Path("/run/repomap-test-sandbox-owner")
SCRATCH_BYTES = 8 * GIB
DOCKER_BYTES = 4 * GIB
# A checkpoint margin for consumers outside managed scratch; not suite sizing.
SCRATCH_HEADROOM_BYTES = GIB
SCHEMA = "repomap-sandbox-capacity-binding-v1"


def _outer_evidence(fields: dict[str, str | int | bool]) -> None:
    write_sandbox_diagnostic(json.dumps({
        "event": "repomap-sandbox-capacity-v1",
        "stage": "outer_overlay_backing",
        **fields,
    }, separators=(",", ":")))


def _outer_refuse(reason: str) -> RuntimeError:
    _outer_evidence({"decision": "refused", "reason": reason})
    return _refuse(reason)


def _refuse(reason: str) -> RuntimeError:
    return RuntimeError(f"sandbox_capacity_refused: {reason}")


def _closed_json(text: str) -> object:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)


def bind_backing_capacity(
    runner: Callable[..., subprocess.CompletedProcess[str]],
    container_id: str,
    token: str,
    *,
    timeout_limit: Callable[[float], float] = float,
) -> None:
    """Measure the already materialized image's layer before releasing tests."""

    def captured(command: list[str], *, input_text: str | None = None) -> str:
        try:
            result = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_limit(30),
                input=input_text,
            )
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            raise _outer_refuse("backing_measurement_unavailable") from error
        if result.returncode != 0 or len(result.stdout) > 8192:
            raise _outer_refuse("backing_measurement_unavailable")
        return result.stdout

    try:
        driver = json.loads(
            captured(["docker", "info", "--format", "{{json .Driver}}"])
        )
        docker_root = json.loads(
            captured(["docker", "info", "--format", "{{json .DockerRootDir}}"])
        )
        graph = json.loads(
            captured(
                ["docker", "inspect", container_id, "--format", "{{json .GraphDriver}}"]
            )
        )
        upper = graph["Data"]["UpperDir"]
        if (
            driver != "overlay2"
            or graph["Name"] != "overlay2"
            or not isinstance(docker_root, str)
            or not isinstance(upper, str)
        ):
            raise _outer_refuse("unsupported_backing_mapping")
        relative = Path(upper).relative_to(Path(docker_root) / "overlay2")
        if (
            not Path(docker_root).is_absolute()
            or len(relative.parts) != 2
            or relative.parts[1] != "diff"
            or any(part in {".", ".."} for part in Path(upper).parts)
        ):
            raise _outer_refuse("unsupported_backing_mapping")
        evidence = _closed_json(
            captured(
                [
                    "docker",
                    "exec",
                    container_id,
                    "python3",
                    "/workspace-ro/tools/test_sandbox_capacity.py",
                    "probe",
                ]
            )
        )
        value = validate_probe(evidence, upper=upper)
    except (ValueError, KeyError, TypeError) as error:
        raise _outer_refuse("unsupported_backing_mapping") from error
    binding = {"schema": SCHEMA, "token": token, "mount_sha256": value["mount_sha256"]}
    writer = (
        "import json,os,sys,time; value=json.load(sys.stdin); "
        "value['issued_seconds']=int(time.time()); "
        f"fd=os.open({str(BINDING_PATH)!r},os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); "
        "stream=os.fdopen(fd,'w'); json.dump(value,stream); stream.close()"
    )
    captured(
        ["docker", "exec", "-i", container_id, "python3", "-c", writer],
        input_text=json.dumps(binding),
    )


def root_mount() -> tuple[str, str]:
    try:
        with Path("/proc/self/mountinfo").open(encoding="utf-8") as stream:
            text = stream.read(1024 * 1024 + 1)
    except (OSError, UnicodeError) as error:
        raise _refuse("mount_measurement_unavailable") from error
    if len(text) > 1024 * 1024:
        raise _refuse("unsupported_backing_mapping")
    roots = [
        line
        for line in text.splitlines()
        if len(line.split()) > 6 and line.split()[4] == "/"
    ]
    if len(roots) != 1:
        raise _refuse("unsupported_backing_mapping")
    line = roots[0]
    before, separator, after = line.partition(" - ")
    fields = after.split()
    if (
        not separator
        or len(fields) != 3
        or fields[0] != "overlay"
        or "rw" not in before.split()[5].split(",")
    ):
        raise _refuse("unsupported_backing_mapping")
    upper = [
        part.removeprefix("upperdir=")
        for part in fields[2].split(",")
        if part.startswith("upperdir=")
    ]
    if len(upper) != 1 or not upper[0].startswith("/") or "\\" in upper[0]:
        raise _refuse("unsupported_backing_mapping")
    return upper[0], hashlib.sha256(line.encode()).hexdigest()


def space(path: str) -> tuple[int, int]:
    try:
        measured = os.statvfs(path)
        free = measured.f_bavail * measured.f_frsize
        total = measured.f_blocks * measured.f_frsize
    except OSError as error:
        raise _refuse("filesystem_measurement_unavailable") from error
    if (
        type(free) is not int
        or type(total) is not int
        or not 0 <= free <= total < 2**63
        or total == 0
    ):
        raise _refuse("invalid_filesystem_measurement")
    return free, total


def probe() -> dict[str, str | int]:
    upper, mount_digest = root_mount()
    free, total = space("/")
    return {
        "upper": upper,
        "mount_sha256": mount_digest,
        "free_bytes": free,
        "total_bytes": total,
        "free_percent": free * 100 // total,
    }


def validate_probe(value: object, *, upper: str) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "upper",
        "mount_sha256",
        "free_bytes",
        "total_bytes",
        "free_percent",
    }:
        raise _outer_refuse("malformed_backing_evidence")
    if (
        value["upper"] != upper
        or not isinstance(value["mount_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["mount_sha256"]) is None
    ):
        raise _outer_refuse("unbound_backing_evidence")
    free, total, percent = (
        value[key] for key in ("free_bytes", "total_bytes", "free_percent")
    )
    if (
        any(type(number) is not int for number in (free, total, percent))
        or not 0 <= free <= total < 2**63
        or total == 0
        or percent != free * 100 // total
    ):
        raise _outer_refuse("malformed_backing_evidence")
    byte_ok, percent_ok = free >= 10 * GIB, percent >= 5
    _outer_evidence({
        "free_bytes": free, "total_bytes": total, "free_percent": percent,
        "required_free_bytes": 10 * GIB, "required_free_percent": 5,
        "byte_floor_passed": byte_ok, "percentage_floor_passed": percent_ok,
        "decision": "admitted" if byte_ok and percent_ok else "refused",
    })
    if not byte_ok or not percent_ok:
        raise RuntimeError("host_admission_refused: free_disk_reserve")
    return value


def read_binding() -> dict:
    try:
        descriptor = os.open(BINDING_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise _refuse("invalid_binding_owner")
            rendered = stream.read(4097)
        if len(rendered) > 4096:
            raise _refuse("malformed_binding")
        binding = _closed_json(rendered)
        token = OWNER_PATH.read_text(encoding="utf-8").strip()
    except (OSError, ValueError, UnicodeError) as error:
        raise _refuse("missing_or_malformed_binding") from error
    if not isinstance(binding, dict) or set(binding) != {
        "schema",
        "token",
        "mount_sha256",
        "issued_seconds",
    }:
        raise _refuse("malformed_binding")
    if (
        binding["schema"] != SCHEMA
        or re.fullmatch(r"[0-9a-f]{64}", token) is None
        or binding["token"] != token
    ):
        raise _refuse("wrong_attempt_binding")
    if (
        not isinstance(binding["mount_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", binding["mount_sha256"]) is None
    ):
        raise _refuse("substituted_backing_mapping")
    issued = binding["issued_seconds"]
    if type(issued) is not int or issued < 0 or issued > int(time.time()):
        raise _refuse("stale_binding")
    try:
        current_mount = root_mount()[1]
    except (OSError, UnicodeError) as error:
        raise _refuse("mount_measurement_unavailable") from error
    if binding["mount_sha256"] != current_mount:
        raise _refuse("substituted_backing_mapping")
    return binding


def backing_space() -> tuple[int, int]:
    read_binding()
    free, total = space("/")
    return free, free * 100 // total


def validate_scratch_capacity() -> None:
    """Check current whole-filesystem pressure, independently of logical quotas."""
    free, total = space("/sandbox-scratch")
    if total != SCRATCH_BYTES:
        raise _refuse("scratch_limit_mismatch")
    if free < SCRATCH_HEADROOM_BYTES:
        raise _refuse("scratch_headroom_insufficient")
    docker_free, docker_total = space("/var/lib/docker")
    if docker_total != DOCKER_BYTES:
        raise _refuse("inner_docker_limit_mismatch")
    if docker_free == 0:
        raise RuntimeError("inner_docker_capacity_refused: exhausted")


if __name__ == "__main__":
    if sys.argv[1:] != ["probe"]:
        raise SystemExit("sandbox capacity accepts only the fixed probe")
    print(json.dumps(probe(), separators=(",", ":")))
