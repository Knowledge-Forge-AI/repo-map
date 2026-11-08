"""In-process publication phase evidence for one staged refresh call."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class PublicationPhase(IntEnum):
    NOT_ENTERED = 0
    FINAL_TRANSACTION = 1
    ROLLED_BACK = 2
    COMMIT_ATTEMPTED = 3
    RECONCILING = 4
    COMMITTED = 5
    RETURNED = 6


@dataclass
class PublicationPhaseWitness:
    """Monotone, non-IO evidence owned by one refresh caller."""

    phase: PublicationPhase = PublicationPhase.NOT_ENTERED

    def advance(self, phase: PublicationPhase) -> None:
        """Advance to ``phase`` without allowing observation to raise."""

        try:
            if phase > self.phase:
                self.phase = phase
        except BaseException:
            # The witness is evidence only; a malformed observer update must
            # never replace the publication exception it is recording.
            return


__all__ = ("PublicationPhase", "PublicationPhaseWitness")
