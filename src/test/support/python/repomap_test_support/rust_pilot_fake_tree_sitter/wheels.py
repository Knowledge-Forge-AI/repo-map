"""Synthetic wheels, frames and root-substituted guest text for T1 owners.

Everything here is public synthetic data. Synthetic wheels follow the locked
archive rules but are not the pinned artifacts; tests that use them prove
parent and guest logic only.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Any

from common_lore_index.extractors.rust_pilot.archive_verifier import record_hash
from common_lore_index.extractors.rust_pilot.component_lock import ElfFacts, MemberLock, WheelLock

GUEST_PACKAGE = "common_lore_index.extractors.rust_pilot.guest"
ROOT_LINE = 'RUNTIME_ROOT = "/opt/repomap-rust"'
SCRATCH_LINE = 'SCRATCH = "/scratch"'
NOTICES = (("tree-sitter-core-LICENSE", b"core notice\n"), ("tree-sitter-unicode-LICENSE", b"unicode notice\n"))


@dataclass(frozen=True)
class SyntheticWheel:
    lock: WheelLock
    data: bytes


def build_wheel(files: Mapping[str, bytes], dist_info: str, *, extra: Mapping[str, bytes] | None = None,
                record_rows: list[str] | None = None, mode: int = 0o100644,
                compression: int = zipfile.ZIP_DEFLATED) -> tuple[bytes, dict[str, bytes]]:
    """Write ``files`` plus a RECORD; ``extra`` members are added after RECORD."""

    record_name = f"{dist_info}/RECORD"
    rows = record_rows if record_rows is not None else [
        f"{name},{record_hash(data)},{len(data)}" for name, data in files.items()] + [f"{record_name},,"]
    contents = {**files, record_name: ("\n".join(rows) + "\n").encode("utf-8")}
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in [*contents.items(), *(extra or {}).items()]:
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 5, 0, 0, 0))
            info.external_attr = mode << 16
            info.compress_type = compression
            archive.writestr(info, data)
    return buffer.getvalue(), contents


def synthetic_wheel(package: str, files: Mapping[str, bytes], *, cpu: str = "aarch64",
                    top_level: tuple[str, ...] | None = None) -> SyntheticWheel:
    dist_info = f"{package}-1.0.dist-info"
    data, contents = build_wheel(files, dist_info)
    members = tuple(MemberLock(name, len(blob), hashlib.sha256(blob).hexdigest(), 0o644)
                    for name, blob in contents.items())
    head = next(iter(files)).split("/", 1)[0]
    lock = WheelLock(package, "1.0", cpu, f"{package}-1.0-py3-none-any.whl", "https://example.invalid/w",
                     len(data), hashlib.sha256(data).hexdigest(), dist_info, top_level or (head, dist_info),
                     f"{head}/_binding.so", ElfFacts(183, ("libc.so.6",), ("GLIBC_2.17",)), members)
    return SyntheticWheel(lock, data)


def stand_in_wheels() -> tuple[SyntheticWheel, SyntheticWheel]:
    """Two synthetic wheels carrying the stdlib stand-in packages."""

    root = Path(__file__).resolve().parent
    binding = {f"tree_sitter/{name}": (root / "tree_sitter" / name).read_bytes()
               for name in ("__init__.py", "_grammar.py", "_lexer.py")}
    grammar = {"tree_sitter_rust/__init__.py": (root / "tree_sitter_rust" / "__init__.py").read_bytes()}
    return synthetic_wheel("tree_sitter", binding), synthetic_wheel("tree_sitter_rust", grammar)


def payload(wheel: SyntheticWheel) -> tuple[str, bytes, str, tuple[str, ...], list[tuple[str, int, str, int]]]:
    lock = wheel.lock
    return (lock.filename, wheel.data, lock.dist_info, lock.top_level,
            [(item.name, item.size, item.sha256, item.wheel_mode) for item in lock.members])


def guest_text(name: str, runtime_root: Path, scratch: Path | None = None) -> bytes:
    """Guest source with its fixed root constant replaced exactly once (tests only)."""

    source = resources.files(GUEST_PACKAGE).joinpath(name).read_text(encoding="ascii")
    if source.count(ROOT_LINE) != 1:
        raise AssertionError("guest root constant drifted")
    source = source.replace(ROOT_LINE, f"RUNTIME_ROOT = {str(runtime_root)!r}")
    if scratch is not None and SCRATCH_LINE in source:
        source = source.replace(SCRATCH_LINE, f"SCRATCH = {str(scratch)!r}")
    return source.encode("ascii")


def frame(kind: str, **fields: Any) -> bytes:
    return json.dumps({"t": kind, **fields}, separators=(",", ":")).encode("ascii") + b"\n"


def item_frame(i: int, p: int, k: int, s: int, e: int, *, n: list[int] | None = None,
               a: list[list[int]] | None = None, v: list[int] | None = None, y: list[int] | None = None,
               r: list[int] | None = None, f: int = 0) -> bytes:
    return frame("n", i=i, p=p, k=k, s=s, e=e, n=n, a=a or [], v=v, y=y, r=r, f=f)


def frames(nonce: str, body: list[bytes], *, root_error: int = 0, errors: int = 0, missing: int = 0,
           truncated: int = 0) -> bytes:
    items = sum(1 for line in body if line.startswith(b'{"t":"n"'))
    unsupported = sum(1 for line in body if line.startswith(b'{"t":"u"'))
    return (frame("hello", v=1, nonce=nonce, ts="0.26.0", abi=15) + b"".join(body)
            + frame("end", nonce=nonce, root_error=root_error, errors=errors, missing=missing, items=items,
                    unsupported=unsupported, truncated=truncated))
