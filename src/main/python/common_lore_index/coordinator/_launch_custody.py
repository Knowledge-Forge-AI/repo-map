"""Launch provenance and abnormal-exit dispatch for one supervised worker.

Canonical intent means the effective launch callable (explicit argument or the
current module global) is the original ``launch_managed_process`` captured
when this module was imported; that includes the canonical facade. Genuine
native provenance is a separate fact recorded by that launch on the returned
``ManagedProcess``. New default, facade and ticketed custody requires both.

| Mode | Factory / Popen | Abnormal entry |
|---|---|---|
| default/facade/ticketed | original / original real child | shared outcome |
| default | patched or custom callable | incumbent (none) |
| default | original / patched or fake Popen | incumbent (none) |
| usage | any admitted launch | ``interrupt_cleanup`` shim |

Usage and ticketed launches refuse an explicit callable before launch. T0
simulations may drive the shim but never establish native custody.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import threading

from common_lore_index.coordinator._launch_custody_steps import (
    CustodyOutcome,
    settle_abnormal_exit,
)
from common_lore_index.coordinator._usage_observation import UsageObserver, UsageSettlement
from common_lore_index.coordinator.process_supervision import (
    ManagedProcess,
    launch_managed_process as _ORIGINAL_LAUNCH,
)

UsageCleanup = Callable[..., UsageSettlement | None]


def is_canonical_launch(launch_process: object) -> bool:
    """The effective callable is the captured original launch function."""
    return launch_process is _ORIGINAL_LAUNCH


def has_native_custody(process: object, canonical: bool) -> bool:
    """Canonical intent and genuine recorded native provenance, never a pid claim."""
    return canonical and isinstance(process, ManagedProcess) and process.native


class WorkerCustody:
    """Primary, observer and ticket truth for one launched worker."""

    def __init__(
        self,
        process: object,
        *,
        canonical: bool,
        readers: Sequence[threading.Thread],
        termination_grace: float,
        collect_usage: bool,
        observer: UsageObserver | None,
        ticket: object | None,
    ) -> None:
        self.process = process
        self.native = has_native_custody(process, canonical)
        self.readers = readers
        self.termination_grace = termination_grace
        self.collect_usage = collect_usage
        self.observer = observer
        self.ticket = ticket
        self.settled_notified = False
        self.outcome: CustodyOutcome | None = None

    def notify_settled(self, facts: UsageSettlement) -> None:
        """Normal-path delivery; marked first so a failure is never retried."""
        assert self.observer is not None
        self.settled_notified = True
        self.observer.settled(facts)

    def settle(self, primary: BaseException, usage_cleanup: UsageCleanup) -> None:
        """Abnormal settlement after ``primary``; the caller re-raises it.

        Any escape from settlement becomes a type-only note (D2); the outcome
        then stays unset and a ticketed registration stays held.
        """
        _guarded(primary, "worker custody settlement",
                 lambda: self._settle(primary, usage_cleanup))

    def _settle(self, primary: BaseException, usage_cleanup: UsageCleanup) -> None:
        if self.collect_usage:
            facts = usage_cleanup(self.process, self.readers, self.termination_grace, primary)
            observer = self.observer
            if observer is not None and not self.settled_notified and facts is not None:
                self.settled_notified = True
                _guarded(primary, "usage observer settlement", lambda: observer.settled(facts))
            return
        if not self.native:
            return  # incumbent injected or simulated behavior; no new handler
        self.outcome = settle_abnormal_exit(
            self.process, self.readers, self.termination_grace, primary)
        if self.ticket is not None:
            from common_lore_index.coordinator._supervisor_fencing import _release_abnormal_launch

            outcome = self.outcome
            _guarded(primary, "worker custody release",
                     lambda: _release_abnormal_launch(self.ticket, self.process, outcome))


def _guarded(primary: BaseException, kind: str, step: Callable[[], object]) -> None:
    try:
        step()
    except BaseException as failure:  # a secondary failure never replaces the primary
        _note(primary, f"{kind} failure: {type(failure).__name__}")


def _note(primary: BaseException, text: str) -> None:
    """Best-effort diagnostics cannot replace the original exception."""
    try:
        primary.add_note(text)
    except BaseException:
        return


__all__ = (
    "WorkerCustody",
    "has_native_custody",
    "is_canonical_launch",
)
