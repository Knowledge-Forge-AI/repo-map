"""Canonical dependency-runtime image identity."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from repomap_test_support.resource_test_image_base import TestImageError


_PROHIBITED_FINGERPRINT_FIELDS = {
    "candidate_commit",
    "candidate_source_hash",
    "candidate_source_hashes",
    "candidate_source_sha256",
    "phase",
    "phase_name",
    "run_id",
    "timestamp",
    "wall_clock_time",
    "random",
}


def canonical_runtime_fingerprint(fields: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_runtime_json(fields).encode("utf-8")).hexdigest()


def canonical_runtime_json(fields: Mapping[str, Any]) -> str:
    identity = {
        key: value
        for key, value in fields.items()
        if key not in _PROHIBITED_FINGERPRINT_FIELDS
    }
    return json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


_EVIDENCE_RECORDS = 16


def _read_private_evidence(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise TestImageError("private runtime identity evidence is unsafe")
        existing = json.loads(os.read(descriptor, 1_000_000))
    finally:
        os.close(descriptor)
    if not isinstance(existing, dict):
        raise TestImageError("private runtime identity evidence is malformed")
    return existing


def write_private_runtime_evidence(
    resource_run: object, fingerprint: str, payload: Mapping[str, object]
) -> None:
    """Retain one runtime identity observation without silently dropping or merging another.

    Run-root names are bounded scratch categories (64 bytes), so a file names a
    16-hex fingerprint prefix. A record there for another full fingerprint or
    canonical identity is a truncated-name collision, and one that selected another
    image for the same identity conflicts; both refuse. A differing but consistent
    observation of the same identity (built, then reused) is retained beside it.
    """
    layout = getattr(resource_run, "layout", None)
    retain = getattr(resource_run, "retain_evidence", None)
    if layout is None or not callable(retain):
        return
    if payload.get("fingerprint") != fingerprint:
        raise TestImageError("runtime identity evidence names another fingerprint")
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    for ordinal in range(_EVIDENCE_RECORDS):
        suffix = f".{ordinal}" if ordinal else ""
        path = Path(layout.run_root) / f"test-runtime-{fingerprint[:16]}{suffix}.evidence.json"
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            existing = _read_private_evidence(path)
            if (existing.get("fingerprint"), existing.get("canonical_json")) != (
                fingerprint, payload.get("canonical_json")
            ):
                raise TestImageError("private runtime identity evidence name collides or conflicts") from None
            selected = (existing.get("selected_image_id"), payload.get("selected_image_id"))
            if all(selected) and selected[0] != selected[1]:
                raise TestImageError("private runtime identity evidence conflicts") from None
            if existing == json.loads(content):
                retain(path, reason="diagnostic_evidence")
                return
            continue
        try:
            os.write(descriptor, content.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        retain(path, reason="diagnostic_evidence")
        return
    raise TestImageError("private runtime identity evidence exceeds its record bound")
