"""Receipt I/O custody for public-text allocation bookkeeping (study section 19.1).

This owner only serializes, seals, reads and exclusively writes small receipts
under a private 0700 root. It decides nothing about sequencing and grants no
native, model or study authority. A failed write is never repaired: the slot
stays spent and the caller sees a closed refusal.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LOCK_NAME = ".allocation.lock"
MAX_RECEIPT_BYTES = 64 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


class AllocationRefused(RuntimeError):
    """Closed custody or sequencing refusal; no automatic repair is attempted."""


def require_token(value: object, name: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise AllocationRefused(f"{name} is not a portable identity token")
    return value


def require_digest(value: object, name: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise AllocationRefused(f"{name} is not a lowercase sha256 digest")
    return value


def _ready(item: object) -> object:
    if item is None or type(item) in (str, bool, int):
        return item
    if isinstance(item, Mapping):
        if any(type(key) is not str for key in item):
            raise ValueError("receipt keys must be strings")
        return {key: _ready(value) for key, value in item.items()}
    if isinstance(item, (list, tuple)):
        return [_ready(value) for value in item]
    raise ValueError("receipt has an unsupported JSON value")


def canonical_receipt_bytes(value: object) -> bytes:
    """Sorted, ASCII, finite JSON plus one LF; floats are not receipt values."""
    try:
        text = json.dumps(_ready(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("receipt is not finite canonical JSON") from error
    return text.encode("ascii") + b"\n"


def receipt_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def seal_receipt(payload: Mapping[str, object]) -> bytes:
    """Bind ``receipt_sha256`` over the canonical body without that field."""
    body = dict(payload)
    body.pop("receipt_sha256", None)
    body["receipt_sha256"] = receipt_digest(canonical_receipt_bytes(body))
    return canonical_receipt_bytes(body)


def _file_custody(path: Path) -> os.stat_result:
    try:
        details = os.lstat(path)
    except FileNotFoundError as error:
        raise AllocationRefused(f"missing allocation file: {path.name}") from error
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o600):
        raise AllocationRefused(f"unsafe allocation file custody: {path.name}")
    return details


def _checked_root(root: Path | str, *, create: bool, allowed: frozenset[str]) -> Path:
    path = Path(root)
    if not path.is_absolute() or path.is_symlink():
        raise AllocationRefused("allocation root must be an absolute non-symlink directory")
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        if not create:
            raise AllocationRefused("allocation root does not exist") from None
        try:
            path.mkdir(mode=0o700, exist_ok=False)
        except OSError as error:
            raise AllocationRefused("allocation root cannot be created") from error
        details = os.lstat(path)
    if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700):
        raise AllocationRefused("allocation root custody is unsafe")
    for child in path.iterdir():
        if child.name == LOCK_NAME:
            continue
        if child.name not in allowed:
            raise AllocationRefused(f"unknown allocation file: {child.name}")
        _file_custody(child)
    return path


@contextmanager
def locked_root(root: Path | str, *, create: bool, allowed: frozenset[str]) -> Iterator[Path]:
    """Hold an exclusive no-follow lock on a verified root for one transition."""
    if not _NOFOLLOW:
        raise AllocationRefused("O_NOFOLLOW is required for allocation custody")
    path = _checked_root(root, create=create, allowed=allowed)
    try:
        descriptor = os.open(str(path / LOCK_NAME), os.O_RDWR | os.O_CREAT | _NOFOLLOW | _CLOEXEC, 0o600)
    except OSError as error:
        raise AllocationRefused("allocation lock cannot be opened") from error
    try:
        _file_custody(path / LOCK_NAME)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield _checked_root(path, create=False, allowed=allowed)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _identity(details: os.stat_result) -> tuple[int, int, int, int]:
    return (details.st_dev, details.st_ino, details.st_uid, details.st_size)


def _read_bytes(path: Path) -> bytes:
    before = _file_custody(path)
    try:
        descriptor = os.open(str(path), os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
    except OSError as error:
        raise AllocationRefused(f"allocation file cannot be opened: {path.name}") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise AllocationRefused(f"allocation file changed during read: {path.name}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(8192, MAX_RECEIPT_BYTES - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RECEIPT_BYTES:
                raise AllocationRefused("allocation receipt exceeds bounded size")
        after = os.fstat(descriptor)
        if _identity(after) != _identity(before) or stat.S_IMODE(after.st_mode) != 0o600:
            raise AllocationRefused(f"allocation file changed during read: {path.name}")
        return b"".join(chunks)
    except OSError as error:
        raise AllocationRefused(f"allocation file read failed: {path.name}") from error
    finally:
        os.close(descriptor)


def read_receipt(root: Path, name: str) -> dict[str, object] | None:
    """Return the canonical sealed receipt, ``None`` if absent; torn bytes refuse."""
    path = root / name
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    raw = _read_bytes(path)
    try:
        record = json.loads(raw.decode("ascii"))
        if type(record) is not dict or canonical_receipt_bytes(record) != raw:
            raise ValueError("non-canonical receipt")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AllocationRefused(f"allocation receipt is torn or non-canonical: {name}") from error
    body = dict(record)
    stored = body.pop("receipt_sha256", None)
    if stored != receipt_digest(canonical_receipt_bytes(body)):
        raise AllocationRefused(f"allocation receipt digest mismatch: {name}")
    return record


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short receipt write")
        view = view[written:]


def write_receipt(root: Path, name: str, payload: Mapping[str, object]) -> dict[str, object]:
    """Exclusive create, fsync file and directory; any failure leaves the name spent."""
    data = seal_receipt(payload)
    if len(data) > MAX_RECEIPT_BYTES:
        raise AllocationRefused("allocation receipt exceeds bounded size")
    try:
        descriptor = os.open(str(root / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600)
    except OSError as error:
        raise AllocationRefused(f"receipt already exists or cannot be created: {name}") from error
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except OSError as error:
        raise AllocationRefused(f"receipt write failed and remains spent: {name}") from error
    finally:
        os.close(descriptor)
    try:
        directory = os.open(str(root), os.O_RDONLY | _DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise AllocationRefused(f"receipt directory sync failed and remains spent: {name}") from error
    return json.loads(data.decode("ascii"))


__all__ = [
    "AllocationRefused", "LOCK_NAME", "MAX_RECEIPT_BYTES", "canonical_receipt_bytes", "locked_root",
    "read_receipt", "receipt_digest", "require_digest", "require_token", "seal_receipt", "write_receipt",
]
