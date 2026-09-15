"""Canonical dependency-runtime image identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


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
