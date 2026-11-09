"""Real-bundle negatives (section 9.3): mutate only a separate copy, then re-check.

Each mutation copies an accepted bundle into a distinct pytest directory and
changes exactly one thing. Re-encoded records go through the strict codecs and,
where the contract says "index updated", the copy's index is rebuilt so that
the targeted category is reached rather than a digest mismatch.
"""

from __future__ import annotations

import os
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path

from first_use_workload_bundle import read_bundle
from first_use_workload_census import Census
from first_use_workload_domains import CONTROL_NAMES, INTENT_NAME
from first_use_workload_integrity import member_rows, sha256_hex
from first_use_workload_reconcile import check_bundle
from first_use_workload_records import (
    decode_index, decode_intent, decode_observation, encode_index, encode_intent,
    encode_observation, index_payload,
)

Mutation = Callable[[Path], None]


def copy_bundle(bundle: Path, destination_parent: Path) -> Path:
    """A separate copy; the accepted original is never touched."""
    destination_parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    target = destination_parent / bundle.name
    shutil.copytree(bundle, target, symlinks=True)
    return target


def _replace(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
    finally:
        os.close(descriptor)


def _rebuild_index(bundle: Path) -> None:
    files = read_bundle(bundle)
    index = decode_index(files["index.json"])
    payload = {name: data for name, data in files.items() if name not in CONTROL_NAMES}
    _replace(bundle / "index.json", encode_index(index_payload(
        index["scenario"], index["attempt"], sha256_hex(files[INTENT_NAME]), member_rows(payload),
    )))


def flip_byte(name: str = "observation-01-0.json") -> Mutation:
    def mutate(bundle: Path) -> None:
        path = bundle / name
        data = bytearray(path.read_bytes())
        position = len(data) // 2
        data[position] ^= 0x01
        _replace(path, bytes(data))

    return mutate


def drop_member(name: str = "observation-02-0.json") -> Mutation:
    def mutate(bundle: Path) -> None:
        (bundle / name).unlink()

    return mutate


def reencode_observation(name: str, **changes: object) -> Mutation:
    """Canonically re-encode one observation with changed fields; index updated."""
    def mutate(bundle: Path) -> None:
        path = bundle / name
        payload = decode_observation(path.read_bytes())
        payload.update(changes)
        _replace(path, encode_observation(payload))
        _rebuild_index(bundle)

    return mutate


def other_attempt() -> str:
    return secrets.token_hex(16)


def reencode_intent(field: str) -> Mutation:
    """An intent whose identity field names a different candidate; index updated."""
    def mutate(bundle: Path) -> None:
        path = bundle / INTENT_NAME
        payload = decode_intent(path.read_bytes())
        payload[field] = sha256_hex(str(payload[field]).encode("ascii") + b"-mutated")
        _replace(path, encode_intent(payload))
        _rebuild_index(bundle)

    return mutate


def mutated_categories(
    bundle: Path, scratch: Path, mutation: Mutation, current_intent: bytes, census: Census,
) -> tuple[str, ...]:
    """Copy, mutate the copy only, and return the recomputed check categories."""
    copy = copy_bundle(bundle, scratch)
    mutation(copy)
    return check_bundle(current_intent, read_bundle(copy), census).categories


__all__ = [
    "Mutation", "copy_bundle", "drop_member", "flip_byte", "mutated_categories", "other_attempt",
    "reencode_intent", "reencode_observation",
]
