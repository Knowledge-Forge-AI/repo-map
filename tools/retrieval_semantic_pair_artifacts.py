"""Bounded readers for the retained W5 six-member journals.

The paired report treats the journals as immutable evidence.  This module
owns only filesystem/JSON framing; pairing and metric interpretation live in
``retrieval_semantic_pair_metrics``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from retrieval_semantic_baseline_result_frames import (
    MAX_RESULT_BYTES,
    MAX_RESULT_INPUT_BYTES,
)
from retrieval_semantic_experiment_artifacts import MEMBER_LIMITS, MEMBER_NAMES


MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_JSON_TRAVERSAL_DEPTH = 256
MAX_JSON_TRAVERSAL_NODES = 250_000
JOURNAL_SCHEMA = "cloe-w5-semantic-experiment-v1"
ATTEMPT_IDS = {"w5-semantic-g1", "w5-semantic-g2"}
GENERATION_BY_ATTEMPT = {"w5-semantic-g1": 1, "w5-semantic-g2": 2}


class PairReportRefusal(ValueError):
    """A public-safe reason for rejecting an unbound or malformed artifact."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or any(ord(char) < 32 for char in code):
            code = "pair_report_refused"
        self.code = code
        super().__init__(code)


def refuse(code: str) -> PairReportRefusal:
    """Create the stable exception used by all paired-report boundaries."""

    return PairReportRefusal(code)


def digest_bytes(raw: bytes) -> str:
    """Return the repository's public ``sha256:`` digest spelling."""

    if type(raw) is not bytes:
        raise refuse("pair_digest_input")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise refuse("pair_duplicate_json_field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise refuse("pair_nonfinite_json")


def _validate_finite(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > MAX_JSON_TRAVERSAL_NODES:
            raise refuse("pair_json_traversal")
        if depth > MAX_JSON_TRAVERSAL_DEPTH:
            raise refuse("pair_json_depth")
        if type(current) is float and not math.isfinite(current):
            raise refuse("pair_nonfinite_json")
        if isinstance(current, Mapping):
            pending.extend((child, depth + 1) for child in current.values())
        elif type(current) is list:
            pending.extend((child, depth + 1) for child in current)


def parse_json_object(raw: bytes, *, code_prefix: str) -> dict[str, object]:
    """Parse one strict JSON object without changing the retained bytes."""

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except PairReportRefusal:
        raise
    except RecursionError as error:
        raise refuse(code_prefix + "_depth") from error
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise refuse(code_prefix + "_json") from error
    try:
        _validate_finite(value)
    except RecursionError as error:
        raise refuse(code_prefix + "_depth") from error
    if type(value) is not dict:
        raise refuse(code_prefix + "_object")
    return value


def _absolute_path(raw_path: object, *, code: str) -> Path:
    if not isinstance(raw_path, (str, os.PathLike)):
        raise refuse(code)
    try:
        path = Path(raw_path)
    except (TypeError, ValueError) as error:
        raise refuse(code) from error
    if (
        not path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or any(parent.is_symlink() for parent in path.parents)
    ):
        raise refuse(code)
    return path


def _bounded_read(path: Path, limit: int, *, code_prefix: str) -> bytes:
    try:
        initial = os.lstat(path)
    except OSError as error:
        raise refuse(code_prefix + "_unreadable") from error
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise refuse(code_prefix + "_unsafe")
    if initial.st_size > limit:
        raise refuse(code_prefix + "_size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise refuse(code_prefix + "_unreadable") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit:
            raise refuse(code_prefix + "_size")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise refuse(code_prefix + "_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise refuse(code_prefix + "_changed")
        return b"".join(chunks)
    except PairReportRefusal:
        raise
    except OSError as error:
        raise refuse(code_prefix + "_unreadable") from error
    finally:
        os.close(descriptor)


def read_owned_file(
    raw_path: object, *, limit: int = MAX_REPORT_BYTES, code_prefix: str = "pair_file",
) -> bytes:
    """Read a result/output file with the same no-symlink discipline as journals."""

    path = _absolute_path(raw_path, code="pair_file_path")
    if type(code_prefix) is not str or not code_prefix or any(ord(char) < 32 for char in code_prefix):
        raise refuse("pair_file_code")
    return _bounded_read(path, limit, code_prefix=code_prefix)


def _validate_digest(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise refuse(code)
    return value


def _validate_identity_list(value: object, code: str) -> tuple[str, ...]:
    if type(value) is not list or not value or any(type(item) is not str or not item for item in value):
        raise refuse(code)
    items = tuple(value)
    if len(set(items)) != len(items):
        raise refuse(code)
    return items


@dataclass(frozen=True)
class JournalArtifact:
    """One validated journal, retaining raw member bytes and parsed events."""

    attempt_id: str
    generation: int
    members: Mapping[str, bytes]
    declaration: Mapping[str, object]
    source_manifest: Mapping[str, object]
    report: Mapping[str, object]
    terminal: Mapping[str, object]
    observations: tuple[Mapping[str, object], ...]

    @property
    def member_digests(self) -> dict[str, str]:
        return {name: digest_bytes(self.members[name]) for name in MEMBER_NAMES}

    @property
    def member_lengths(self) -> dict[str, int]:
        return {name: len(self.members[name]) for name in MEMBER_NAMES}


def _parse_observations(raw: bytes) -> tuple[Mapping[str, object], ...]:
    if not raw.endswith(b"\n"):
        raise refuse("pair_observations_unterminated")
    lines = raw[:-1].split(b"\n")
    if any(not line for line in lines):
        raise refuse("pair_observations_blank")
    return tuple(parse_json_object(line, code_prefix="pair_observation") for line in lines)


def _validate_terminal(
    terminal: Mapping[str, object], members: Mapping[str, bytes], observation_count: int,
) -> None:
    expected_fields = {
        "declaration_sha256", "journal_sha256", "observation_count", "report_sha256",
        "source_manifest_sha256", "sources_archive_sha256", "status",
    }
    if frozenset(terminal) != expected_fields:
        raise refuse("pair_terminal_fields")
    hashes = {
        "declaration_sha256": "declaration.json",
        "journal_sha256": "observations.jsonl",
        "report_sha256": "report.json",
        "source_manifest_sha256": "source-manifest.json",
        "sources_archive_sha256": "sources.zip",
    }
    for field, member in hashes.items():
        if _validate_digest(terminal[field], "pair_terminal_digest") != digest_bytes(members[member]):
            raise refuse("pair_terminal_digest_mismatch")
    if type(terminal["observation_count"]) is not int or terminal["observation_count"] != observation_count:
        raise refuse("pair_terminal_observation_count")
    if terminal["status"] not in {"completed", "failed"}:
        raise refuse("pair_terminal_status")


def _validate_declaration(
    declaration: Mapping[str, object], attempt_id: str, generation: int,
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    required = {
        "arms", "attempt_id", "generation", "repetitions", "schema", "task_ids",
        "input_identity",
    }
    if not required.issubset(declaration):
        raise refuse("pair_declaration_fields")
    if declaration["schema"] != JOURNAL_SCHEMA or declaration["attempt_id"] != attempt_id:
        raise refuse("pair_declaration_identity")
    if declaration["generation"] != generation:
        raise refuse("pair_declaration_generation")
    arms = _validate_identity_list(declaration["arms"], "pair_declaration_arms")
    tasks = _validate_identity_list(declaration["task_ids"], "pair_declaration_tasks")
    _validate_digest(declaration["input_identity"], "pair_declaration_input_identity")
    repetitions = declaration["repetitions"]
    if type(repetitions) is not int or not 1 <= repetitions <= 100:
        raise refuse("pair_declaration_repetitions")
    return arms, tasks, repetitions


def load_journal(raw_path: object) -> JournalArtifact:
    """Load and hash-check one retained six-member journal directory."""

    path = _absolute_path(raw_path, code="pair_attempt_unsafe")
    try:
        info = os.lstat(path)
    except OSError as error:
        raise refuse("pair_attempt_unreadable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise refuse("pair_attempt_unsafe")
    attempt_id = path.name
    if attempt_id not in ATTEMPT_IDS:
        raise refuse("pair_attempt_id")
    generation = GENERATION_BY_ATTEMPT[attempt_id]
    members = {
        name: _bounded_read(path / name, MEMBER_LIMITS[name], code_prefix="pair_member")
        for name in MEMBER_NAMES
    }
    declaration = parse_json_object(members["declaration.json"], code_prefix="pair_declaration")
    source_manifest = parse_json_object(
        members["source-manifest.json"], code_prefix="pair_source_manifest",
    )
    report = parse_json_object(members["report.json"], code_prefix="pair_legacy_report")
    terminal = parse_json_object(members["terminal.json"], code_prefix="pair_terminal")
    observations = _parse_observations(members["observations.jsonl"])
    _validate_declaration(declaration, attempt_id, generation)
    _validate_terminal(terminal, members, len(observations))
    archive_digest = source_manifest.get("archive_sha256")
    if archive_digest is not None and _validate_digest(archive_digest, "pair_source_digest") != digest_bytes(members["sources.zip"]):
        raise refuse("pair_source_archive_mismatch")
    for event in observations:
        if type(event.get("event")) is not str or not event["event"]:
            raise refuse("pair_observation_event")
    return JournalArtifact(
        attempt_id,
        generation,
        members,
        declaration,
        source_manifest,
        report,
        terminal,
        observations,
    )


__all__ = [
    "ATTEMPT_IDS",
    "GENERATION_BY_ATTEMPT",
    "JOURNAL_SCHEMA",
    "JournalArtifact",
    "MAX_REPORT_BYTES",
    "MAX_RESULT_BYTES",
    "MAX_RESULT_INPUT_BYTES",
    "MEMBER_NAMES",
    "PairReportRefusal",
    "digest_bytes",
    "load_journal",
    "parse_json_object",
    "read_owned_file",
    "refuse",
]
