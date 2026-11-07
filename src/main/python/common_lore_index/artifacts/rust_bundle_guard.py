"""Refuse Rust raw, canonical, evidence, or endpoint claims in worker bundles."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import IO, Any, TypeVar

RUST_CLAIM_REFUSAL = "Rust bundle claims require a live parent witness"
_FamilyKey = TypeVar("_FamilyKey")


def _rust(value: object) -> bool:
    return isinstance(value, str) and value.startswith("rust.")


def _check(family: object, row: Mapping[str, object]) -> None:
    if not isinstance(family, str):
        return  # The bounded stream parser owns malformed family-schema errors.
    fields = {
        "raw_observations": ("kind",),
        "canonical_nodes": ("kind", "canonical_key"),
        "canonical_edges": ("edge_kind", "source_canonical_key", "target_canonical_key"),
        "canonical_evidence": ("raw_kind",),
        "canonical_node_evidence": ("canonical_key",),
        "canonical_edge_evidence": ("source_canonical_key", "target_canonical_key"),
    }.get(family, ())
    if any(_rust(row.get(field)) for field in fields):
        raise ValueError(RUST_CLAIM_REFUSAL)


def reject_rust_claims(
    families: Mapping[_FamilyKey, Iterable[Mapping[str, object]]],
) -> None:
    for family, rows in families.items():
        for row in rows:
            _check(family, row)


class GuardedBundleStream:
    """One-pass frame observer; parser errors still belong to the stream parser."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream

    def readline(self, size: int = -1) -> bytes:
        line = self._stream.readline(size)
        if line:
            try:
                frame: Any = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                frame = None
            if isinstance(frame, Mapping) and frame.get("frame") == "record":
                row = frame.get("record")
                if isinstance(row, Mapping):
                    _check(frame.get("family"), row)
        return line

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


__all__ = ("GuardedBundleStream", "reject_rust_claims")
