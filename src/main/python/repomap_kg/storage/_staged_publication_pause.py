"""Disabled-by-default checkpoints around publication-start proof."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

from repomap_kg.runtime import system_test_pause as pause_window
from repomap_kg.runtime.postgres_route import CONTAINER_INTERNAL_MARKER
from repomap_kg.storage.publication_fencing import PublicationHandoff


def _run_system_test_publication_pause(handoff: PublicationHandoff | None = None) -> None:
    """Disabled-by-default checkpoints before or after publication-start proof."""
    key = "_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH" if handoff else "_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH"
    value = os.environ.get(key)
    if not value:
        return
    pause_path = Path(value)
    ready_path = Path(f"{value}.ready")
    try:
        if not pause_path.is_absolute() or pause_path.is_symlink() or pause_path.parent.is_symlink():
            return
        st = pause_path.parent.stat()
        legacy = handoff is not None and pause_path == Path("/tmp/system_pause_trigger") and CONTAINER_INTERNAL_MARKER.is_file()
        if not legacy and (st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o700):
            return
        if handoff is not None:
            pause_window.validate_pause_window_contract()
        content = f"pid={os.getpid()}\n"
        if handoff is not None:
            handoff.validate()
            checkpoint = {"repository_id": handoff.merge.owner.repository_id, "stage_id": handoff.merge.stage_id, "run_id": handoff.merge.run_id,
                          "receipt": handoff.receipt.to_mapping()}
            content += f"job_id={handoff.receipt.attempt.job_id}\nattempt={handoff.merge.owner.attempt}\nhandoff={json.dumps(checkpoint, separators=(',', ':'))}\n"
        marker_fd = os.open(ready_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(marker_fd, "w", encoding="utf-8") as marker:
            marker.write(content)
            marker.flush()
            os.fsync(marker.fileno())
        deadline = time.monotonic() + (pause_window.SYSTEM_TEST_PRODUCER_PAUSE_SECONDS if handoff is not None else 30.0)
        try:
            while pause_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            ready_path.unlink(missing_ok=True)
    except OSError:
        return

_run_system_test_post_publication_pause = _run_system_test_publication_pause

