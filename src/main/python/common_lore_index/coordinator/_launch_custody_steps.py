"""The one shared abnormal-exit settlement algorithm for an owned worker.

Every step shares one cooperative monotonic deadline of twice the termination
grace (no hard wall-time guarantee, X2/X7):

1. kill first under ownership rules: never after release; a live known leader
   or a fresh ``members`` probe permits the owned group signal, while ``empty``
   or ``unprobeable`` does not;
2. one bounded owner wait;
3. ``cleanup`` with zero TERM grace and at most half the remaining budget per
   incumbent kill wait (a released boundary returns its retained result);
4. close stdin, stdout and stderr, then join readers with what remains.

An ordinary secondary ``Exception`` becomes a path-free, type-only note on the
primary. A guarded second ``BaseException`` is noted too; all remaining work is
then abandoned except guarded stream-close attempts and custody is unproven.
The caller re-raises the original exception object; this module never does.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import subprocess
import threading
import time
from typing import Any

from common_lore_index.coordinator._process_supervision_state import LIVE, MEMBERS, REAPED
from common_lore_index.coordinator._usage_observation import (
    UsageSettlement,
    settlement_for_process,
    usage_streams_closed,
)

GENERIC_LABEL = "worker"


@dataclass(frozen=True, slots=True)
class CustodyOutcome:
    """Facts established by abnormal settlement; proven only when all hold.

    ``group_empty`` is the independent pre-close group observation retained by
    ``ManagedProcess``.  It may be true under unknown owner status or after a
    first signal failure. Unknown status keeps custody unproven; an ordinary
    signal failure can recover when subsequent cleanup establishes every fact.
    """

    status_known: bool
    returncode: int | None
    group_empty: bool
    released: bool
    readers_joined: bool
    streams_closed: bool
    proven: bool
    reason: str | None
    usage: UsageSettlement | None = None


class _Steps:
    def __init__(self, primary: BaseException, label: str) -> None:
        self.primary, self.label, self.interrupted = primary, label, False

    def note(self, failure: BaseException, kind: str = "interrupt cleanup") -> None:
        try:
            self.primary.add_note(f"{self.label} {kind} failure: {type(failure).__name__}")
        except Exception:
            pass  # ordinary diagnostic failure does not abandon cleanup
        except BaseException:
            self.interrupted = True  # retain the second-interrupt close-only rule

    def attempt(self, step: Callable[[], object], *, after_interrupt: bool = False) -> bool:
        if self.interrupted and not after_interrupt:
            return False
        try:
            step()
            return True
        except Exception as failure:
            self.note(failure)
            return False
        except BaseException as failure:
            self.note(failure)
            self.interrupted = True
            return False


def _reason(facts: dict[str, bool]) -> str | None:
    for reason, held in facts.items():
        if not held:
            return reason
    return None


def settle_abnormal_exit(
    process: Any,
    readers: Sequence[threading.Thread],
    termination_grace: float,
    primary: BaseException,
    *,
    label: str = GENERIC_LABEL,
    _monotonic: Callable[[], float] = time.monotonic,
) -> CustodyOutcome:
    """Settle one owned worker after ``primary``; never replaces ``primary``."""

    deadline = _monotonic() + 2 * termination_grace
    steps = _Steps(primary, label)

    def remaining() -> float:
        return max(0.0, deadline - _monotonic())

    def kill_first() -> None:
        if process.closed:
            return
        if process.reap_state() == LIVE or process.group_state() == MEMBERS:
            process.kill_tree()

    def owner_wait() -> None:
        if process.closed:
            return
        try:
            process._wait_quiet(min(termination_grace, remaining()))
        except subprocess.TimeoutExpired:
            pass  # cleanup below escalates within the shared deadline

    steps.attempt(kill_first)
    steps.attempt(owner_wait)
    steps.attempt(lambda: process.cleanup(0.0, remaining() / 2))
    observed_group: list[bool | None] = []
    steps.attempt(lambda: observed_group.append(process.group_empty_observed))
    group_empty = observed_group == [True]
    state: list[str] = []
    steps.attempt(lambda: state.append(process.reap_state()))
    status_known = state == [REAPED]
    released: list[bool] = []
    steps.attempt(lambda: released.append(process.closed is True))
    streams_closed = True
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None:
            closed = steps.attempt(stream.close, after_interrupt=True)
            if not closed and getattr(stream, "closed", False) is not True:
                streams_closed = False
    readers_joined = not steps.interrupted
    for reader in readers:
        joined = steps.attempt(lambda: reader.join(timeout=remaining()))
        alive: list[object] = []
        steps.attempt(lambda: alive.append(reader.is_alive()))
        if not joined or alive != [False]:
            readers_joined = False
    usage_closed: list[bool] = []
    steps.attempt(lambda: usage_closed.append(usage_streams_closed(process)), after_interrupt=True)
    streams_closed = streams_closed and usage_closed == [True]
    facts = {
        "interrupted": not steps.interrupted,
        "status_unknown": status_known,
        "group_not_proven": group_empty,
        "release_not_proven": released == [True],
        "readers_alive": readers_joined,
        "streams_open": streams_closed,
    }
    reason = _reason(facts)
    return CustodyOutcome(
        status_known=status_known,
        returncode=process.returncode if status_known else None,
        group_empty=group_empty,
        released=released == [True],
        readers_joined=readers_joined,
        streams_closed=streams_closed,
        proven=reason is None,
        reason=reason,
        usage=_usage_projection(process, steps, status_known, group_empty,
                                readers_joined, streams_closed),
    )


def _usage_projection(process: Any, steps: _Steps, waited: bool, group_empty: bool,
                      readers_joined: bool, streams_closed: bool) -> UsageSettlement | None:
    try:
        return settlement_for_process(
            process, waited=waited, process_group_cleaned=group_empty,
            readers_closed=readers_joined, streams_closed=streams_closed,
        )
    except (TypeError, ValueError):
        return None
    except Exception as failure:
        steps.note(failure, "settlement observation")
        return None


__all__ = ("CustodyOutcome", "GENERIC_LABEL", "settle_abnormal_exit")
