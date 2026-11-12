"""Actual private study inputs, raw members, report assembly and terminal export.

This owner assembles observed evidence; it creates no execution authority.
The unchanged journal framing and the phase-private sidecar together retain
bytes through the ordinary no-coverage sandbox's captured stdout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import stat
from typing import Any

from repomap_test_support.w5_experiment_support import DECLARED_PROFILE_IDENTITY
from retrieval_public_text_export import ALL_NAMES, emit_study_evidence
from retrieval_public_text_preflight import check_transition_observation
from retrieval_public_text_report import (
    ReportEvidence, build_report, census_summary, component_evidence, fences_summary,
    import_summary, index_summary, preparation_summary, read_verified_report,
    request_summary, seal_summary, write_report,
)
from retrieval_public_text_report_cells import expected_cell_keys
from retrieval_semantic_experiment_artifacts import MEMBER_NAMES
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_generator_kernel_contracts import MODEL_REVISION
from retrieval_semantic_raw_component_anchors import MEMBER_ROLES

REPORT_NAME = "public-text-calibration-report.json"
TRANSITION_NAME = "functional-transition-observation.json"
TRANSITION_GATE_NAME = "functional-transition-gate.json"
MAX_RAW_BYTES = 32 * 1024 * 1024


def _directory(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("private_evidence_root")
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink():
            raise ValueError("private_evidence_symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("private_evidence_directory")
    path.chmod(0o700)


def write_private_file(path: Path, raw: bytes) -> None:
    """An exclusive owned regular file; callers supply only fixed internal names."""
    _directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("private_evidence_write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_private_file(path: Path, limit: int = MAX_RAW_BYTES) -> bytes:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError("private_evidence_symlink")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or not 0 <= before.st_size <= limit):
            raise ValueError("private_evidence_file")
        raw = bytearray()
        while len(raw) <= limit:
            part = os.read(descriptor, min(65536, limit + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(descriptor)
        current = os.lstat(path)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if len(raw) != before.st_size or identity(before) != identity(after) or identity(before) != identity(current):
            raise ValueError("private_evidence_changed")
        return bytes(raw)
    finally:
        os.close(descriptor)


def private_generation_inputs(prepared: Any, selected: Any, gate_payload: bytes) -> dict[str, bytes]:
    """Actual pinned objects and printed payload; raw task questions/golds remain private."""
    values = {
        "publication.json": prepared.pin.to_dict(),
        "task-pins.json": selected.pins.to_dict(),
        "selected-task-set.json": selected.to_dict(),
        "selected-task-objects.json": [task.to_dict() for task in selected.tasks],
        "preparation.json": prepared.preparation.to_dict(),
        "census.json": prepared.census.to_dict(),
    }
    return {"generation-gate.json": gate_payload,
            **{name: canonical_json_bytes(value) + b"\n" for name, value in values.items()}}


def retain_raw_members(root: Path, attempt_id: str, members: Mapping[str, bytes]) -> None:
    """Retain actual response bytes before parsing; retention alone is not verification."""
    if attempt_id not in ("w5-semantic-g1", "w5-semantic-g2") or set(members) != set(MEMBER_ROLES):
        raise ValueError("private_raw_members")
    if any(type(raw) is not bytes for raw in members.values()) or sum(map(len, members.values())) > MAX_RAW_BYTES:
        raise ValueError("private_raw_size")
    _directory(root)
    _directory(root / "raw-components")
    directory = root / "raw-components" / attempt_id
    if directory.exists() or directory.is_symlink():
        raise ValueError("private_raw_exists")
    _directory(directory)
    for name in sorted(members):
        write_private_file(directory / name, members[name])


def _generation_row(g: int, gen: Any, cells: Sequence[Mapping[str, Any]], functional_only: bool) -> dict[str, Any]:
    inventory = "changed" if any(c["generation"] == g and (c["reason"] or {}).get("code") == "study_relation_changed"
                                 for c in cells) else "verified"
    return {
        "generation": g, "publication_identity": gen.prepared.dual.publication_identity,
        "census": census_summary(gen.prepared.census), "preparation": preparation_summary(gen.prepared.preparation),
        "request": request_summary(gen.prepared.dual, gen.request_raw),
        **component_evidence(gen.artifact, gen.members), "seal": seal_summary(gen.seal),
        "imports": [import_summary(batch) for batch in gen.imports],
        "indexes": [index_summary(index, arm) for index, arm in gen.indexes],
        "fences": fences_summary(functional_only=functional_only, creation="verified",
                                 inventory=inventory, publication="current"),
    }


def write_observed_report(env: Any, *, study_identity: str, selected: Any, evaluator: Any,
                          scope: Any, generations: Mapping[int, Any], cells: Sequence[dict[str, Any]],
                          cleanup: Any) -> tuple[str, str]:
    order = {key: index for index, key in enumerate(expected_cell_keys())}
    sorted_cells = sorted(cells, key=lambda c: order[(c["generation"], c["task_id"], c["task_sha256"], c["arm"],
                                                     c["repetition"])])
    report = build_report(
        study_identity=study_identity, selected_task_set_identity=selected.identity(),
        source={"q_source_closure": evaluator.identity, "artifact_profile_identity": DECLARED_PROFILE_IDENTITY,
                "model_revision": MODEL_REVISION}, functional_only=env.functional_only,
        generations=[_generation_row(g, generations[g], cells, env.functional_only) for g in (1, 2)],
        cells=sorted_cells, cleanup=cleanup.to_dict(), scope=scope)
    _directory(env.report_root)
    path = env.report_root / REPORT_NAME
    identity = write_report(path, report, scope=scope)
    evidence = ReportEvidence({g: (generations[g].artifact, generations[g].members) for g in (1, 2)}, selected, scope)
    return identity, read_verified_report(path, evidence).verification


def write_transition_pair(root: Path, observation: Mapping[str, Any], *, counts: Mapping[str, Any],
                          evaluator_identity: str, selected: Any) -> dict[str, Any]:
    """Write and independently reread the actual source-bound interval and checked gate."""
    expected = dict(actual_counts=counts, q_source_closure_identity=evaluator_identity,
                    task_pins_identity=selected.pins.identity(), selected_task_set_identity=selected.identity(),
                    artifact_profile_identity=DECLARED_PROFILE_IDENTITY)
    gate = check_transition_observation(observation, **expected)
    for name, value in ((TRANSITION_NAME, observation), (TRANSITION_GATE_NAME, gate)):
        write_private_file(root / name, canonical_json_bytes(value) + b"\n")
    reread = json.loads(read_private_file(root / TRANSITION_NAME, 64 * 1024))
    actual_gate = json.loads(read_private_file(root / TRANSITION_GATE_NAME, 64 * 1024))
    if reread != observation or actual_gate != check_transition_observation(reread, **expected):
        raise ValueError("private_transition_readback")
    return actual_gate


def emit_private_evidence(root: Path, journal_dirs: Sequence[Path], *, functional_only: bool) -> str:
    extras = {name: read_private_file(root / name) for name in sorted(ALL_NAMES) if (root / name).exists()}
    journal_bytes = sum(len(read_private_file(directory / name)) for directory in journal_dirs for name in MEMBER_NAMES)
    return emit_study_evidence(extras, journal_decoded_bytes=journal_bytes, functional_only=functional_only)


__all__ = ["REPORT_NAME", "TRANSITION_GATE_NAME", "TRANSITION_NAME", "emit_private_evidence",
           "private_generation_inputs", "read_private_file", "retain_raw_members", "write_observed_report",
           "write_private_file", "write_transition_pair"]
