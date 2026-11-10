"""Test-owned projection of the SDK's installed pure-Python dependency (section 5).

Only ``RECORD`` rows whose hashes verify are copied, from the sandbox
interpreter's purelib into a pure venv's purelib, through a private sibling
staging directory. Symlinks, hard links, foreign owners, unknown members, path
escapes, size or hash mismatches, missing license files and drift from the
reviewed frozen digests refuse with a closed code and leave the target unchanged.
This is preprovisioning, not vendoring, resolution or a fabricated wheel.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import os
import re
import secrets
import shutil
import stat
import sysconfig
import zipfile
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from installed_experience_pins import TE_MODULE_SHA256, TE_PROJECTION_SOURCE_CLASS, TE_RECORD_SHA256

RECORD_LIMIT = 64 * 1024
RECORD_ROWS = 64
_PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.]*)\Z")


class ProjectionRefused(Exception):
    """A closed projection refusal; the target is unchanged unless ``cleanup-failed``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProjectionRecord:
    name: str
    version: str
    member_count: int
    hashed_count: int
    bytecode_omitted: int
    license_count: int
    module_sha256: str
    record_sha256: str
    source_class: str = TE_PROJECTION_SOURCE_CLASS

    def as_payload(self) -> dict[str, Any]:
        return {"schema": "cloe-installed-experience-projection-v1", **asdict(self)}


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_from_wheel(wheel: Path, dist_info: str) -> tuple[str, str]:
    """The candidate's single unconditional ``Requires-Dist``; only an exact pin projects."""
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"{dist_info}/METADATA"))
    rows = [item.replace(" ", "") for item in metadata.get_all("Requires-Dist") or [] if ";" not in item]
    match = _PIN.fullmatch(rows[0]) if len(rows) == 1 else None
    if match is None:
        raise ProjectionRefused("projection-requirement-unsupported")
    return match.group(1), match.group(2)


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ProjectionRefused("projection-entry-unsafe") from None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ProjectionRefused("projection-entry-unsafe")
        if details.st_size > limit:
            raise ProjectionRefused("projection-record-unbounded")
        data = os.read(descriptor, limit + 1)
    finally:
        os.close(descriptor)
    if len(data) > limit:
        raise ProjectionRefused("projection-record-unbounded")
    return data


def _source_distribution(name: str, version: str, source: Path) -> importlib.metadata.Distribution:
    details = os.lstat(source)
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
            or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-source-missing")
    found = [item for item in importlib.metadata.distributions(path=[str(source)])
             if _normalized(item.metadata["Name"] or "") == _normalized(name)]
    if not found:
        raise ProjectionRefused("projection-source-missing")
    if len(found) > 1:
        raise ProjectionRefused("projection-source-ambiguous")
    if found[0].metadata["Version"] != version:
        raise ProjectionRefused("projection-source-missing")
    return found[0]


def _validate_source_directories(source: Path, dist_info: str) -> None:
    """Reject source-root and known intermediate directory links before metadata reads."""
    try:
        details = os.lstat(source)
    except OSError:
        raise ProjectionRefused("projection-source-missing") from None
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
            or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-source-missing")
    dist_path = source / dist_info
    try:
        details = os.lstat(dist_path)
    except FileNotFoundError:
        raise ProjectionRefused("projection-source-missing") from None
    except OSError:
        raise ProjectionRefused("projection-entry-unsafe") from None
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
            or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-entry-unsafe")
    licenses = dist_path / "licenses"
    try:
        details = os.lstat(licenses)
    except FileNotFoundError:
        return
    except OSError:
        raise ProjectionRefused("projection-entry-unsafe") from None
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
            or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-entry-unsafe")


def _classify_row(rel: str, module: str, dist_info: str) -> str:
    """``module``, ``meta``, ``license`` or ``bytecode``; anything else refuses."""
    path = PurePosixPath(rel)
    if (not rel or rel.startswith("/") or "\\" in rel or ".." in path.parts
            or str(path) != rel or rel.startswith("./")):
        raise ProjectionRefused("projection-path-escape")
    parts = path.parts
    if rel == f"{module}.py":
        return "module"
    if len(parts) == 2 and parts[0] == dist_info:
        return "meta"
    if len(parts) == 3 and parts[:2] == (dist_info, "licenses"):
        return "license"
    if len(parts) == 2 and parts[0] == "__pycache__" and re.fullmatch(
            re.escape(module) + r"\.[A-Za-z0-9_-]+(\.opt-[12])?\.pyc", parts[1]):
        return "bytecode"
    raise ProjectionRefused("projection-unknown-entry")


def _source_member(source: Path, rel: str) -> Path:
    """Resolve one source member only through owned, non-symlink directories."""
    path = PurePosixPath(rel)
    if (not path.parts or path.is_absolute() or "\\" in rel or ".." in path.parts
            or str(path) != rel):
        raise ProjectionRefused("projection-path-escape")
    try:
        details = os.lstat(source)
    except OSError:
        raise ProjectionRefused("projection-entry-unsafe") from None
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
            or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-entry-unsafe")
    current = source
    for part in path.parts[:-1]:
        current /= part
        try:
            details = os.lstat(current)
        except OSError:
            raise ProjectionRefused("projection-entry-unsafe") from None
        if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
                or details.st_uid not in (0, os.geteuid())):
            raise ProjectionRefused("projection-entry-unsafe")
    member = current / path.parts[-1]
    try:
        details = os.lstat(member)
    except OSError:
        raise ProjectionRefused("projection-entry-unsafe") from None
    if (stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1 or details.st_uid not in (0, os.geteuid())):
        raise ProjectionRefused("projection-entry-unsafe")
    return member


def _verify_member(source: Path, rel: str, recorded_hash: str, recorded_size: str) -> str:
    member = _source_member(source, rel)
    details = os.lstat(member)
    algorithm, _sep, value = recorded_hash.partition("=")
    if algorithm != "sha256" or recorded_size != str(details.st_size):
        raise ProjectionRefused("projection-hash-mismatch")
    body = _read_bounded(member, details.st_size)
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    if digest != value:
        raise ProjectionRefused("projection-hash-mismatch")
    return hashlib.sha256(body).hexdigest()


def target_listing(target: Path) -> str:
    """Digest of the target census (relative names, types and sizes), for unchanged proofs."""
    rows: list[str] = []
    for current, dirnames, filenames in os.walk(target, followlinks=False):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(current) / name
            details = os.lstat(path)
            rows.append(f"{path.relative_to(target).as_posix()}\0{stat.S_IFMT(details.st_mode)}\0"
                        f"{details.st_size if stat.S_ISREG(details.st_mode) else 0}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _copy_exclusive(source_root: Path, rel: str, destination: Path) -> str:
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    body = _read_bounded(_source_member(source_root, rel), 16 * 1024 * 1024)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        view = memoryview(body)
        while view:
            view = view[os.write(descriptor, view):]
    finally:
        os.close(descriptor)
    return hashlib.sha256(_read_bounded(destination, len(body))).hexdigest()


def _publish(staging: Path, target: Path, roots: list[str], before: str) -> None:
    published: list[tuple[Path, int]] = []
    try:
        for root in roots:
            os.rename(staging / root, target / root)
            published.append((target / root, os.lstat(target / root).st_ino))
    except BaseException:
        for path, inode in reversed(published):
            try:
                if os.lstat(path).st_ino != inode:
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError:
                pass
        if target_listing(target) != before:
            raise ProjectionRefused("projection-cleanup-failed") from None
        raise


def project_sdk_distribution(
    name: str,
    version: str,
    target_purelib: Path,
    *,
    source_purelib: Path | None = None,
    module_sha256: str = TE_MODULE_SHA256,
    record_sha256: str = TE_RECORD_SHA256,
) -> ProjectionRecord:
    """Verify, stage and publish one RECORD-bearing pure distribution; refuse otherwise."""
    source = Path(sysconfig.get_path("purelib")) if source_purelib is None else source_purelib
    module = name.replace("-", "_")
    dist_info = f"{module}-{version}.dist-info"
    _validate_source_directories(source, dist_info)
    distribution = _source_distribution(name, version, source)
    record_bytes = _read_bounded(_source_member(source, f"{dist_info}/RECORD"), RECORD_LIMIT)
    rows = [row for row in csv.reader(io.StringIO(record_bytes.decode("utf-8"))) if row]
    if len(rows) > RECORD_ROWS or any(len(row) != 3 for row in rows):
        raise ProjectionRefused("projection-record-unbounded")
    kinds = {row[0]: _classify_row(row[0], module, dist_info) for row in rows}
    copied: list[str] = []
    frozen_digests: dict[str, str] = {}
    for rel, recorded_hash, recorded_size in rows:
        if kinds[rel] == "bytecode":
            continue
        if rel == f"{dist_info}/RECORD":
            copied.append(rel)
            frozen_digests[rel] = hashlib.sha256(record_bytes).hexdigest()
            continue
        if not recorded_hash:
            raise ProjectionRefused("projection-hash-mismatch")
        frozen_digests[rel] = _verify_member(source, rel, recorded_hash, recorded_size)
        copied.append(rel)
    hashed = {rel for rel, recorded_hash, _size in rows if recorded_hash}
    licenses = distribution.metadata.get_all("License-File") or []
    if not licenses or any(f"{dist_info}/licenses/{item}" not in hashed
                           and f"{dist_info}/{item}" not in hashed for item in licenses):
        raise ProjectionRefused("projection-license-missing")
    module_bytes = _read_bounded(_source_member(source, f"{module}.py"), 16 * 1024 * 1024)
    if (hashlib.sha256(module_bytes).hexdigest() != module_sha256
            or hashlib.sha256(record_bytes).hexdigest() != record_sha256):
        raise ProjectionRefused("projection-drift")
    if os.path.lexists(target_purelib / f"{module}.py") or os.path.lexists(target_purelib / dist_info):
        raise ProjectionRefused("projection-target-occupied")
    before = target_listing(target_purelib)
    staging = target_purelib.parent / f".projection-{secrets.token_hex(8)}"
    os.mkdir(staging, 0o700)
    try:
        for rel in copied:
            if _copy_exclusive(source, rel, staging / rel) != frozen_digests[rel]:
                raise ProjectionRefused("projection-hash-mismatch")
        _publish(staging, target_purelib, [f"{module}.py", dist_info], before)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return ProjectionRecord(
        name=name, version=version, member_count=len(rows), hashed_count=len(hashed),
        bytecode_omitted=sum(kind == "bytecode" for kind in kinds.values()),
        license_count=len(licenses), module_sha256=module_sha256, record_sha256=record_sha256)


def copy_source_distribution(name: str, version: str, scratch: Path) -> Path:
    """A disposable scratch copy of the SDK distribution for the A07 adverse cases."""
    source = Path(sysconfig.get_path("purelib"))
    module = name.replace("-", "_")
    scratch.mkdir(mode=0o700, parents=True)
    shutil.copyfile(source / f"{module}.py", scratch / f"{module}.py")
    shutil.copytree(source / f"{module}-{version}.dist-info", scratch / f"{module}-{version}.dist-info",
                    symlinks=True)
    return scratch


__all__ = [
    "ProjectionRecord", "ProjectionRefused", "copy_source_distribution", "project_sdk_distribution",
    "requirement_from_wheel", "target_listing",
]
