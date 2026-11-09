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
from common_lore_index.coordinator._usage_observation import (
    UsageSettlement,
    settlement_for_process,
    usage_streams_closed,
)


def interrupt_cleanup(
    process: Any,
    readers: Sequence[threading.Thread],
    termination_grace: float,
    original: BaseException,
    *,
    _monotonic: Callable[[], float] = time.monotonic,
) -> UsageSettlement | None:
    """Run the bounded kill-first cleanup; never replaces ``original``."""

    deadline = _monotonic() + 2 * termination_grace

    def remaining() -> float:
        return max(0.0, deadline - _monotonic())

    def attempt(step: Callable[[], object]) -> bool:
        try:
            step()
            return True
        except Exception as failure:
            original.add_note(
                f"usage worker interrupt cleanup failure: {type(failure).__name__}"
            )
            return False

    waited = False

    def bounded_wait() -> bool:
        nonlocal waited
        try:
            status = process.wait(timeout=min(termination_grace, remaining()))
            waited = type(status) is int
            return waited
        except subprocess.TimeoutExpired:
            pass  # cleanup below escalates within the shared deadline
            return False

    def kill_first() -> None:
        # Once the owning reaper holds the leader's status and the group is
        # empty, the group id may be reused: never signal it again (the same
        # probe-before-kill rule as ``ManagedProcess.cleanup``).
        if process.returncode is not None and not process.tree_exists():
            return
        process.kill_tree()

    # A closed boundary means incumbent cleanup already escalated and released
    # it; signalling after that would act outside the owned boundary.
    streams_closed = True
    readers_closed = True
    group_cleaned = False
    if not process.closed:
        kill_ok = attempt(kill_first)
        attempt(bounded_wait)
        cleanup_result: list[bool] = []
        cleanup_ok = attempt(lambda: cleanup_result.append(process.cleanup(0.0, remaining() / 2)))
        group_cleaned = bool(kill_ok and cleanup_ok and cleanup_result and cleanup_result[0])
    else:
        # A released boundary must not be probed or signalled again. Without
        # the earlier cleanup result, its group settlement remains unproved.
        group_cleaned = False
    if not waited:
        # Native cleanup can reap after the first bounded wait timed out.
        # Read its retained status; no additional wait or PID-absence inference.
        status: list[object] = []
        observed = attempt(lambda: status.append(process.returncode))
        waited = bool(observed and status and type(status[0]) is int)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            closed = attempt(stream.close)
            if not closed and getattr(stream, "closed", False) is not True:
                streams_closed = False
    for reader in readers:
        def join(item: threading.Thread = reader) -> None:
            item.join(timeout=remaining())

        joined = attempt(join)
        alive_fn = getattr(reader, "is_alive", None)
        try:
            alive = alive_fn() if callable(alive_fn) else None
        except Exception as failure:
            original.add_note(
                f"usage worker interrupt cleanup failure: {type(failure).__name__}"
            )
            alive = None
        if not joined or alive is not False:
            readers_closed = False
    try:
        return settlement_for_process(
            process, waited=waited, process_group_cleaned=group_cleaned,
            readers_closed=readers_closed,
            streams_closed=streams_closed and usage_streams_closed(process),
        )
    except (TypeError, ValueError):
        return None
    except Exception as failure:
        original.add_note(f"usage worker settlement observation failure: {type(failure).__name__}")
        return None


__all__ = ("interrupt_cleanup",)
