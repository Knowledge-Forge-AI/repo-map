"""Bounded, path-safe extraction for explicit sandbox report exports."""

from __future__ import annotations

import io
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile


def write_sandbox_diagnostic(message: str) -> None:
    """Keep a broken evidence channel from replacing admission or cleanup."""
    try:
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        try:
            print(
                "integration sandbox diagnostic write failed: stderr_unavailable\n"
                + message,
                file=sys.stdout,
                flush=True,
            )
        except (OSError, ValueError):
            # Neither inherited channel is writable; preserve the primary outcome.
            pass


def _report_members(
    archive: bytes,
    *,
    max_members: int,
    max_content_bytes: int,
) -> tuple[tarfile.TarFile, list[tuple[tarfile.TarInfo, PurePosixPath]]]:
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except (tarfile.TarError, OSError) as error:
        raise RuntimeError("integration sandbox report archive is malformed") from error
    members: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
    names: set[PurePosixPath] = set()
    total_size = 0
    try:
        for member in tar.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if name in {"", "."}:
                continue
            raw_parts = name.split("/")
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or any(part in {"", ".", ".."} for part in raw_parts)
                or len(name) > 4096
            ):
                raise RuntimeError("integration sandbox report archive contains unsafe path")
            if not (member.isdir() or member.isreg()):
                raise RuntimeError(
                    "integration sandbox report archive contains unsafe file type"
                )
            if path in names:
                raise RuntimeError(
                    "integration sandbox report archive contains duplicate path"
                )
            names.add(path)
            total_size += member.size
            if len(names) > max_members or total_size > max_content_bytes:
                raise RuntimeError(
                    "integration sandbox report archive exceeds bounded limits"
                )
            members.append((member, path))
    except BaseException:
        tar.close()
        raise
    return tar, members


def export_sandbox_report(
    archive: bytes,
    destination: Path,
    *,
    max_members: int,
    max_content_bytes: int,
) -> None:
    tar, members = _report_members(
        archive,
        max_members=max_members,
        max_content_bytes=max_content_bytes,
    )
    created_destination = False
    try:
        if destination.exists() or destination.is_symlink():
            raise RuntimeError("integration sandbox report destination already exists")
        for ancestor in (destination.parent, *destination.parent.parents):
            if ancestor.exists() and ancestor.is_symlink():
                raise RuntimeError(
                    "integration sandbox report destination has symlink ancestor"
                )
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.mkdir(mode=0o700)
        created_destination = True
        for member, relative in members:
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o750, parents=True, exist_ok=True)
                target.chmod(0o750)
                continue
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                raise RuntimeError("integration sandbox report member is unavailable")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, "wb") as output:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise RuntimeError(
                            "integration sandbox report member is truncated"
                        )
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise RuntimeError(
                        "integration sandbox report member exceeds declared size"
                    )
            target.chmod(0o640)
        destination.chmod(0o750)
        created_destination = False
    except OSError as error:
        raise RuntimeError("integration sandbox report export failed") from error
    finally:
        tar.close()
        if created_destination:
            shutil.rmtree(destination, ignore_errors=True)
