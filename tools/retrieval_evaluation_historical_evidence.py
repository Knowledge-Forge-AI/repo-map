"""Verify retained attempt bytes without executing or extracting candidate sources."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import io
import json
from pathlib import Path
from typing import Any
import zipfile

from retrieval_evaluation_attempts import _validate_archive_path

_MAX_FILE_BYTES = 64 * 1024 * 1024
_FILES = {
    "declaration_sha256": "declaration.json",
    "report_sha256": "report.json",
    "journal_sha256": "observations.jsonl",
    "source_manifest_sha256": "source-manifest.json",
    "sources_archive_sha256": "sources.zip",
}


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("retained JSON contains duplicate keys")
        result[key] = value
    return result


def _load_json(value: bytes) -> dict[str, Any]:
    parsed = json.loads(value, object_pairs_hook=_unique_object)
    if not isinstance(parsed, dict):
        raise ValueError("retained JSON must be an object")
    return parsed


def verify_completed_attempt(
    directory: Path, *, expected_terminal_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the original raw chain; a caller supplies any trusted terminal anchor."""
    raw: dict[str, bytes] = {}
    for name in (*_FILES.values(), "terminal.json"):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("retained attempt requires six regular evidence files")
        with path.open("rb") as stream:
            value = stream.read(_MAX_FILE_BYTES + 1)
        if len(value) > _MAX_FILE_BYTES:
            raise ValueError("retained evidence exceeds the verification byte bound")
        raw[name] = value
    digests = {name: _sha256(value) for name, value in raw.items()}
    if expected_terminal_sha256 is not None and digests["terminal.json"] != expected_terminal_sha256:
        raise ValueError("retained terminal digest mismatch")
    terminal = _load_json(raw["terminal.json"])
    if terminal.get("status") != "completed":
        raise ValueError("retained attempt must be completed")
    for field, name in _FILES.items():
        if terminal.get(field) != digests[name]:
            raise ValueError(f"retained terminal {field} mismatch")
    declaration = _load_json(raw["declaration.json"])
    report = _load_json(raw["report.json"])
    manifest = _load_json(raw["source-manifest.json"])
    if report.get("status") != "completed" or report.get("attempt_id") != declaration.get("attempt_id"):
        raise ValueError("retained report/declaration identity mismatch")
    if manifest.get("schema_version") != "cloe-retrieval-attempt-source-manifest-v1":
        raise ValueError("unsupported retained source manifest")
    if manifest.get("archive_sha256") != digests["sources.zip"]:
        raise ValueError("retained archive digest mismatch")
    expected: dict[str, str] = {}
    for field, prefix in (("source_files", "sources"), ("input_files", "inputs")):
        files = manifest.get(field)
        if not isinstance(files, Mapping):
            raise ValueError("retained source/input manifest must be mappings")
        for path, digest in files.items():
            safe_path = _validate_archive_path(path)
            if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError("retained manifest requires full sha256 digests")
            expected[f"{prefix}/{safe_path}"] = digest
    if manifest["source_files"] != declaration.get("candidate_closure_digests"):
        raise ValueError("retained source manifest differs from declaration closure")
    with zipfile.ZipFile(io.BytesIO(raw["sources.zip"])) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(set(names)) != len(names) or set(names) != set(expected):
            raise ValueError("retained archive membership mismatch")
        if sum(entry.file_size for entry in entries) > _MAX_FILE_BYTES:
            raise ValueError("retained archive expands beyond verification byte bound")
        for entry in entries:
            if entry.is_dir() or _sha256(archive.read(entry)) != expected[entry.filename]:
                raise ValueError("retained archive member digest mismatch")
    events = [_load_json(line) for line in raw["observations.jsonl"].splitlines() if line.strip()]
    count = terminal.get("observation_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(events):
        raise ValueError("retained observation_count mismatch")
    return {
        "declaration": declaration, "report": report, "manifest": manifest,
        "terminal": terminal, "events": events, "sha256": digests,
    }
