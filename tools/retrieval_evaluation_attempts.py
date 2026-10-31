"""Durable admission and observation journal for retrieval evaluations.

This module deliberately owns only filesystem admission and evidence custody.
It does not know about tasks, query adapters, databases, or execution budgets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
import zipfile


_SCHEMA_VERSION = "cloe-retrieval-attempt-source-manifest-v1"
_SHA256_PREFIX = "sha256:"
_EXCLUSIVE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_APPEND_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_APPEND
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _sha256(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _json_ready(value: object) -> object:
    """Convert mappings/sequences to a finite, JSON-compatible value tree."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    raise ValueError("value is outside the canonical JSON domain")


def _canonical_json(value: object) -> bytes:
    try:
        ready = _json_ready(value)
        encoded = json.dumps(
            ready,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("value is not finite canonical JSON") from error
    return encoded + b"\n"


def _validate_attempt_id(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("attempt_id must be a non-empty portable component")
    if (
        value in {".", ".."}
        or "\x00" in value
        or "/" in value
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 for character in value)
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or PureWindowsPath(value).root
    ):
        raise ValueError("attempt_id must be a non-empty portable component")
    return value


def _validate_archive_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("archive paths must be non-empty relative strings")
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("archive paths must not be absolute or contain unsafe components")
    return value


def _validated_bytes_mapping(name: str, value: Mapping[str, bytes] | None) -> dict[str, bytes]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    result: dict[str, bytes] = {}
    for raw_path, raw_bytes in value.items():
        path = _validate_archive_path(raw_path)
        if not isinstance(raw_bytes, bytes):
            raise ValueError(f"{name} values must be bytes")
        if path in result:
            raise ValueError(f"{name} contains duplicate path: {path!r}")
        result[path] = raw_bytes
    return result


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write to attempt evidence file")
        remaining = remaining[written:]


def _write_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(str(path), _EXCLUSIVE_FLAGS, 0o600)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _read_bytes(path: Path) -> bytes:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _build_sources_archive(
    source_files: Mapping[str, bytes], input_files: Mapping[str, bytes]
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for prefix, files in (("sources", source_files), ("inputs", input_files)):
            for path, data in sorted(files.items()):
                info = zipfile.ZipInfo(f"{prefix}/{path}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
    return stream.getvalue()


@dataclass(slots=True)
class AttemptJournal:
    """Single-owner append-only journal for one admitted attempt."""

    directory: Path
    declaration_sha256: str
    _observation_count: int = field(default=0, init=False)
    _finished: bool = field(default=False, init=False)

    @property
    def observation_count(self) -> int:
        return self._observation_count

    @property
    def record_count(self) -> int:
        return self._observation_count

    def append(self, record: Mapping[str, Any]) -> None:
        """Append one finite canonical JSON object and durably flush it."""
        if self._finished or _path_exists(self.directory / "terminal.json"):
            raise RuntimeError("attempt journal is terminal")
        if not isinstance(record, Mapping):
            raise ValueError("journal record must be a mapping")
        data = _canonical_json(record)
        path = self.directory / "observations.jsonl"
        descriptor = os.open(str(path), _APPEND_FLAGS, 0o600)
        try:
            _write_all(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.directory)
        self._observation_count += 1

    def finish(self, status: str, report: Mapping[str, Any] | None = None) -> None:
        """Exclusively persist an optional report and terminal hash metadata."""
        if status not in {"completed", "failed"}:
            raise ValueError("attempt status must be completed or failed")
        if self._finished or _path_exists(self.directory / "terminal.json"):
            raise RuntimeError("attempt journal is already terminal")
        report_bytes = None
        if report is not None:
            if not isinstance(report, Mapping):
                raise ValueError("report must be a mapping")
            report_bytes = _canonical_json(report)
        if report_bytes is not None:
            _write_exclusive(self.directory / "report.json", report_bytes)
            _fsync_directory(self.directory)

        observations_path = self.directory / "observations.jsonl"
        observations = _read_bytes(observations_path) if _path_exists(observations_path) else b""
        terminal = {
            "declaration_sha256": self.declaration_sha256,
            "journal_sha256": _sha256(observations),
            "observation_count": self._observation_count,
            "report_sha256": _sha256(report_bytes) if report_bytes is not None else None,
            "source_manifest_sha256": _sha256(_read_bytes(self.directory / "source-manifest.json")),
            "sources_archive_sha256": _sha256(_read_bytes(self.directory / "sources.zip")),
            "status": status,
        }
        _write_exclusive(self.directory / "terminal.json", _canonical_json(terminal))
        _fsync_directory(self.directory)
        self._finished = True


def admit_attempt(
    root: Path,
    declaration: Mapping[str, Any],
    source_files: Mapping[str, bytes],
    *,
    input_files: Mapping[str, bytes] | None = None,
) -> AttemptJournal:
    """Admit one immutable source closure and return its durable journal."""
    if not isinstance(declaration, Mapping):
        raise ValueError("declaration must be a mapping")
    if not isinstance(source_files, Mapping):
        raise ValueError("source_files must be a mapping")
    declaration_value = _json_ready(declaration)
    if not isinstance(declaration_value, dict):
        raise ValueError("declaration must be a JSON object")
    attempt_id = _validate_attempt_id(declaration_value.get("attempt_id"))
    declared_raw = declaration_value.get("candidate_closure_digests")
    if not isinstance(declared_raw, Mapping):
        raise ValueError("candidate_closure_digests must be a mapping")
    declared: dict[str, str] = {}
    for raw_path, raw_digest in declared_raw.items():
        path = _validate_archive_path(raw_path)
        if not isinstance(raw_digest, str) or not raw_digest.startswith(_SHA256_PREFIX):
            raise ValueError("candidate closure digests must use the sha256: prefix")
        declared[path] = raw_digest
    sources = _validated_bytes_mapping("source_files", source_files)
    if set(sources) != set(declared):
        raise ValueError("source_files keys must exactly match candidate_closure_digests")
    for path, data in sources.items():
        if declared[path] != _sha256(data):
            raise ValueError(f"source digest mismatch for {path!r}")
    inputs = _validated_bytes_mapping("input_files", input_files)
    declaration_bytes = _canonical_json(declaration_value)
    archive_bytes = _build_sources_archive(sources, inputs)
    manifest = {
        "archive_sha256": _sha256(archive_bytes),
        "input_files": {path: _sha256(data) for path, data in sorted(inputs.items())},
        "schema_version": _SCHEMA_VERSION,
        "source_files": {path: _sha256(data) for path, data in sorted(sources.items())},
    }
    manifest_bytes = _canonical_json(manifest)

    experiment_root = Path(root)
    experiment_root.mkdir(parents=True, exist_ok=True)
    attempt_directory = experiment_root / attempt_id
    attempt_directory.mkdir(mode=0o700, exist_ok=False)
    _fsync_directory(experiment_root)
    _write_exclusive(attempt_directory / "declaration.json", declaration_bytes)
    _write_exclusive(attempt_directory / "sources.zip", archive_bytes)
    _write_exclusive(attempt_directory / "source-manifest.json", manifest_bytes)
    _fsync_directory(attempt_directory)
    return AttemptJournal(attempt_directory, _sha256(declaration_bytes))


__all__ = ["AttemptJournal", "admit_attempt"]
