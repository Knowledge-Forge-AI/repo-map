"""Member digests and the acyclic payload -> index -> verdict binding.

Payload members are the intent, observations, reports and plans. The index
lists every payload member and excludes itself and ``verdict.json``; the
verdict binds the final index bytes. Nothing here trusts a stored verdict.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from first_use_workload_domains import CONTROL_NAMES

MemberRow = list[Any]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def member_row(name: str, data: bytes) -> MemberRow:
    return [name, sha256_hex(data), len(data)]


def member_rows(files: Mapping[str, bytes]) -> list[MemberRow]:
    """Sorted index rows for every payload member; controls never appear."""
    return sorted(member_row(name, data) for name, data in files.items() if name not in CONTROL_NAMES)


def compare_index(index_rows: Sequence[Sequence[Any]], files: Mapping[str, bytes]) -> set[str]:
    """Categories for listed-missing, unlisted-present and digest-changed members."""
    categories: set[str] = set()
    listed = {str(row[0]): (row[1], row[2]) for row in index_rows}
    present = {name for name in files if name not in CONTROL_NAMES}
    if set(listed) - present:
        categories.add("partial_bundle")
    if present - set(listed):
        categories.add("tampered_member")
    for name in set(listed) & present:
        digest, size = listed[name]
        data = files[name]
        if (sha256_hex(data), len(data)) != (digest, size):
            categories.add("tampered_member")
    return categories


def referenced_members(observations: Sequence[Mapping[str, Any]]) -> dict[str, MemberRow]:
    """Report and plan rows referenced by observations, keyed by member name."""
    rows: dict[str, MemberRow] = {}
    for observation in observations:
        for row in observation.get("members", ()):
            rows[str(row[0])] = list(row)
    return rows


__all__ = ["compare_index", "member_row", "member_rows", "referenced_members", "sha256_hex"]
