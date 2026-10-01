"""Test-owned children that hold or contend for a SQLite Local graph lock (LOCAL10).

Each child is ``sys.executable -c`` over the product lock owner and is
synchronized only through its pipes: a holder prints ``ready`` once it holds
the lock and releases when a line (or end of file) arrives on its stdin; an
attempt prints one outcome line. The deadline on every read is a hang guard,
not a timing claim.
"""

from __future__ import annotations

import select
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

HANG_GUARD_SECONDS = 120

HOLD = """
import sys
from pathlib import Path
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock
with hold_graph_lock(Path(sys.argv[1])):
    print("ready", flush=True)
    sys.stdin.readline()
"""

# Spawns a grandchild with close_fds=False while holding the lock, so only the
# lock descriptor's own non-inheritable flag keeps the lock out of it. The
# grandchild lives until the test closes the write end of the pipe whose read
# end (argv[2]) it inherits.
HOLD_AND_SPAWN = """
import subprocess, sys
from pathlib import Path
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock
with hold_graph_lock(Path(sys.argv[1])):
    child = subprocess.Popen(
        [sys.executable, "-c", "import os, sys; os.read(int(sys.argv[1]), 1)", sys.argv[2]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=False,
    )
    print(f"ready {child.pid}", flush=True)
    sys.stdin.readline()
"""

ATTEMPT = """
import sys
from pathlib import Path
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock, probe_graph_lock
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
try:
    if sys.argv[2] == "probe":
        with probe_graph_lock(Path(sys.argv[1])) as held:
            print("probed" if held else "absent")
    else:
        with hold_graph_lock(Path(sys.argv[1])):
            print("acquired")
except LocalStoreError as error:
    print(error.code)
"""


def start_holder(
    database: Path, env: Mapping[str, str], script: str = HOLD, keep_open: int | None = None
) -> tuple[subprocess.Popen[str], str]:
    """Start a holder and return it with its ``ready`` line once it holds the lock.

    ``keep_open`` is a pipe read end handed to :data:`HOLD_AND_SPAWN`'s grandchild.
    """
    extra = () if keep_open is None else (str(keep_open),)
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(database), *extra],
        pass_fds=() if keep_open is None else (keep_open,),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env),
    )
    return process, read_line(process)


def read_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], HANG_GUARD_SECONDS)
    line = process.stdout.readline() if readable else ""
    if not line:
        process.kill()
        _, stderr = process.communicate()
        raise AssertionError(f"lock child produced no line: {stderr}")
    return line.strip()


def release_holder(process: subprocess.Popen[str]) -> int:
    """Release a holder normally and return its exit status."""
    process.communicate("release\n", timeout=HANG_GUARD_SECONDS)
    return process.returncode


def attempt(database: Path, env: Mapping[str, str], mode: str = "hold") -> str:
    """One child's lock attempt: ``acquired``, ``probed``, ``absent`` or a refusal code."""
    completed = subprocess.run(
        [sys.executable, "-c", ATTEMPT, str(database), mode],
        capture_output=True,
        text=True,
        env=dict(env),
        timeout=HANG_GUARD_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


__all__ = (
    "HOLD",
    "HOLD_AND_SPAWN",
    "attempt",
    "read_line",
    "release_holder",
    "start_holder",
)
