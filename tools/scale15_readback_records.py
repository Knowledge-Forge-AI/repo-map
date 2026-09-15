"""Evidence and timeout record models for SCALE15 terminal readback."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.storage.authority import PublicationGenerations
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.publication_readback import RunPublicationRecord
from repomap_kg.storage.run_authority import RunAuthoritySnapshot


@dataclass(frozen=True)
class StageTerminalEvidence:
    """Private exact-owner evidence for the newest launched stage."""

    state: str
    merge_status: str
    reconciliation_state: str
    cleanup_eligibility: str
    execution_mode: str
    publication_identity: str
    attempt: int
    generations: PublicationGenerations
    owner_stale: bool


@dataclass(frozen=True)
class TerminalStorageEvidence:
    """Private typed inputs to sanitized terminal classification."""

    repository_identity_matches: bool
    run_authority: RunAuthoritySnapshot
    canonical_publication: RunPublicationRecord | None
    latest_run_receipt: RunPublicationReceipt | None
    latest_run_receipt_malformed: bool
    stage: StageTerminalEvidence | None
    family_counts: dict[str, int]
    structural_digest: str
    repository_exists: bool = True


class TerminalBackendReadTimeout(TimeoutError):
    """One terminal-read deadline result without a quiescence claim."""

    def __init__(self, stage: str) -> None:
        super().__init__("terminal backend read timed out")
        self.stage = stage
        self.backend_quiescent = False
        self.read_count = 1


__all__ = [
    "StageTerminalEvidence",
    "TerminalBackendReadTimeout",
    "TerminalStorageEvidence",
]
