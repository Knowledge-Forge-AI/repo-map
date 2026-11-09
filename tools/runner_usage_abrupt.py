"""Bounded checkpoint evidence for the two exact usage A roles."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from typing import Any


def _read_probe_pid(path: Path) -> int:
    """Read one private canonical ``<pid>\\n`` witness without following links."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            details = os.fstat(fd)
            if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
                    or details.st_nlink != 1 or stat.S_IMODE(details.st_mode) != 0o600):
                raise RuntimeError("usage abrupt block witness is unsafe")
            payload = os.read(fd, 32)
            if len(payload) >= 32 or os.read(fd, 1):
                raise RuntimeError("usage abrupt block witness is oversized")
        finally:
            os.close(fd)
    except OSError as error:
        raise RuntimeError("usage abrupt block witness is invalid") from error
    if not re.fullmatch(rb"[1-9][0-9]{0,19}\n", payload):
        raise RuntimeError("usage abrupt block witness is not canonical")
    return int(payload[:-1])


def observe_usage_checkpoint(launch: Any, spec: Any, result: Any) -> None:
    """Bind the exact pre-hello witness to the native PID."""
    case = launch.declaration.launch_case
    if case == "sigkill":
        stderr = getattr(result, "stderr", "") if result is not None else ""
        if (getattr(result, "stderr_truncated", None) is not False
                or not isinstance(stderr, str) or len(stderr.encode("utf-8")) > 4096):
            raise RuntimeError("usage abrupt checkpoint stderr was truncated")
        lines = [line for line in str(stderr).splitlines()
                 if line.startswith("REPOMAP_ABRUPT_CHECKPOINT ")]
        expected = f"REPOMAP_ABRUPT_CHECKPOINT pre_hello {launch.pid}"
        if lines != [expected]:
            raise RuntimeError("usage abrupt pre_hello checkpoint mismatch")
        launch.observed_checkpoint("pre_hello", launch.pid)
        return
    if case == "block":
        argv = tuple(spec.argv)
        try:
            probe = Path(argv[argv.index("--probe-path") + 1])
        except (ValueError, IndexError) as error:
            raise RuntimeError("usage abrupt block probe is missing") from error
        launch.observed_checkpoint("pre_hello", _read_probe_pid(probe))
        return
    raise RuntimeError("usage abrupt launch case is not closed")


__all__ = ("observe_usage_checkpoint",)
