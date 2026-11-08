"""Bounded kill-first cleanup for opt-in usage-collecting launches (ADR 0173 B1).

Only an owned, unticketed, usage-collecting portable launch reaches this
handler; the default path and coordinator launches keep incumbent supervision.
Every step shares one monotonic deadline of twice the termination grace:

1. ``kill_tree`` immediately, with no graceful phase, unless the boundary is
   already closed or the reaped leader's group is provably empty (its id may
   then be reused, so it is never signalled again);
2. wait on the reaper for at most the termination grace;
3. ``cleanup`` with zero termination grace and kill timeouts of half the
   remaining deadline, because incumbent cleanup can wait twice that long;
4. close stdin, stdout and stderr, then join the readers with what remains.

An ordinary ``Exception`` from any step becomes a note on the original
exception, which the caller re-raises unchanged. A second ``BaseException`` is
not caught: it propagates with the original as ``__context__`` and leaves the
rest of the cleanup unproved. No hard operating-system wall-time bound is
claimed: a reader blocked by a process outside the group can outlive it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import subprocess
import threading
import time
from typing import Any


def interrupt_cleanup(
    process: Any,
    readers: Sequence[threading.Thread],
    termination_grace: float,
    original: BaseException,
    *,
    _monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Run the bounded kill-first cleanup; never replaces ``original``."""

    deadline = _monotonic() + 2 * termination_grace

    def remaining() -> float:
        return max(0.0, deadline - _monotonic())

    def attempt(step: Callable[[], object]) -> None:
        try:
            step()
        except Exception as failure:
            original.add_note(
                f"usage worker interrupt cleanup failure: {type(failure).__name__}"
            )

    def bounded_wait() -> None:
        try:
            process.wait(timeout=min(termination_grace, remaining()))
        except subprocess.TimeoutExpired:
            pass  # cleanup below escalates within the shared deadline

    def kill_first() -> None:
        # Once the owning reaper holds the leader's status and the group is
        # empty, the group id may be reused: never signal it again (the same
        # probe-before-kill rule as ``ManagedProcess.cleanup``).
        if process.returncode is not None and not process.tree_exists():
            return
        process.kill_tree()

    # A closed boundary means incumbent cleanup already escalated and released
    # it; signalling after that would act outside the owned boundary.
    if not process.closed:
        attempt(kill_first)
        attempt(bounded_wait)
        attempt(lambda: process.cleanup(0.0, remaining() / 2))
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            attempt(stream.close)
    for reader in readers:
        def join(item: threading.Thread = reader) -> None:
            item.join(timeout=remaining())

        attempt(join)


__all__ = ("interrupt_cleanup",)
