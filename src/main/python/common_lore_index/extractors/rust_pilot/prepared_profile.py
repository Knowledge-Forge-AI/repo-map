"""Host-side prepared profile: the exact verified wheel pair for one CPU (spec 3).

``prepare_profile`` copies already acquired bytes from an operator-supplied
private directory and never downloads. ``load_profile`` verifies the frozen
profile at run start: exact listing, owner-only single-link regular entries,
canonical ``profile.json`` bytes, lock sizes and digests and the closed member
check. Any failure is :class:`ProfileUnavailable`, which the controller turns
into exactly one run-level ``dependency_unavailable`` outcome.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.extractors.contracts.bounded_io import (
    HARD_MAX_BYTES,
    BoundedIOError,
    open_directory,
    read_regular_file,
    write_new_regular_file,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.archive_verifier import (
    ArchiveRefused,
    VerifiedWheel,
    verify_wheel,
)
from common_lore_index.extractors.rust_pilot.component_lock import (
    CPUS,
    LOCK_ID,
    LOCK_SHA256,
    canonical_json,
    wheels_for_cpu,
)

PROFILE_SCHEMA = "cloe-rust-pilot-prepared-profile-v1"
PROFILE_NAME = "profile.json"


class ProfileUnavailable(ContractError):
    """The prepared profile is missing or inadmissible; the code is categorical."""


@dataclass(frozen=True)
class VerifiedProfile:
    """A profile the parent itself verified at run start."""

    cpu: str
    profile_sha256: str
    profile_bytes: bytes
    wheels: tuple[VerifiedWheel, VerifiedWheel]


def profile_document(cpu: str) -> dict[str, Any]:
    binding, grammar = wheels_for_cpu(cpu)
    return {"schema": PROFILE_SCHEMA, "cpu": cpu, "lock_id": LOCK_ID, "lock_sha256": LOCK_SHA256,
            "wheels": [{"filename": wheel.filename, "size": wheel.size, "sha256": wheel.sha256}
                       for wheel in (binding, grammar)]}


def profile_bytes(cpu: str) -> bytes:
    return canonical_json(profile_document(cpu)) + b"\n"


def _verified_pair(dir_fd: int, cpu: str) -> tuple[VerifiedWheel, VerifiedWheel]:
    binding, grammar = wheels_for_cpu(cpu)
    try:
        return (verify_wheel(read_regular_file(dir_fd, binding.filename, max_bytes=HARD_MAX_BYTES), binding),
                verify_wheel(read_regular_file(dir_fd, grammar.filename, max_bytes=HARD_MAX_BYTES), grammar))
    except (BoundedIOError, ArchiveRefused) as error:
        raise ProfileUnavailable(error.code) from None


def prepare_profile(source_dir: Path | str, profile_dir: Path | str, cpu: str) -> str:
    """Create a new profile directory from verified source bytes; return its digest."""

    if cpu not in CPUS:
        raise ProfileUnavailable("unknown_cpu")
    try:
        source_fd = open_directory(source_dir)
    except BoundedIOError as error:
        raise ProfileUnavailable(error.code) from None
    try:
        wheels = _verified_pair(source_fd, cpu)
    finally:
        os.close(source_fd)
    try:
        os.mkdir(os.fspath(profile_dir), 0o700)
        profile_fd = open_directory(profile_dir)
    except FileExistsError:
        raise ProfileUnavailable("profile_exists") from None
    except (OSError, BoundedIOError):
        raise ProfileUnavailable("profile_unwritable") from None
    try:
        for wheel in wheels:
            write_new_regular_file(profile_fd, wheel.lock.filename, wheel.data, max_bytes=HARD_MAX_BYTES)
        document = profile_bytes(cpu)
        write_new_regular_file(profile_fd, PROFILE_NAME, document, max_bytes=HARD_MAX_BYTES)
    except BoundedIOError as error:
        raise ProfileUnavailable(error.code) from None
    finally:
        os.close(profile_fd)
    return hashlib.sha256(document).hexdigest()


def _check_entries(dir_fd: int, expected: set[str]) -> None:
    if set(os.listdir(dir_fd)) != expected:
        raise ProfileUnavailable("profile_listing")
    for name in expected:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()):
            raise ProfileUnavailable("profile_entry_unsafe")


def load_profile(profile_dir: Path | str, *, server_cpu: str | None = None) -> VerifiedProfile:
    """Verify a frozen profile; ``server_cpu`` must match when supplied."""

    try:
        dir_fd = open_directory(profile_dir)
    except BoundedIOError as error:
        raise ProfileUnavailable("profile_missing" if error.code == "missing" else error.code) from None
    try:
        try:
            document = read_regular_file(dir_fd, PROFILE_NAME, max_bytes=16_384)
        except BoundedIOError as error:
            raise ProfileUnavailable("profile_json_" + error.code) from None
        cpu = next((value for value in CPUS if profile_bytes(value) == document), None)
        if cpu is None:
            raise ProfileUnavailable("profile_json_mismatch")
        if server_cpu is not None and server_cpu != cpu:
            raise ProfileUnavailable("wrong_platform")
        binding, grammar = wheels_for_cpu(cpu)
        _check_entries(dir_fd, {PROFILE_NAME, binding.filename, grammar.filename})
        wheels = _verified_pair(dir_fd, cpu)
    except OSError:
        raise ProfileUnavailable("profile_unreadable") from None
    finally:
        os.close(dir_fd)
    return VerifiedProfile(cpu, hashlib.sha256(document).hexdigest(), document, wheels)
