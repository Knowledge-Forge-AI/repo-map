"""Opt-in usage-launch entry into the shared abnormal settlement (ADR 0173 B1).

``collect_usage=True`` supervision still calls this module-global entry. It
delegates to the one shared algorithm in ``_launch_custody_steps`` and returns
only the existing immutable ``UsageSettlement`` projection, so the usage-A
lifecycle owners and observer validation stay unchanged. Default, facade and
ticketed native launches use the full ``CustodyOutcome`` instead.

Per worker custody decision D2 (superseding ADR 0173 B1), a guarded second
``BaseException`` no longer replaces the original: it becomes a type-only note,
the remaining work except guarded stream closes is abandoned, and the
settlement is unproven. No hard operating-system wall-time bound is claimed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import threading
import time
from typing import Any

from common_lore_index.coordinator._launch_custody_steps import settle_abnormal_exit
from common_lore_index.coordinator._usage_observation import UsageSettlement

USAGE_LABEL = "usage worker"


def interrupt_cleanup(
    process: Any,
    readers: Sequence[threading.Thread],
    termination_grace: float,
    original: BaseException,
    *,
    _monotonic: Callable[[], float] = time.monotonic,
) -> UsageSettlement | None:
    """Run the shared bounded kill-first settlement; never replaces ``original``."""

    outcome = settle_abnormal_exit(
        process, readers, termination_grace, original,
        label=USAGE_LABEL, _monotonic=_monotonic,
    )
    return outcome.usage


__all__ = ("USAGE_LABEL", "interrupt_cleanup")
