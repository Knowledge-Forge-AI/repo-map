"""Test-owned children that hold or contend for a SQLite Local graph lock (LOCAL10).

Each child is ``sys.executable -c`` over the product lock owner and is
synchronized only through its pipes: a holder prints ``ready`` once it holds
the lock and releases when a line (or end of file) arrives on its stdin; an
attempt prints one outcome line. The deadline on every read is a hang guard,
not a timing claim.
"""

from __future__ import annotations

import select
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from repomap_test_support.sqlite_managed_child import ManagedChild, cleanup_child, cleanup_after_failure, child_failure_detail

HANG_GUARD_SECONDS = 120

HOLD = """
import os, sys
from pathlib import Path
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock
is_abrupt = os.environ.get("REPOMAP_TEST_SQLITE_ABRUPT_SETTLEMENT") == "1"
if is_abrupt:
    coverage_armed = bool(os.environ.get("COVERAGE_PROCESS_START") or os.environ.get("COVERAGE_CHILD_MANIFEST_DIR"))
    sc = sys.modules.get("sitecustomize")
    if coverage_armed:
        if not sc or not hasattr(sc, "_settle_terminal_receipt"):
            raise RuntimeError("abrupt terminal settlement hook missing or renamed while coverage is armed")
        sc._settle_terminal_receipt()
    elif sc and hasattr(sc, "_settle_terminal_receipt"):
        sc._settle_terminal_receipt()
with hold_graph_lock(Path(sys.argv[1])):
    print("ready", flush=True)
    sys.stdin.readline()
if is_abrupt:
    sc = sys.modules.get("sitecustomize")
    if sc and hasattr(sc, "_invalidate_terminal_receipt"):
        sc._invalidate_terminal_receipt()
    raise RuntimeError("abrupt termination lock child was released instead of killed")
"""

# Spawns a grandchild with close_fds=False while holding the lock, so only the
# lock descriptor's own non-inheritable flag keeps the lock out of it. The
# grandchild lives until the test closes the write end of the pipe whose read
# end (argv[2]) it inherits.
HOLD_AND_SPAWN = """
import os, subprocess, sys
from pathlib import Path
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock
is_abrupt = os.environ.get("REPOMAP_TEST_SQLITE_ABRUPT_SETTLEMENT") == "1"
if is_abrupt:
    coverage_armed = bool(os.environ.get("COVERAGE_PROCESS_START") or os.environ.get("COVERAGE_CHILD_MANIFEST_DIR"))
    sc = sys.modules.get("sitecustomize")
    if coverage_armed:
        if not sc or not hasattr(sc, "_settle_terminal_receipt"):
            raise RuntimeError("abrupt terminal settlement hook missing or renamed while coverage is armed")
        sc._settle_terminal_receipt()
    elif sc and hasattr(sc, "_settle_terminal_receipt"):
        sc._settle_terminal_receipt()
with hold_graph_lock(Path(sys.argv[1])):
    child = subprocess.Popen(
        [sys.executable, "-c", "import os, sys; os.read(int(sys.argv[1]), 1)", sys.argv[2]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=False,
    )
    print(f"ready {child.pid}", flush=True)
    sys.stdin.readline()
if is_abrupt:
    sc = sys.modules.get("sitecustomize")
    if sc and hasattr(sc, "_invalidate_terminal_receipt"):
        sc._invalidate_terminal_receipt()
    raise RuntimeError("abrupt termination lock child was released instead of killed")
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
    database: Path,
    env: Mapping[str, str],
    script: str = HOLD,
    keep_open: int | None = None,
    *,
    abrupt: bool = False,
) -> tuple[ManagedChild, str]:
    """Start a holder and return it with its ``ready`` line once it holds the lock.

    ``keep_open`` is a pipe read end handed to :data:`HOLD_AND_SPAWN`'s grandchild.
    """
    child_env = dict(env)
    if abrupt:
        child_env["REPOMAP_TEST_SQLITE_ABRUPT_SETTLEMENT"] = "1"
    extra = () if keep_open is None else (str(keep_open),)
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(database), *extra],
        pass_fds=() if keep_open is None else (keep_open,),
        start_new_session=not abrupt,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
    )
    managed = ManagedChild(process, abrupt=abrupt, group_owned=not abrupt)
    return managed, read_line(managed)


def kill_holder(process: subprocess.Popen[str] | ManagedChild, signal_num: int = signal.SIGKILL) -> None:
    """Kill a lock holder child under an explicit abrupt-kill contract."""
    from repomap_test_support.sqlite_local_harness import kill_paused_child

    kill_paused_child(process, signal_num)


def read_line(process: subprocess.Popen[str] | ManagedChild) -> str:
    try:
        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], HANG_GUARD_SECONDS)
        line = process.stdout.readline() if readable else ""
    except Exception as read_error:
        cleanup_after_failure(process, read_error)
        raise
    if line:
        return line.strip()
    primary = AssertionError("lock child produced no line")
    cleanup_after_failure(process, primary)
    detail = child_failure_detail(process, primary)
    primary.args = ("lock child produced no line: " + detail,)
    raise primary


def release_holder(process: subprocess.Popen[str] | ManagedChild) -> int:
    """Release a holder normally and return its exit status."""
    process.communicate("release\n", timeout=HANG_GUARD_SECONDS)
    assert process.returncode is not None
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
    "cleanup_child",
    "kill_holder",
    "read_line",
    "release_holder",
    "start_holder",
)
