"""Small immutable models shared by observer trace evidence consumers."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_test_support.observer_trace_vocabulary import ObserverTraceEvidenceError


@dataclass(frozen=True, slots=True)
class TerminalCounts:
    attempted: int
    terminally_classified: int
    published: int
    failed: int
    unclassified_or_interrupted: int


def reconcile_terminal_counts(
    *,
    attempted: int,
    terminally_classified: int,
    published: int,
    failed: int,
    unclassified_or_interrupted: int,
) -> TerminalCounts:
    counts = TerminalCounts(
        attempted,
        terminally_classified,
        published,
        failed,
        unclassified_or_interrupted,
    )
    if (
        terminally_classified != published + failed
        or attempted != terminally_classified + unclassified_or_interrupted
    ):
        raise ObserverTraceEvidenceError("terminal counts do not reconcile")
    return counts


__all__ = ["TerminalCounts", "reconcile_terminal_counts"]
