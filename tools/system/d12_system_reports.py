"""Pure stdlib bounded JSON report accounting and atomic file replacement for D12 system runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from tools.system.config import SystemTestError


def redact_public_text(text: str, *, repo_root: Path | None = None) -> str:
    cleaned = str(text).replace(str(repo_root), "<REPO_ROOT>") if repo_root is not None else str(text)
    return cleaned.replace("/Users/", "/<REDACTED_USER>/")


def encode_sorted_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_target(path: Path) -> Path:
    return path.parent.resolve() / path.name


def _deduplicate_targets(target_paths: Sequence[Path]) -> tuple[Path, ...]:
    seen_targets: set[Path] = set()
    unique: list[Path] = []
    for target in target_paths:
        canonical = _canonical_target(target)
        if canonical not in seen_targets:
            seen_targets.add(canonical)
            unique.append(target)
    return tuple(unique)


def existing_json_bytes(
    directories: Sequence[Path],
    *,
    exclude_paths: Sequence[Path] = (),
) -> int:
    excluded = frozenset(_canonical_target(path) for path in exclude_paths)
    seen_dirs: set[Path] = set()
    total = 0
    for directory in directories:
        resolved_dir = directory.resolve()
        if resolved_dir in seen_dirs or not directory.is_dir():
            continue
        seen_dirs.add(resolved_dir)
        for item in directory.glob("*.json"):
            if item.is_file() and (resolved_dir / item.name) not in excluded:
                total += item.stat().st_size
    return total


def verify_bounded_json_budget(
    raw: bytes,
    *,
    filename: str,
    directories: Sequence[Path],
    part_limit: int,
    total_limit: int,
    cleanup_reserve: int,
    is_cleanup: bool = False,
    target_paths: Sequence[Path] = (),
) -> int:
    if len(raw) > part_limit:
        raise ValueError(
            f"D12 report {filename} exceeds part limit ({len(raw)} > {part_limit})"
        )
    raw_targets = tuple(target_paths) if target_paths else tuple(d / filename for d in directories)
    unique_targets = _deduplicate_targets(raw_targets)
    all_dirs = [*directories, *(target.parent for target in unique_targets)]
    existing = existing_json_bytes(all_dirs, exclude_paths=unique_targets)
    copy_count = len(unique_targets) if unique_targets else 1
    projected = existing + (len(raw) * copy_count)
    reserve = 0 if is_cleanup else cleanup_reserve
    if projected + reserve > total_limit:
        raise ValueError(
            f"D12 report {filename} exceeds total report budget "
            f"({projected + reserve} > {total_limit})"
        )
    return projected


def write_json_bytes_atomic(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    closed = False
    try:
        os.write(fd, raw)
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_name, path)
    except BaseException:
        if not closed:
            os.close(fd)
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return hashlib.sha256(raw).hexdigest()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    return write_json_bytes_atomic(path, encode_sorted_json_bytes(payload))


def write_bounded_json_atomic(
    path: Path,
    payload: Mapping[str, Any],
    *,
    part_limit: int,
    total_limit: int,
    cleanup_reserve: int,
    is_cleanup: bool = False,
    account_dirs: Sequence[Path] = (),
) -> str:
    raw = encode_sorted_json_bytes(payload)
    dirs = [path.parent, *account_dirs]
    verify_bounded_json_budget(
        raw,
        filename=path.name,
        directories=dirs,
        part_limit=part_limit,
        total_limit=total_limit,
        cleanup_reserve=cleanup_reserve,
        is_cleanup=is_cleanup,
        target_paths=(path,),
    )
    return write_json_bytes_atomic(path, raw)


def write_bounded_json_to_targets(
    target_dirs: Sequence[Path],
    filename: str,
    payload: Mapping[str, Any],
    *,
    part_limit: int,
    total_limit: int,
    cleanup_reserve: int,
    is_cleanup: bool = False,
) -> Path | None:
    unique_targets = _deduplicate_targets([d / filename for d in target_dirs])
    if not unique_targets:
        return None
    raw = encode_sorted_json_bytes(payload)
    verify_bounded_json_budget(
        raw,
        filename=filename,
        directories=target_dirs,
        part_limit=part_limit,
        total_limit=total_limit,
        cleanup_reserve=cleanup_reserve,
        is_cleanup=is_cleanup,
        target_paths=unique_targets,
    )
    for out_file in unique_targets:
        write_json_bytes_atomic(out_file, raw)
    return unique_targets[0]


def write_exclusive_0600_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SystemTestError(f"one-use D12 system build intent already exists: {path}") from exc
    except OSError as exc:
        msg = "must not be a symlink" if exc.errno == errno.ELOOP else f"cannot create ({exc})"
        raise SystemTestError(f"D12 system build intent {msg}: {path}") from exc
    for t_fd, sync_only in ((fd, False), (os.open(path.parent, os.O_RDONLY), True)):
        try:
            if not sync_only:
                os.fchmod(t_fd, 0o600)
                os.write(t_fd, raw)
            os.fsync(t_fd)
        finally:
            os.close(t_fd)
    return hashlib.sha256(raw).hexdigest()
