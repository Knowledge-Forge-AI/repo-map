"""Frozen ``cloe-first-use-census-v1`` codec, projections and fixture digest.

The census is the committed freeze of the materialized mixed-v1 generations.
This module validates it strictly, recomputes its alias projections from its
own entries, and recomputes the committed-fixture digest from the four alias
trees plus ``python-sources-v1.json`` only. It never parses task, gold,
held-out or trial material and never imports test support; the working-copy
generator stays support-owned.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.ops.resource_view._canonical import CanonicalBoundError, canonical_bytes
from first_use_workload_domains import (
    ALIASES, MAX_CENSUS_BYTES, MAX_CENSUS_ENTRIES, MAX_REL_BYTES, PREFIXED_SHA256,
    SCHEMA_CENSUS, WorkloadError,
)
from first_use_workload_encoding import closed, decode_record, is_count, is_hex64, require

REPO_ROOT = Path(__file__).resolve().parents[1]
CENSUS_RELATIVE = Path("src/test/fixtures/first_use_workload/mixed-v1-census-v1.json")
FIXTURE_RELATIVE = Path("src/test/fixtures/retrieval_evaluation/mixed-v1")
PYTHON_SOURCES = "python-sources-v1.json"
EXCLUDED_TOP = ("companion", "excluded_cache")
PROJECTION_ALIAS_SETS: tuple[tuple[str, ...], ...] = (ALIASES, ("core", "companion"))
GENERATIONS = (1, 2)

Entry = tuple[str, str, str, int, bool]
Row = list[Any]


@dataclass(frozen=True)
class Projection:
    aliases: tuple[str, ...]
    S: int
    C: int
    files: int


@dataclass(frozen=True)
class Generation:
    generation: int
    entries: tuple[Entry, ...]
    bytes_total: int
    projections: tuple[Projection, ...]

    def projection(self, aliases: Sequence[str]) -> Projection:
        return project(self.entries, aliases)


@dataclass(frozen=True)
class Census:
    fixture_digest: str
    generations: tuple[Generation, ...]
    digest: str

    def generation(self, number: int) -> Generation:
        for item in self.generations:
            if item.generation == number:
                return item
        raise WorkloadError("invalid_domain")


def valid_relative(rel: object) -> bool:
    """A POSIX relative path of at most 255 UTF-8 bytes without traversal."""
    if type(rel) is not str or not rel or rel.startswith("/") or "\\" in rel:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in rel):
        return False
    if len(rel.encode("utf-8", "surrogatepass")) > MAX_REL_BYTES:
        return False
    return all(part not in {"", ".", ".."} for part in rel.split("/"))


def is_selected(alias: str, rel: str) -> bool:
    """The one fixture exclusion: companion's ``excluded_cache`` subtree."""
    return (alias, rel.split("/", 1)[0]) != EXCLUDED_TOP


def selected_rows(entries: Sequence[Entry], aliases: Sequence[str]) -> list[Row]:
    return sorted(
        [alias, rel, digest, size]
        for alias, rel, digest, size, selected in entries
        if selected and alias in aliases
    )


def project(entries: Sequence[Entry], aliases: Sequence[str]) -> Projection:
    """``S`` counts equal digests; ``C`` is ``S`` minus one size per unique digest."""
    rows = selected_rows(entries, aliases)
    total = sum(row[3] for row in rows)
    unique = {row[2]: row[3] for row in rows}
    return Projection(tuple(aliases), total, total - sum(unique.values()), len(rows))


def inventory_digest(rows: Sequence[Sequence[Any]]) -> str:
    """SHA-256 of canonical sorted ``[alias, rel, digest, size]`` rows plus LF."""
    ordered = sorted(list(row) for row in rows)
    return hashlib.sha256(canonical_bytes(ordered, MAX_CENSUS_BYTES) + b"\n").hexdigest()


def _entry(raw: object) -> Entry:
    require(type(raw) is list and len(raw) == 5, "malformed")
    assert isinstance(raw, list)
    alias, rel, digest, size, selected = raw
    require(alias in ALIASES and valid_relative(rel))
    require(type(digest) is str and PREFIXED_SHA256.fullmatch(digest) is not None)
    require(is_count(size) and type(selected) is bool)
    require(selected is is_selected(alias, rel))
    return (alias, rel, digest, size, selected)


def _generation(raw: object, number: int) -> Generation:
    record = closed(raw, ("bytes_total", "entries", "generation", "projections"))
    require(record["generation"] == number and type(record["generation"]) is int)
    entries_raw = record["entries"]
    require(type(entries_raw) is list and 0 < len(entries_raw) <= MAX_CENSUS_ENTRIES)
    entries = tuple(_entry(item) for item in entries_raw)
    keys = [(alias, rel) for alias, rel, *_rest in entries]
    require(keys == sorted(set(keys)) and len(keys) == len(set(keys)))
    require(is_count(record["bytes_total"]))
    require(record["bytes_total"] == sum(item[3] for item in entries))
    raw_projections = record["projections"]
    require(type(raw_projections) is list and len(raw_projections) == len(PROJECTION_ALIAS_SETS))
    projections: list[Projection] = []
    for aliases, item in zip(PROJECTION_ALIAS_SETS, raw_projections, strict=True):
        stored = closed(item, ("C", "S", "aliases", "files"))
        require(stored["aliases"] == list(aliases))
        expected = project(entries, aliases)
        require((stored["S"], stored["C"], stored["files"]) == (expected.S, expected.C, expected.files))
        require(all(type(stored[key]) is int for key in ("S", "C", "files")))
        projections.append(expected)
    return Generation(number, entries, record["bytes_total"], tuple(projections))


def decode_census(data: bytes) -> Census:
    """Validate the committed census bytes; any deviation is ``stale_input``."""
    try:
        payload = decode_record(data, MAX_CENSUS_BYTES)
        record = closed(payload, ("fixture_digest", "generations", "schema"))
        require(record["schema"] == SCHEMA_CENSUS and is_hex64(record["fixture_digest"]))
        raw_generations = record["generations"]
        require(type(raw_generations) is list and len(raw_generations) == len(GENERATIONS))
        generations = tuple(
            _generation(item, number) for number, item in zip(GENERATIONS, raw_generations, strict=True)
        )
    except WorkloadError as error:
        if error.category == "too_large":
            raise
        raise WorkloadError("stale_input") from None
    return Census(record["fixture_digest"], generations, hashlib.sha256(data).hexdigest())


def read_bounded(path: Path, limit: int) -> bytes:
    """Read one regular, non-symlink file of at most ``limit`` bytes."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        category = "unsafe_input" if error.errno == errno.ELOOP else "unreadable"
        raise WorkloadError(category) from None
    failure: WorkloadError | None = None
    data: bytes | None = None
    try:
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise WorkloadError("unsafe_input")
            if details.st_size > limit:
                raise WorkloadError("too_large")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                data = handle.read(limit + 1)
        except WorkloadError as error:
            failure = error
        except OSError:
            failure = WorkloadError("unreadable")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if failure is None:
                failure = WorkloadError("unreadable")
    if failure is not None:
        raise failure from None
    assert data is not None
    if len(data) > limit:
        raise WorkloadError("too_large")
    return data


def load_census(repo_root: Path = REPO_ROOT) -> Census:
    return decode_census(read_bounded(repo_root / CENSUS_RELATIVE, MAX_CENSUS_BYTES))


def _fixture_file_rows(fixture_root: Path) -> list[Row]:
    def walk_error(_error: OSError) -> None:
        raise WorkloadError("unreadable") from None

    try:
        root_details = os.lstat(fixture_root)
    except OSError:
        raise WorkloadError("unreadable") from None
    if stat.S_ISLNK(root_details.st_mode) or not stat.S_ISDIR(root_details.st_mode):
        raise WorkloadError("unsafe_input")
    rows: list[Row] = []
    candidates = [fixture_root / PYTHON_SOURCES]
    entries = 1
    for alias in ALIASES:
        entries += 1
        alias_root = fixture_root / alias
        try:
            alias_details = os.lstat(alias_root)
        except OSError:
            raise WorkloadError("unreadable") from None
        if stat.S_ISLNK(alias_details.st_mode) or not stat.S_ISDIR(alias_details.st_mode):
            raise WorkloadError("unsafe_input")
        try:
            for current, dirnames, filenames in os.walk(
                alias_root, followlinks=False, onerror=walk_error
            ):
                entries += len(dirnames) + len(filenames)
                if entries > 2 * MAX_CENSUS_ENTRIES:
                    raise WorkloadError("too_large")
                dirnames.sort()
                for name in dirnames:
                    try:
                        details = os.lstat(Path(current) / name)
                    except OSError:
                        raise WorkloadError("unreadable") from None
                    if stat.S_ISLNK(details.st_mode):
                        raise WorkloadError("unsafe_input")
                candidates.extend(Path(current) / name for name in sorted(filenames))
        except OSError:
            raise WorkloadError("unreadable") from None
    for path in candidates:
        body = read_bounded(path, MAX_CENSUS_BYTES)
        rel = path.relative_to(fixture_root).as_posix()
        rows.append([rel, hashlib.sha256(body).hexdigest(), len(body)])
    return sorted(rows)


def fixture_digest(fixture_root: Path | None = None) -> str:
    """SHA-256 of canonical sorted ``[rel, hex, size]`` committed-input rows plus LF."""
    root = (REPO_ROOT / FIXTURE_RELATIVE) if fixture_root is None else fixture_root
    rows = _fixture_file_rows(root)
    try:
        data = canonical_bytes(rows, MAX_CENSUS_BYTES)
    except CanonicalBoundError:
        raise WorkloadError("too_large") from None
    except ValueError:
        raise WorkloadError("unsafe_input") from None
    return hashlib.sha256(data + b"\n").hexdigest()


def verify_fixture(census: Census, fixture_root: Path | None = None) -> None:
    """Refuse a committed fixture that drifted from the freeze as ``stale_input``."""
    if fixture_digest(fixture_root) != census.fixture_digest:
        raise WorkloadError("stale_input")


__all__ = [
    "CENSUS_RELATIVE", "Census", "Entry", "FIXTURE_RELATIVE", "Generation", "PROJECTION_ALIAS_SETS",
    "Projection", "REPO_ROOT", "decode_census", "fixture_digest", "inventory_digest",
    "is_selected", "load_census", "project", "read_bounded", "selected_rows", "valid_relative",
    "verify_fixture",
]
