"""Strict in-memory wheel verification and the expected install tree (spec 2.2).

A wheel is admitted only when its size and SHA-256 match the lock, every
archive member is an exact locked regular file with an admitted compression,
and ``RECORD`` lists every other member with its exact digest and length and
itself with empty fields. Nothing is extracted to disk and nothing is
imported. The guest setup writer repeats these rules independently.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import stat
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.component_lock import (
    MAX_ARCHIVE_UNCOMPRESSED,
    MemberLock,
    WheelLock,
    canonical_json,
)

ADMITTED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
SITE_DIR = "site"
HELPER_DIR = "helper"
NOTICE_DIR = "notices"
HELPER_NAME = "parse_helper.py"
DIRECTORY_MODE = 0o555
FILE_MODE = 0o444
EXTENSION_MODE = 0o555
ZIP_DIRECTORY_MODE = 0o755


class ArchiveRefused(ContractError):
    """Categorical archive refusal; the message is the closed code only."""


@dataclass(frozen=True)
class VerifiedWheel:
    """Locked wheel bytes plus its verified members, in archive order."""

    lock: WheelLock
    data: bytes
    members: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class ExpectedEntry:
    """One path under the runtime root as the parent itself expects it."""

    path: str
    kind: str
    mode: int
    data: bytes | None


def require_member_name(name: str) -> str:
    """Refuse absolute, traversing, backslashed, empty or directory names."""

    if (not name or "\\" in name or "\x00" in name or name.startswith("/")
            or name.endswith("/")):
        raise ArchiveRefused("unsafe_member_name")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise ArchiveRefused("unsafe_member_name")
    return name


def require_directory_name(name: str) -> str:
    """Refuse traversal and non-canonical explicit directory names."""

    if type(name) is not str or not name.endswith("/"):
        raise ArchiveRefused("unsafe_member_name")
    require_member_name(name[:-1])
    return name


def _required_directory_names(names: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for name in names:
        parts = name.split("/")[:-1]
        directories.update("/".join(parts[:index]) + "/"
                           for index in range(1, len(parts) + 1))
    return directories


def record_hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + digest.decode("ascii")


def _classify_unexpected(name: str, dist_info: str, top_level: Sequence[str]) -> str:
    base = name.rsplit("/", 1)[-1]
    head = name.split("/", 1)[0]
    if base.endswith(".pth"):
        return "pth_member"
    if base == "entry_points.txt":
        return "entry_points_member"
    if head.endswith(".data"):
        return "data_directory_member"
    if head.endswith(".dist-info") and head != dist_info:
        return "conflicting_distribution"
    if head not in top_level:
        return "unexpected_top_level"
    return "member_set_mismatch"


def _check_info(info: zipfile.ZipInfo) -> None:
    if info.filename.endswith("/"):
        require_directory_name(info.filename)
        if info.flag_bits & 0x1:
            raise ArchiveRefused("encrypted_member")
        if info.compress_type not in ADMITTED_COMPRESSION:
            raise ArchiveRefused("compression_refused")
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFLNK:
            raise ArchiveRefused("symlink_member")
        if kind != stat.S_IFDIR or stat.S_IMODE(mode) != ZIP_DIRECTORY_MODE:
            raise ArchiveRefused("directory_mode_mismatch")
        if info.file_size != 0:
            raise ArchiveRefused("directory_payload")
        return
    require_member_name(info.filename)
    if info.flag_bits & 0x1:
        raise ArchiveRefused("encrypted_member")
    if info.compress_type not in ADMITTED_COMPRESSION:
        raise ArchiveRefused("compression_refused")
    mode = info.external_attr >> 16
    if mode and stat.S_IFMT(mode) != stat.S_IFREG:
        raise ArchiveRefused("special_member" if not stat.S_ISLNK(mode) else "symlink_member")


def verify_archive(data: bytes, *, size: int, sha256: str, dist_info: str,
                   top_level: Sequence[str], members: Sequence[MemberLock]) -> tuple[tuple[str, bytes], ...]:
    """Verify one archive against an explicit closed member list."""

    if type(data) is not bytes or len(data) != size:
        raise ArchiveRefused("artifact_size_mismatch")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ArchiveRefused("artifact_digest_mismatch")
    expected = {item.name: item for item in members}
    expected_directories = _required_directory_names(expected)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ArchiveRefused("invalid_archive") from None
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ArchiveRefused("duplicate_member")
        regular_infos: list[zipfile.ZipInfo] = []
        for info in infos:
            _check_info(info)
            if info.filename.endswith("/"):
                if info.filename[:-1] in expected:
                    raise ArchiveRefused("member_path_collision")
                if info.filename not in expected_directories:
                    raise ArchiveRefused("unexpected_directory")
                continue
            if info.filename not in expected:
                raise ArchiveRefused(_classify_unexpected(info.filename, dist_info, top_level))
            regular_infos.append(info)
        if {info.filename for info in regular_infos} != set(expected):
            raise ArchiveRefused("member_set_mismatch")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_UNCOMPRESSED:
            raise ArchiveRefused("archive_too_large")
        verified = tuple((info.filename, _read_member(archive, info, expected[info.filename]))
                         for info in regular_infos)
    _verify_record(dict(verified), f"{dist_info}/RECORD")
    return verified


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, lock: MemberLock) -> bytes:
    if stat.S_IMODE(info.external_attr >> 16) != lock.wheel_mode:
        raise ArchiveRefused("member_mode_mismatch")
    if info.file_size != lock.size:
        raise ArchiveRefused("member_size_mismatch")
    try:
        with archive.open(info) as handle:
            content = handle.read(lock.size + 1)
    except (zipfile.BadZipFile, ValueError, OSError, EOFError, RuntimeError):
        raise ArchiveRefused("invalid_archive") from None
    if len(content) != lock.size:
        raise ArchiveRefused("member_size_mismatch")
    if hashlib.sha256(content).hexdigest() != lock.sha256:
        raise ArchiveRefused("member_digest_mismatch")
    return content


def _verify_record(contents: dict[str, bytes], record_name: str) -> None:
    raw = contents.get(record_name)
    if raw is None:
        raise ArchiveRefused("record_missing")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error):
        raise ArchiveRefused("record_invalid") from None
    seen: set[str] = set()
    for row in rows:
        if len(row) != 3 or row[0] in seen:
            raise ArchiveRefused("record_invalid")
        name, digest, length = row
        seen.add(name)
        if name == record_name:
            if digest or length:
                raise ArchiveRefused("record_self_entry")
            continue
        content = contents.get(name)
        if content is None:
            raise ArchiveRefused("record_extra_entry")
        if digest != record_hash(content) or length != str(len(content)):
            raise ArchiveRefused("record_mismatch")
    if seen != set(contents):
        raise ArchiveRefused("record_incomplete")


def verify_wheel(data: bytes, wheel: WheelLock) -> VerifiedWheel:
    """Verify one locked wheel completely in memory."""

    members = verify_archive(data, size=wheel.size, sha256=wheel.sha256, dist_info=wheel.dist_info,
                             top_level=wheel.top_level, members=wheel.members)
    return VerifiedWheel(wheel, data, members)


def _parents(path: str) -> Iterable[str]:
    parts = path.split("/")[:-1]
    for index in range(1, len(parts) + 1):
        yield "/".join(parts[:index])


def expected_install_tree(member_sets: Sequence[Sequence[tuple[str, bytes]]], helper: bytes,
                          notices: Sequence[tuple[str, bytes]]) -> tuple[ExpectedEntry, ...]:
    """Return the sealed runtime tree the parent expects, sorted by path.

    The root is ``""``. Wheel members live under ``site/``; the helper and the
    supplemental notices are fixed names. Any path collision is refused.
    """

    files: dict[str, tuple[int, bytes]] = {}

    def add(path: str, mode: int, content: bytes) -> None:
        require_member_name(path)
        if path in files:
            raise ArchiveRefused("install_path_collision")
        files[path] = (mode, content)

    for members in member_sets:
        for name, content in members:
            mode = EXTENSION_MODE if name.endswith(".so") else FILE_MODE
            add(f"{SITE_DIR}/{require_member_name(name)}", mode, content)
    add(f"{HELPER_DIR}/{HELPER_NAME}", FILE_MODE, helper)
    for name, content in notices:
        add(f"{NOTICE_DIR}/{name}", FILE_MODE, content)
    directories = {"", SITE_DIR, HELPER_DIR, NOTICE_DIR}
    for path in files:
        directories.update(_parents(path))
    if directories & set(files):
        raise ArchiveRefused("install_path_collision")
    entries = [ExpectedEntry(path, "d", DIRECTORY_MODE, None) for path in directories]
    entries.extend(ExpectedEntry(path, "f", mode, content) for path, (mode, content) in files.items())
    return tuple(sorted(entries, key=lambda entry: entry.path))


def tree_digest(entries: Iterable[tuple[str, str, int, bytes | None]]) -> str:
    """Digest of (path, kind, mode, content) rows; owners/links are checked separately."""

    rows = [[path, kind, mode, None if data is None else hashlib.sha256(data).hexdigest(),
             None if data is None else len(data)] for path, kind, mode, data in entries]
    return hashlib.sha256(canonical_json(sorted(rows))).hexdigest()


def expected_tree_digest(entries: Sequence[ExpectedEntry]) -> str:
    return tree_digest((entry.path, entry.kind, entry.mode, entry.data) for entry in entries)
