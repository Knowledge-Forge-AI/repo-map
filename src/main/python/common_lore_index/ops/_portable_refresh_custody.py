"""Exception custody helpers for the trusted portable refresh route."""

from __future__ import annotations

from typing import Any
from pathlib import Path
import os
import stat

from common_lore_index.coordinator._portable_materialization import (
    OwnedDirectoryIdentity, _remove_attempt_root,
)
from common_lore_index.ops._server_retention_lock import retention_lock_for

from common_lore_index.storage.errors import StorageCommitUnknownError
from common_lore_index.storage.publication_phase_witness import (
    PublicationPhase, PublicationPhaseWitness,
)


def note_secondary(primary: BaseException, secondary: BaseException) -> None:
    """Attach categorical cleanup evidence without replacing ``primary``."""

    try:
        primary.add_note(f"portable refresh cleanup failure: {type(secondary).__name__}")
    except BaseException:
        pass


def close_validated(validated: Any, primary: BaseException | None) -> None:
    """Close validated storage, preserving an already-propagating exception."""

    try:
        validated.close()
    except BaseException as secondary:
        if primary is None:
            raise
        note_secondary(primary, secondary)


def settle_after_publisher_error(
    capture: Any,
    error: BaseException,
    *,
    publication_witness: PublicationPhaseWitness | None,
    publisher_returned: bool,
) -> None:
    """Mark only a proved pre-publication failure; retain uncertainty otherwise."""

    phase = publication_witness.phase if publication_witness is not None else (
        PublicationPhase.RETURNED if publisher_returned else PublicationPhase.RECONCILING
    )
    can_mark_failed = (
        not publisher_returned
        and phase in {PublicationPhase.NOT_ENTERED, PublicationPhase.ROLLED_BACK}
        and not isinstance(error, StorageCommitUnknownError)
        and not getattr(error, "is_commit_unknown", False)
    )
    if not can_mark_failed:
        return
    try:
        capture.mark_terminal(accepted=False)
    except BaseException as secondary:
        note_secondary(error, secondary)


def remove_capture_attempt(root: Path, identity: OwnedDirectoryIdentity | None) -> None:
    """Coordinate Server capture-error removal with retained metadata settlement."""
    with retention_lock_for(root):
        _remove_attempt_root(root, identity)


def prepare_server_publication_root(root: Path) -> None:
    """Make only a newly owned Server anchor private, independent of umask."""
    try:
        root.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        # Existing anchors are admitted by the retention lock, never migrated.
        return
    created = root.lstat()
    if not stat.S_ISDIR(created.st_mode) or created.st_uid != os.getuid():
        raise OSError("new Server publication root is unsafe")
    root.chmod(0o700)
    current = root.lstat()
    if (current.st_dev, current.st_ino) != (created.st_dev, created.st_ino):
        raise OSError("new Server publication root changed")


__all__ = (
    "close_validated", "note_secondary", "prepare_server_publication_root",
    "remove_capture_attempt", "settle_after_publisher_error",
)
