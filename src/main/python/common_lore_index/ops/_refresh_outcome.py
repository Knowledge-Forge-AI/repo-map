"""Pure classification of staged refresh failures."""

from __future__ import annotations

from common_lore_index.ops._portable_retention import PortableRefreshError
from common_lore_index.storage.errors import StorageCommitUnknownError
from common_lore_index.storage.publication_phase_witness import PublicationPhase


_UNCERTAIN_PHASES = frozenset(
    {
        PublicationPhase.FINAL_TRANSACTION,
        PublicationPhase.COMMIT_ATTEMPTED,
        PublicationPhase.RECONCILING,
        PublicationPhase.COMMITTED,
    }
)


def classify_refresh_failure(
    phase: PublicationPhase, error: BaseException
) -> tuple[str, str]:
    """Map witnessed publication progress and an error to public categories."""

    if phase is PublicationPhase.RETURNED:
        publication_state = "commit_unknown"
    elif isinstance(error, StorageCommitUnknownError) or getattr(
        error, "is_commit_unknown", False
    ):
        publication_state = "commit_unknown"
    elif phase in _UNCERTAIN_PHASES:
        publication_state = "commit_unknown"
    elif phase is PublicationPhase.ROLLED_BACK:
        publication_state = "rolled_back"
    else:
        publication_state = "not_started"

    cancelled = isinstance(error, KeyboardInterrupt) or isinstance(
        getattr(error, "__cause__", None), KeyboardInterrupt
    )
    if cancelled:
        error_category = "cancelled"
    elif publication_state == "commit_unknown":
        error_category = "publication_unknown"
    elif isinstance(error, PortableRefreshError):
        error_category = error.category
    else:
        error_category = "worker_crash"
    return publication_state, error_category


__all__ = ("classify_refresh_failure",)
