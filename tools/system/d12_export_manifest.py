"""Host-retained archive identity; the inner sandbox cannot select or rewrite this receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ci.d12_system_grant import loads_strict_json_object, validate_system_admission_proof
from repomap_test_support import d12_image_probes as d12
from test_sandbox_contract import MAX_REPORT_ARCHIVE_BYTES, MAX_REPORT_CONTENT_BYTES, MAX_REPORT_MEMBERS
from test_sandbox_report import _report_members
from tools.system.d12_system_reports import write_exclusive_0600_json
from tools.system.d12_qualification import FILENAME, PARTS, need, read_part

SCHEMA = "repomap-d12-host-export-manifest-v1"
HOST_FILENAME = "export-manifest.json"
REPORT_FILENAME = "repomap-system-gate-report.json"
BINDING_FILENAME = "repomap-system-gate-binding-v1.json"
REQUIRED_FILES = frozenset((*PARTS.values(), FILENAME, REPORT_FILENAME, BINDING_FILENAME))
MAX_MANIFEST_BYTES = 16_384


def manifest_from_archive(archive: bytes, expected_proof_bytes: bytes) -> dict[str, Any]:
    """Hash actual stopped-container archive members before the exporter writes any host files."""
    need(0 < len(archive) <= MAX_REPORT_ARCHIVE_BYTES, "archive exceeds its transport bound")
    proof = validate_system_admission_proof(loads_strict_json_object(expected_proof_bytes, label="host proof"))
    tar, members = _report_members(archive, max_members=MAX_REPORT_MEMBERS, max_content_bytes=MAX_REPORT_CONTENT_BYTES)
    files = {}
    try:
        for member, path in members:
            name = path.as_posix()
            if name not in REQUIRED_FILES:
                continue
            need(member.isreg() and 0 < member.size <= d12.REPORT_PART_LIMIT, "required archive part is invalid")
            stream = tar.extractfile(member)
            if stream is None:
                raise RuntimeError("required archive part is unreadable")
            raw = stream.read(member.size + 1)
            need(len(raw) == member.size, "required archive part is truncated")
            files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    finally:
        tar.close()
    need(set(files) == REQUIRED_FILES, "archive is missing required qualification parts")
    return {"schema": SCHEMA, "proof_sha256": hashlib.sha256(expected_proof_bytes).hexdigest(),
            "candidate_sha": proof["candidate_sha"], "candidate_tree": proof["candidate_tree"],
            "archive_sha256": hashlib.sha256(archive).hexdigest(), "files": files}


def retain_host_manifest(archive: bytes, *, expected_proof_bytes: bytes, host_proof_path: Path) -> bytes:
    payload = manifest_from_archive(archive, expected_proof_bytes)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    need(len(raw) <= MAX_MANIFEST_BYTES, "host export manifest exceeds its bound")
    write_exclusive_0600_json(host_proof_path.parent / HOST_FILENAME, payload)
    return raw


def verify_host_manifest(directory: Path, *, manifest_bytes: bytes, expected_proof_bytes: bytes) -> None:
    need(0 < len(manifest_bytes) <= MAX_MANIFEST_BYTES, "expected host export manifest is absent or oversized")
    manifest = loads_strict_json_object(manifest_bytes, label="expected host export manifest")
    proof = validate_system_admission_proof(loads_strict_json_object(expected_proof_bytes, label="expected host proof"))
    need(set(manifest) == {"schema", "proof_sha256", "candidate_sha", "candidate_tree", "archive_sha256", "files"},
         "host export manifest fields differ")
    need(manifest["schema"] == SCHEMA and manifest["proof_sha256"] == hashlib.sha256(expected_proof_bytes).hexdigest()
         and manifest["candidate_sha"] == proof["candidate_sha"] and manifest["candidate_tree"] == proof["candidate_tree"],
         "host export manifest belongs to another admission")
    need(isinstance(manifest["archive_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", manifest["archive_sha256"]),
         "archive digest is invalid")
    need(isinstance(manifest["files"], dict) and set(manifest["files"]) == REQUIRED_FILES,
         "host export manifest file set differs")
    for name, expected in manifest["files"].items():
        need(isinstance(expected, dict) and set(expected) == {"sha256", "bytes"}, "part identity fields differ")
        _data, digest = read_part(directory / name)
        need(expected == {"sha256": digest, "bytes": (directory / name).stat().st_size},
             "exported part differs from the host-retained archive")
