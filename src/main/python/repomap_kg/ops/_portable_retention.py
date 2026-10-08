"""Retained portable attempt records shared by the PostgreSQL and SQLite routes.

Extracted from ``ops.portable_refresh`` (REPOMAP-PRODUCT3-SQLITE-LOCAL1) so
both publishers reuse one retention contract: an owner-only
``portable-result.json`` per attempt, reconciliation retention until a terminal
mark, and expiry pruning of terminal attempts. LOCAL3 added the SQLite Local
reconciliation helpers: annotating an unsettled record, listing every
``publication-reconciliation`` record under an attempts directory, and one
shared atomic record replacement. Replacement always fsyncs the record file.
LOCAL7 added ``sync_directory``: the SQLite Local route passes ``True``. Such a
record must live at
``state/portable-publication/sqlite-local/<graph>/attempts/<token>/`` (anything
else refuses before any write), and after the replace the attempt directory and
every Local retention namespace level up to and including ``state/`` are
fsynced, so a namespace created by the first capture is durable too. The home
and anything above it are never synced: ``sqlite-init`` and restore already
made ``state/`` durable in the home (``ops sqlite-cleanup --yes`` establishes
that for an existing home from then on, LOCAL9). A failed sync is a bounded
``local-durability-*`` refusal. The PostgreSQL route keeps the default
``False``: it fsyncs the record file only and does not claim power-loss
durability of the rename.

LOCAL9 names the whole resolved Local chain, ``state`` included, and refuses a
record whose attempt directory is reached through a symlink or ``..`` below
the (already resolved) publication root. It also adds the read-only
``classify_retained_attempts`` inventory and
``remove_expired_terminal_attempt`` used by ``ops sqlite-cleanup``: only an
owner-valid terminal record whose integer ``expires_at_epoch`` has passed, in
an attempt tree of real directories and single-link owner files, is ever
removable. Unsettled and record-less attempts are only reported.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from repomap_kg.artifacts import ArtifactReference
from repomap_kg.coordinator._portable_materialization import (
    OwnedDirectoryIdentity,
    _directory_identity,
    _remove_attempt_root,
)
from repomap_kg.storage.sqlite_local.durability import fsync_directory_chain

class PortableRefreshError(ValueError):
    """Bounded production-route failure that grants no fallback authority."""

    def __init__(self, message: str, *, category: str = "contract_validation"):
        super().__init__(message)
        self.category = category
        self.publication_state = "not_started"


_TERMINAL_RETENTION_SECONDS = 24 * 60 * 60
_TERMINAL_RETENTION_CLASSES = frozenset({"terminal-accepted", "terminal-failed"})
# Parent levels synced above a Local attempt directory: attempts/, <graph>/,
# sqlite-local/, portable-publication/ and the state/ directory holding them.
_LOCAL_RETENTION_SYNC_LEVELS = 5


def _write_retained_result(path, manifest_id, references):
    payload = {
        "manifest_id": manifest_id,
        "receipt": references[0].to_mapping(),
        "bundle": references[1].to_mapping(),
        "retention_class": "publication-reconciliation",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("portable retention write failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _retained_result(path, expected_manifest_id):
    if not path.exists():
        return None
    try:
        payload = _read_retention_payload(path)
        if payload.get("manifest_id") != expected_manifest_id:
            raise ValueError
        if payload.get("retention_class") not in {
            "publication-reconciliation",
            *_TERMINAL_RETENTION_CLASSES,
        }:
            raise ValueError
        receipt_mapping = payload.get("receipt")
        bundle_mapping = payload.get("bundle")
        if not isinstance(receipt_mapping, Mapping) or not isinstance(
            bundle_mapping, Mapping
        ):
            raise ValueError
        return (
            ArtifactReference.from_mapping(receipt_mapping),
            ArtifactReference.from_mapping(bundle_mapping),
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise PortableRefreshError("retained portable result is invalid") from error


def _read_retention_payload(path: Path) -> dict[str, object]:
    expected = path.lstat()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(descriptor)
        if (
            (expected.st_dev, expected.st_ino) != (details.st_dev, details.st_ino)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size > 64 * 1024
        ):
            raise ValueError
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                raise ValueError
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError
    return payload


def _mark_retained_terminal(
    path: Path, retention_class: str, *, sync_directory: bool = False
) -> None:
    if retention_class not in _TERMINAL_RETENTION_CLASSES:
        raise ValueError("invalid portable retention class")
    payload = _read_retention_payload(path)
    payload["retention_class"] = retention_class
    payload["expires_at_epoch"] = int(time.time()) + _TERMINAL_RETENTION_SECONDS
    _replace_retention_payload(path, payload, sync_directory=sync_directory)


def _annotate_retained_attempt(
    path: Path, key: str, value: Mapping[str, object], *, sync_directory: bool = False
) -> None:
    """Add one block to an unsettled attempt record; never overwrite or settle it."""
    payload = _read_retention_payload(path)
    if payload.get("retention_class") != "publication-reconciliation" or key in payload:
        raise PortableRefreshError("retained portable attempt cannot be annotated")
    payload[key] = dict(value)
    _replace_retention_payload(path, payload, sync_directory=sync_directory)


def _unsettled_retained_attempts(parent: Path) -> list[tuple[Path, dict[str, object]]]:
    """Every record under ``parent`` still retained for publication reconciliation.

    Attempt directories without a record never produced a worker result and are
    skipped. Any other unreadable, invalid or non-directory entry refuses.
    """
    found: list[tuple[Path, dict[str, object]]] = []
    try:
        for candidate in sorted(parent.iterdir()):
            if not stat.S_ISDIR(candidate.lstat().st_mode):
                raise ValueError
            record = candidate / "portable-result.json"
            if not os.path.lexists(record):
                continue
            payload = _read_retention_payload(record)
            retention_class = payload.get("retention_class")
            if retention_class == "publication-reconciliation":
                found.append((record, payload))
            elif retention_class not in _TERMINAL_RETENTION_CLASSES:
                raise ValueError
    except (OSError, TypeError, ValueError) as error:
        raise PortableRefreshError("retained portable attempt is invalid") from error
    return found


def _replace_retention_payload(
    path: Path, payload: Mapping[str, object], *, sync_directory: bool = False
) -> None:
    attempt = _local_attempt_directory(path) if sync_directory else None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("portable retention update failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    if attempt is not None:
        # Every level is synced on every replacement: an existing namespace may
        # have been created by a process that crashed before syncing it.
        fsync_directory_chain(attempt, _LOCAL_RETENTION_SYNC_LEVELS)


def _local_attempt_directory(path: Path) -> Path:
    """The resolved attempt directory of a Local record, or a bounded refusal.

    Requiring the Local layout keeps the directory chain inside the Local
    retention namespace. Every resolved level is name-checked, ``state``
    included (LOCAL9), and the attempt directory must already be its own
    resolved form, so no symlink or ``..`` below the publication root can
    redirect the chain into another same-shaped tree. Callers build the path
    from the resolved publication root, so a symlinked home or ``state`` has
    been resolved before this check and is judged by its resolved names.
    """
    requested = Path(os.path.abspath(path.parent))
    attempt = requested.resolve()
    levels = attempt.parents
    if (
        attempt != requested
        or len(levels) <= _LOCAL_RETENTION_SYNC_LEVELS
        or tuple(levels[index].name for index in (0, 2, 3, 4))
        != ("attempts", "sqlite-local", "portable-publication", "state")
    ):
        raise PortableRefreshError("retained portable record is outside the Local retention namespace")
    return attempt


def _prune_expired_terminal_attempts(parent: Path, *, exclude: Path) -> None:
    for candidate in parent.iterdir():
        if candidate == exclude:
            continue
        try:
            identity = _directory_identity(candidate)
            payload = _read_retention_payload(candidate / "portable-result.json")
            retention_class = payload.get("retention_class")
            expires_at = payload.get("expires_at_epoch")
            if (
                retention_class in _TERMINAL_RETENTION_CLASSES
                and isinstance(expires_at, int)
                and not isinstance(expires_at, bool)
                and expires_at <= int(time.time())
            ):
                _remove_attempt_root(candidate, identity)
        except (FileNotFoundError, OSError, TypeError, ValueError, RuntimeError):
            continue


# LOCAL9 cleanup inventory. Statuses are public counts only; entry names never are.
EXPIRED_TERMINAL = "expired-terminal"
RETAINED_TERMINAL = "retained-terminal"
UNSETTLED = "unsettled"
INCOMPLETE = "incomplete"
UNSAFE = "unsafe"


@dataclass(frozen=True)
class RetainedAttempt:
    """One classified entry of an attempts directory; ``name`` is operator-private."""

    name: str
    status: str
    identity: OwnedDirectoryIdentity | None


def classify_retained_attempts(parent: Path, *, now: int) -> list[RetainedAttempt]:
    """Classify every entry of one attempts directory; nothing is changed.

    ``unsettled`` (a ``publication-reconciliation`` record, armed or not) and
    ``incomplete`` (no record: the capture never produced a worker result) are
    never removable. A terminal record expires under the existing prune rule.
    Anything that is not an owner directory with a valid record, and any
    expired attempt whose tree holds more than real directories and
    single-link owner files, is ``unsafe``.
    """
    return [
        RetainedAttempt(name, *_classify_attempt(parent / name, now))
        for name in sorted(os.listdir(parent))
    ]


def _classify_attempt(root: Path, now: int) -> tuple[str, OwnedDirectoryIdentity | None]:
    try:
        identity = _directory_identity(root)
        if identity.owner_uid != os.getuid():
            return UNSAFE, None
        record = root / "portable-result.json"
        if not os.path.lexists(record):
            return INCOMPLETE, identity
        payload = _read_retention_payload(record)
        retention_class = payload.get("retention_class")
        if retention_class == "publication-reconciliation":
            return UNSETTLED, identity
        expires_at = payload.get("expires_at_epoch")
        if (
            retention_class not in _TERMINAL_RETENTION_CLASSES
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
        ):
            return UNSAFE, None
        if expires_at > now:
            return RETAINED_TERMINAL, identity
        _require_removable_tree(root)
        return EXPIRED_TERMINAL, identity
    except (OSError, RuntimeError, TypeError, ValueError):
        return UNSAFE, None


def _require_removable_tree(directory: Path) -> None:
    """Refuse any node ``_remove_attempt_root`` could stop at after deleting part of a tree."""
    with os.scandir(directory) as entries:
        for entry in entries:
            details = entry.stat(follow_symlinks=False)
            if details.st_uid != os.getuid():
                raise ValueError("retained attempt node is not owned")
            if stat.S_ISDIR(details.st_mode):
                _require_removable_tree(Path(entry.path))
            elif not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise ValueError("retained attempt node is not removable")


def remove_expired_terminal_attempt(
    root: Path, identity: OwnedDirectoryIdentity | None, *, now: int
) -> None:
    """Remove one attempt still classified expired-terminal with the same identity."""
    if identity is None or _classify_attempt(root, now) != (EXPIRED_TERMINAL, identity):
        raise ValueError("retained portable attempt changed")
    _remove_attempt_root(root, identity)
