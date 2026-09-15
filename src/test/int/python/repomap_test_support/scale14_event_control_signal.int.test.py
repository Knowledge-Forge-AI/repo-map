from __future__ import annotations

import select
import signal
import subprocess
import sys


_BLOCKER_PROGRAM = """
from threading import Event

try:
    print("blocker_entered", flush=True)
    try:
        Event().wait(30.0)
    except KeyboardInterrupt:
        print("keyboard_interrupt", flush=True)
        raise
    finally:
        print("finally", flush=True)
except KeyboardInterrupt:
    print("outer_unwind", flush=True)
    raise
"""


def test_event_wait_direct_sigint_runs_python_unwind() -> None:
    process = subprocess.Popen(
        (sys.executable, "-c", _BLOCKER_PROGRAM),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdout is not None
    try:
        ready, _, _ = select.select([process.stdout], [], [], 5.0)
        assert ready, "child did not announce blocker entry in time"
        entered = process.stdout.readline().strip()
        assert entered == "blocker_entered"
        process.send_signal(signal.SIGINT)
        remainder, _ = process.communicate(timeout=5.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)

    assert process.returncode != 0
    assert remainder.splitlines() == [
        "keyboard_interrupt",
        "finally",
        "outer_unwind",
    ]
