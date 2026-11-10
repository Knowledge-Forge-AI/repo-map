"""Installed-experience storage adapter over the unchanged first-use bundle custody.

The exclusive ``BundleWriter`` and descriptor-anchored ``read_bundle`` of
``first_use_workload_bundle`` are reused unmodified. This adapter only nests an
owned ``installed-experience/<owner>/`` directory below the first-use base and
selects an existing storage scenario token (``local`` or ``server``), so the
layout is ``<base>/installed-experience/<owner>/<storage>-<attempt>/``. After the
unchanged reader admits the members, the installed codecs impose their tighter
member names and bounds. No first-use domain, codec, writer or reader changes.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from pathlib import Path

from first_use_workload_bundle import BundleWriter, read_bundle
from first_use_workload_domains import WorkloadError
from installed_experience_domains import (
    BUNDLE_PARENT, INDEX_NAME, INTENT_NAME, MAX_BUNDLE_BYTES, MAX_BUNDLE_FILES,
    OBSERVATION_NAME, OWNERS, STORAGE_SCENARIO, VERDICT_NAME, InstalledError,
)
from installed_experience_reconcile import Verdict, reconcile, sha256_hex
from installed_experience_records import encode_index, index_payload


def _owned_directory(path: Path) -> None:
    details = os.lstat(path)
    if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid()
            or details.st_mode & 0o022):
        raise InstalledError("unsafe-member")


def _owned_child(parent: Path, name: str) -> Path:
    _owned_directory(parent)
    child = parent / name
    try:
        os.mkdir(child, 0o700)
    except FileExistsError:
        pass
    _owned_directory(child)
    return child


def owner_base(first_use_base: Path, owner: str) -> Path:
    """``<first-use base>/installed-experience/<owner>``, owner-private, never a symlink."""
    if owner not in OWNERS:
        raise InstalledError("malformed")
    return _owned_child(_owned_child(first_use_base, BUNDLE_PARENT), owner)


def _payload_bound(intent: bytes, observations: Sequence[tuple[str, bytes]]) -> None:
    if len(observations) + 3 > MAX_BUNDLE_FILES:
        raise InstalledError("bound-exceeded")
    if len(intent) + sum(len(data) for _name, data in observations) > MAX_BUNDLE_BYTES:
        raise InstalledError("bound-exceeded")
    names = [name for name, _data in observations]
    if names != sorted(set(names)) or any(OBSERVATION_NAME.fullmatch(name) is None for name in names):
        raise InstalledError("order-violation")


def _validate_path(root: Path, files: dict[str, bytes]) -> None:
    """Bind owner/storage/attempt path tokens to any decodable members present."""
    from installed_experience_domains import HEX32
    from installed_experience_records import decode_index, decode_intent, decode_observation
    storage, separator, attempt = root.name.rpartition("-")
    path_owner = root.parent.name
    if (not separator or path_owner not in OWNERS
            or storage != STORAGE_SCENARIO[path_owner] or HEX32.fullmatch(attempt) is None):
        raise InstalledError("unsafe-member")
    owner: str | None = None
    bound_attempt: str | None = None
    raw_intent = files.get(INTENT_NAME)
    if raw_intent is not None:
        try:
            intent = decode_intent(raw_intent)
        except InstalledError:
            intent = None
        if intent is not None:
            owner = intent["owner"]
    raw_index = files.get(INDEX_NAME)
    if raw_index is not None:
        try:
            index = decode_index(raw_index)
        except InstalledError:
            index = None
        if index is not None:
            if owner is not None and index["owner"] != owner:
                raise InstalledError("unsafe-member")
            owner, bound_attempt = index["owner"], index["attempt"]
    for name in sorted(files):
        if OBSERVATION_NAME.fullmatch(name) is None:
            continue
        try:
            observation = decode_observation(files[name])
        except InstalledError:
            continue
        if owner is not None and observation["owner"] != owner:
            raise InstalledError("unsafe-member")
        if bound_attempt is not None and observation["attempt"] != bound_attempt:
            raise InstalledError("unsafe-member")
        owner, bound_attempt = observation["owner"], observation["attempt"]
    if owner is not None and (path_owner != owner or storage != STORAGE_SCENARIO[owner]):
        raise InstalledError("unsafe-member")
    if bound_attempt is not None and attempt != bound_attempt:
        raise InstalledError("unsafe-member")


def write_owner_bundle(
    base: Path, owner: str, attempt: str, intent: bytes,
    observations: Sequence[tuple[str, bytes]],
) -> tuple[Path, Verdict]:
    """Intent, observations, index, then the verdict reconciled from the written bytes."""
    _payload_bound(intent, observations)
    try:
        writer = BundleWriter(base, STORAGE_SCENARIO[owner], attempt)
        writer.write(INTENT_NAME, intent)
        for name, data in observations:
            writer.write(name, data)
        rows = [[name, sha256_hex(data), len(data)] for name, data in writer.written.items()]
        writer.write(INDEX_NAME, encode_index(index_payload(owner, attempt, sha256_hex(intent), rows)))
        verdict = reconcile(read_installed_bundle(writer.root))
        writer.write(VERDICT_NAME, verdict.encoded())
    except WorkloadError as error:
        raise InstalledError("bound-exceeded" if error.category in ("too_large", "unbounded")
                             else "unsafe-member") from None
    return writer.root, verdict


def read_installed_bundle(root: Path) -> dict[str, bytes]:
    """The unchanged bounded reader, then the installed member and size rules."""
    try:
        files = read_bundle(root)
    except WorkloadError as error:
        if error.category == "unreadable":
            raise InstalledError("unreadable") from None
        raise InstalledError("unsafe-member") from None
    allowed = {INTENT_NAME, INDEX_NAME, VERDICT_NAME}
    if any(name not in allowed and OBSERVATION_NAME.fullmatch(name) is None for name in files):
        raise InstalledError("unsafe-member")
    if len(files) > MAX_BUNDLE_FILES or sum(len(data) for data in files.values()) > MAX_BUNDLE_BYTES:
        raise InstalledError("bound-exceeded")
    _validate_path(root, files)
    return files


def bundle_bytes(root: Path) -> int:
    """Exact size of one written bundle, for the five-bundle export ceiling."""
    return sum(len(data) for data in read_installed_bundle(root).values())


__all__ = ["bundle_bytes", "owner_base", "read_installed_bundle", "write_owner_bundle"]
