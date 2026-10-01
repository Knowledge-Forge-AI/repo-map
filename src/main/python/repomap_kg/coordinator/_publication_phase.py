"""Private attempt-bound publication gate, independent of diagnostic text.

The supervisor initializes before launch. The publisher and a supervisor with
proved process cleanup compete for one exclusive decision file. A missing or
partial record is uncertainty, never proof of rollback. Closed records survive
capability cleanup so startup reconciliation can consume the same evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from repomap_kg.coordinator._refresh_capability_io import validate_private_directory


def _identity(attempt: object) -> dict[str, object]:
    return {
        "job_id": getattr(attempt, "job_id"),
        "attempt": getattr(attempt, "attempt"),
        "graph_id": getattr(attempt, "graph_id"),
        "instance": getattr(attempt, "coordinator_instance_id", None)
        or getattr(attempt, "instance_id", None),
        "epoch": getattr(attempt, "singleton_fencing_epoch", None)
        or getattr(attempt, "fencing_epoch", None),
        **{key: getattr(attempt, key) for key in (
            "source_generation", "config_generation", "extractor_generation",
            "canonicalizer_generation",
        )},
    }


def _path(directory: Path, attempt: object, suffix: str) -> Path:
    identity = json.dumps(_identity(attempt), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
    return directory / f"publication-{digest}.{suffix}.json"


def _write(path: Path, payload: dict[str, object]) -> None:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        remaining = memoryview(data)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise OSError("publication evidence write failed")
            remaining = remaining[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    # The directory entry must survive a crash before publication begins.
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read(path: Path) -> dict[str, object]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(fd)
        if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
                or not 0 < details.st_size <= 4096):
            raise ValueError("invalid publication evidence")
        payload = json.loads(os.read(fd, 4097))
        if not isinstance(payload, dict):
            raise ValueError("invalid publication evidence")
        return payload
    finally:
        os.close(fd)


def initialize(directory: Path, attempt: object) -> None:
    validate_private_directory(directory)
    _write(_path(directory, attempt, "initial"), _identity(attempt))


def before_publication(directory: Path, attempt: object) -> None:
    if _read(_path(directory, attempt, "initial")) != _identity(attempt):
        raise ValueError("publication evidence identity mismatch")
    _write(_path(directory, attempt, "decision"), {
        **_identity(attempt), "publication_state": "transaction_started",
    })


def publication_state(
    directory: Path, attempt: object, *, close_unpublished: bool = False,
) -> str:
    try:
        validate_private_directory(directory)
        identity = _identity(attempt)
        if _read(_path(directory, attempt, "initial")) != identity:
            return "commit_unknown"
        decision = _path(directory, attempt, "decision")
        if close_unpublished:
            try:
                _write(decision, {**identity, "publication_state": "not_started"})
            except FileExistsError:
                pass
        payload = _read(decision)
        state = payload.pop("publication_state", None)
        if payload == identity and state == "not_started":
            return "not_started"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "commit_unknown"


def retire_evidence(directory: Path, attempt: object) -> tuple[Path, ...]:
    """Safely retire attempt-bound publication phase evidence once terminal.

    Both candidate files (initial and decision) are validated together before either
    is unlinked. On POSIX filesystems without atomic multi-path deletion, validated
    files are unlinked sequentially followed by a directory fsync. If an unexpected
    I/O failure interrupts the sequence, remaining files are retained and surfaced
    as residuals during subsequent cleanup.
    """
    validate_private_directory(directory)
    identity = _identity(attempt)
    candidates = (
        ("initial", _path(directory, attempt, "initial")),
        ("decision", _path(directory, attempt, "decision")),
    )
    validated: list[Path] = []
    for suffix, path in candidates:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError(f"cannot open publication evidence file: {path.name}") from error
        try:
            fst = os.fstat(fd)
            if (
                not stat.S_ISREG(fst.st_mode)
                or stat.S_ISLNK(fst.st_mode)
                or fst.st_uid != os.getuid()
                or stat.S_IMODE(fst.st_mode) != 0o600
                or fst.st_nlink != 1
                or not 0 < fst.st_size <= 4096
            ):
                raise ValueError(f"invalid publication evidence file: {path.name}")
            raw = os.read(fd, 4097)
            try:
                payload = json.loads(raw)
            except Exception as error:
                raise ValueError("publication evidence is not valid json") from error
            if not isinstance(payload, dict):
                raise ValueError("invalid publication evidence payload")
            if suffix == "decision":
                state = payload.pop("publication_state", None)
                if state not in {"not_started", "transaction_started"}:
                    raise ValueError("invalid publication decision evidence")
            if payload != identity:
                raise ValueError("publication evidence identity mismatch")
        finally:
            os.close(fd)
        validated.append(path)

    if not validated:
        return ()

    for path in validated:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    return tuple(validated)
