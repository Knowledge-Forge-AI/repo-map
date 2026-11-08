"""Custody and compare-and-replace helpers for one Server attempt record."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from collections.abc import Mapping
from typing import cast

from common_lore_index.artifacts import ArtifactReference
from common_lore_index.ops._server_retention_lock import server_attempts_parent

RECORD_NAME = "portable-result.json"
RECORD_LIMIT = 64 * 1024
BACKUP_NAME = "portable-result.json.backup"
TERMINAL_ACCEPTED = "terminal-accepted"
TERMINAL_FAILED = "terminal-failed"
RECONCILIATION = "publication-reconciliation"


class RetainedRecordError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class MetadataInstallError(OSError):
    def __init__(self, *, post_install: bool):
        super().__init__("retained metadata durability failed")
        self.post_install = post_install


@dataclass(frozen=True)
class RetainedRecord:
    root: Path
    path: Path
    payload: dict[str, object]
    raw: bytes
    digest: str
    file_identity: tuple[int, int, int, int, int]
    directory_identity: tuple[tuple[int, int, int, int], ...]

    @property
    def retention_class(self) -> str:
        value = self.payload.get("retention_class")
        assert isinstance(value, str)
        return value

    @property
    def references(self) -> tuple[ArtifactReference, ArtifactReference, ArtifactReference]:
        try:
            values = tuple(self.payload[name] for name in ("manifest", "receipt", "bundle"))
            if not all(isinstance(value, Mapping) for value in values):
                raise ValueError
            references = [
                ArtifactReference.from_mapping(cast(Mapping[str, object], value))
                for value in values
            ]
            return references[0], references[1], references[2]
        except (KeyError, TypeError, ValueError) as error:
            raise RetainedRecordError("record-invalid") from error


def _directory_details(path: Path, *, strict: bool = True) -> tuple[int, int, int, int]:
    try:
        details = path.lstat()
    except (FileNotFoundError, OSError) as error:
        raise RetainedRecordError("namespace-unavailable") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or (stat.S_IMODE(details.st_mode) != 0o700 if strict else stat.S_IMODE(details.st_mode) & 0o022)
        or path.resolve() != path.absolute()
    ):
        raise RetainedRecordError("unsafe-record")
    return (details.st_dev, details.st_ino, details.st_uid, stat.S_IMODE(details.st_mode))


def _layout(root: Path) -> tuple[tuple[int, int, int, int], ...]:
    parent = server_attempts_parent(root)
    if parent is None or root.parent != parent:
        raise RetainedRecordError("unsafe-record")
    return (
        _directory_details(parent.parent, strict=False),
        _directory_details(parent),
        _directory_details(root),
    )


def _read_file(path: Path) -> tuple[bytes, tuple[int, int, int, int, int]]:
    primary: BaseException | None = None
    try:
        expected = path.lstat()
        if (
            not stat.S_ISREG(expected.st_mode)
            or expected.st_uid != os.getuid()
            or expected.st_nlink != 1
            or stat.S_IMODE(expected.st_mode) != 0o600
            or expected.st_size > RECORD_LIMIT
        ):
            raise RetainedRecordError("unsafe-record")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as error:
        raise RetainedRecordError("record-missing") from error
    except RetainedRecordError:
        raise
    except OSError as error:
        raise RetainedRecordError("record-unavailable") from error
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_size > RECORD_LIMIT
            or not stat.S_ISREG(opened.st_mode)
            or
            (opened.st_dev, opened.st_ino, opened.st_uid, opened.st_nlink, stat.S_IMODE(opened.st_mode))
            != (expected.st_dev, expected.st_ino, expected.st_uid, expected.st_nlink, stat.S_IMODE(expected.st_mode))
        ):
            raise RetainedRecordError("unsafe-record")
        data = bytearray()
        while len(data) < opened.st_size:
            chunk = os.read(descriptor, min(8192, opened.st_size - len(data)))
            if not chunk:
                raise RetainedRecordError("record-invalid")
            data.extend(chunk)
        if os.read(descriptor, 1):
            raise RetainedRecordError("record-invalid")
        return bytes(data), (opened.st_dev, opened.st_ino, opened.st_uid, opened.st_nlink, stat.S_IMODE(opened.st_mode))
    except RetainedRecordError as error:
        primary = error
        raise
    except OSError as error:
        primary = error
        raise RetainedRecordError("record-unavailable") from error
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as error:
            if primary is None:
                raise
            try:
                primary.add_note(f"retained record close failure: {type(error).__name__}")
            except BaseException:
                pass


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate record key")
        value[key] = item
    return value


def read_retained_record(root: Path) -> RetainedRecord:
    """Read one exact, current-format owner-private Server record."""
    root = Path(root)
    try:
        exists = os.path.lexists(root)
    except OSError as error:
        raise RetainedRecordError("namespace-unavailable") from error
    if not exists:
        raise RetainedRecordError("record-missing")
    directories = _layout(root)
    path = root / RECORD_NAME
    raw, identity = _read_file(path)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(payload, dict):
            raise ValueError
        if not isinstance(payload.get("manifest_id"), str):
            raise ValueError
        if "manifest" not in payload:
            raise RetainedRecordError("legacy-record")
        if payload.get("retention_class") not in {RECONCILIATION, TERMINAL_ACCEPTED, TERMINAL_FAILED}:
            raise ValueError
        if set(payload) - {
            "manifest_id", "manifest", "receipt", "bundle",
            "retention_class", "expires_at_epoch",
        }:
            raise ValueError
        if any(name not in payload for name in ("receipt", "bundle")):
            raise ValueError
        if payload["retention_class"] != RECONCILIATION and (
            type(payload.get("expires_at_epoch")) is not int
        ):
            raise ValueError
        if payload["retention_class"] == RECONCILIATION and "expires_at_epoch" in payload:
            raise ValueError
        values = tuple(payload[name] for name in ("manifest", "receipt", "bundle"))
        if not all(isinstance(value, Mapping) for value in values):
            raise ValueError
        for value in values:
            ArtifactReference.from_mapping(value)
    except RetainedRecordError:
        raise
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise RetainedRecordError("record-invalid") from error
    return RetainedRecord(root, path, payload, raw, hashlib.sha256(raw).hexdigest(), identity, directories)


def same_record(before: RetainedRecord, after: RetainedRecord) -> bool:
    return (
        before.raw == after.raw
        and before.digest == after.digest
        and before.file_identity == after.file_identity
        and before.directory_identity == after.directory_identity
    )


def _write_exact(path: Path, data: bytes) -> tuple[int, int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    primary: BaseException | None = None
    identity: tuple[int, int, int] | None = None
    try:
        details = os.fstat(descriptor)
        identity = (details.st_dev, details.st_ino, details.st_uid)
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("retained metadata write failed")
            view = view[written:]
        os.fsync(descriptor)
        return identity
    except BaseException as error:
        primary = error
        if identity is not None:
            try:
                current = path.lstat()
                if (
                    (current.st_dev, current.st_ino, current.st_uid) != identity
                    or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                ):
                    raise OSError("new metadata file changed before cleanup")
                path.unlink()
            except FileNotFoundError:
                pass
            except BaseException as cleanup:
                try:
                    error.add_note(f"new metadata cleanup failure: {type(cleanup).__name__}")
                except BaseException:
                    pass
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as error:
            if primary is None:
                raise
            try:
                primary.add_note(f"retained metadata close failure: {type(error).__name__}")
            except BaseException:
                pass


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    primary: BaseException | None = None
    try:
        os.fsync(descriptor)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as error:
            if primary is None:
                raise
            try:
                primary.add_note(f"retained directory close failure: {type(error).__name__}")
            except BaseException:
                pass


def _sync_file(path: Path, expected: tuple[int, int, int, int, int]) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    primary: BaseException | None = None
    try:
        details = os.fstat(descriptor)
        identity = (details.st_dev, details.st_ino, details.st_uid, details.st_nlink, stat.S_IMODE(details.st_mode))
        if identity != expected or not stat.S_ISREG(details.st_mode):
            raise RetainedRecordError("metadata-race")
        os.fsync(descriptor)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as cleanup:
            if primary is None:
                raise
            try:
                primary.add_note(f"retained file close failure: {type(cleanup).__name__}")
            except BaseException:
                pass


def resync_retained_record(record: RetainedRecord) -> None:
    _sync_file(record.path, record.file_identity)
    _sync_directory(record.root)
    _sync_directory(record.root.parent)


def install_terminal_accepted(record: RetainedRecord, *, now: int) -> None:
    """Backup, fsync, atomically install, and fsync one terminal mark."""
    backup = record.root / BACKUP_NAME
    if not os.path.lexists(backup):
        _write_exact(backup, record.raw)
    old, identity = _read_file(backup)
    if old != record.raw:
        raise RetainedRecordError("backup-conflict")
    _sync_file(backup, identity)
    _sync_directory(record.root)
    payload = dict(record.payload)
    payload["retention_class"] = TERMINAL_ACCEPTED
    payload["expires_at_epoch"] = int(now) + 24 * 60 * 60
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    temporary = record.root / f".{RECORD_NAME}.{secrets.token_hex(8)}.tmp"
    installed = False
    temporary_identity: tuple[int, int, int] | None = None
    try:
        temporary_identity = _write_exact(temporary, encoded)
        os.replace(temporary, record.path)
        installed = True
        _sync_directory(record.root)
        _sync_directory(record.root.parent)
    except BaseException as error:
        try:
            if temporary_identity is not None and temporary.exists():
                current = temporary.lstat()
                if (
                    (current.st_dev, current.st_ino, current.st_uid) != temporary_identity
                    or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                ):
                    raise OSError("new metadata temporary changed before cleanup")
                temporary.unlink()
        except BaseException as cleanup:
            try:
                error.add_note(f"retained metadata temporary cleanup failure: {type(cleanup).__name__}")
            except BaseException:
                pass
        if not isinstance(error, Exception):
            raise
        if installed:
            raise MetadataInstallError(post_install=True) from error
        raise MetadataInstallError(post_install=False) from error


__all__ = (
    "BACKUP_NAME",
    "MetadataInstallError",
    "RECONCILIATION",
    "RetainedRecord",
    "RetainedRecordError",
    "TERMINAL_ACCEPTED",
    "TERMINAL_FAILED",
    "install_terminal_accepted",
    "read_retained_record",
    "resync_retained_record",
    "same_record",
)
