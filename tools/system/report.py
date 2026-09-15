"""Structured test report serialization for the main-promotion system gate."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.system.config import BINDING_SCHEMA, DIAGNOSTIC_SCHEMA, REPORT_SCHEMA


_MAX_STRING_BYTES = 4096


def _snapshot_details(
    val: Any,
    *,
    max_depth: int = 10,
    max_items: int = 100,
    _depth: int = 0,
    _seen: set[int] | None = None,
    _budget: list[int] | None = None,
) -> Any:
    """Recursively snapshot mappings and sequences into immutable, JSON-safe structures."""
    if _seen is None:
        _seen = set()
    if _budget is None:
        _budget = [1000]
    _budget[0] -= 1
    if _budget[0] < 0:
        return {"__budget_exceeded__": True}
    if _depth > max_depth:
        return {"__depth_exceeded__": True}
    if val is None or isinstance(val, (int, bool)):
        return val
    if isinstance(val, float):
        if math.isnan(val):
            return {"__nonfinite__": "nan"}
        if math.isinf(val):
            return {"__nonfinite__": "inf" if val > 0 else "-inf"}
        return val
    if isinstance(val, str):
        val_bytes = val.encode("utf-8")
        if len(val_bytes) > _MAX_STRING_BYTES:
            suffix = b"\n... [TRUNCATED]"
            limit = _MAX_STRING_BYTES - len(suffix)
            return val_bytes[:limit].decode("utf-8", errors="ignore") + suffix.decode("utf-8")
        return val
    val_id = id(val)
    if val_id in _seen:
        return {"__cyclic_ref__": True}
    if isinstance(val, dict):
        _seen.add(val_id)
        try:
            is_marker = (
                "__truncated_items__" in val
                and isinstance(val["__truncated_items__"], int)
                and not isinstance(val["__truncated_items__"], bool)
                and val["__truncated_items__"] >= 0
            )
            if is_marker:
                prev_truncated = int(val["__truncated_items__"])
                items = [(k, v) for k, v in val.items() if k != "__truncated_items__"]
            else:
                prev_truncated = 0
                items = list(val.items())
            result: dict[str, Any] = {}
            for i, (k, v) in enumerate(items):
                if i >= max_items:
                    result["__truncated_items__"] = (len(items) - max_items) + prev_truncated
                    break
                if isinstance(k, str):
                    k_bytes = k.encode("utf-8")
                    if len(k_bytes) > 256:
                        key_str = k_bytes[:240].decode("utf-8", errors="ignore") + "...[TRUNC]"
                    else:
                        key_str = k
                elif isinstance(k, (int, bool)):
                    key_str = str(k).lower() if isinstance(k, bool) else str(k)
                elif isinstance(k, float):
                    key_str = "__nonfinite__" if (math.isnan(k) or math.isinf(k)) else str(k)
                elif k is None:
                    key_str = "null"
                else:
                    key_str = f"__key_{type(k).__name__}_{i}__"
                if key_str in result:
                    orig_key = key_str
                    col_num = 1
                    while key_str in result:
                        key_str = f"{orig_key}__collision_{col_num}__"
                        col_num += 1
                result[key_str] = _snapshot_details(
                    v,
                    max_depth=max_depth,
                    max_items=max_items,
                    _depth=_depth + 1,
                    _seen=_seen,
                    _budget=_budget,
                )
            else:
                if prev_truncated > 0:
                    result["__truncated_items__"] = prev_truncated
            return result
        finally:
            _seen.discard(val_id)
    if isinstance(val, (list, tuple, set, frozenset)):
        _seen.add(val_id)
        try:
            if isinstance(val, (set, frozenset)):
                try:
                    seq = sorted(val)
                except TypeError:
                    seq = sorted(val, key=lambda x: (type(x).__name__, repr(x)))
            else:
                seq = list(val)
            prev_truncated = 0
            if seq and isinstance(seq[-1], dict):
                last_item = seq[-1]
                if (
                    set(last_item.keys()) == {"__truncated_items__"}
                    and isinstance(last_item["__truncated_items__"], int)
                    and not isinstance(last_item["__truncated_items__"], bool)
                    and last_item["__truncated_items__"] >= 0
                ):
                    prev_truncated = int(last_item["__truncated_items__"])
                    seq = seq[:-1]
            seq_result: list[Any] = []
            for i, item in enumerate(seq):
                if i >= max_items:
                    seq_result.append({"__truncated_items__": (len(seq) - max_items) + prev_truncated})
                    break
                seq_result.append(
                    _snapshot_details(
                        item,
                        max_depth=max_depth,
                        max_items=max_items,
                        _depth=_depth + 1,
                        _seen=_seen,
                        _budget=_budget,
                    )
                )
            else:
                if prev_truncated > 0:
                    seq_result.append({"__truncated_items__": prev_truncated})
            return seq_result
        finally:
            _seen.discard(val_id)
    return {"__unserializable__": type(val).__name__}


@dataclass(frozen=True)
class SystemStepResult:
    step_name: str
    status: str
    duration_seconds: float
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "details",
            _snapshot_details(self.details) if isinstance(self.details, dict) else {},
        )


@dataclass(frozen=True)
class SystemSuiteResult:
    candidate_image_id: str
    candidate_image_tag: str
    candidate_tree_sha: str
    run_id: str
    passed: bool
    total_duration_seconds: float
    step_results: tuple[SystemStepResult, ...]
    docker_projection: dict[str, int] = field(default_factory=dict)
    candidate_commit_sha: str = ""
    gate_kind: str = "main-system"
    approval_id: str = ""
    pr_number: str = ""
    repository: str = ""
    approved_base_branch: str = ""
    approved_base_sha: str = ""
    approved_head_branch: str = ""
    approved_head_sha: str = ""
    candidate_base_parent: str = ""
    candidate_head_parent: str = ""
    candidate_image_digest: str = ""
    candidate_image_labels: dict[str, str] = field(default_factory=dict)
    release_version_checks: dict[str, Any] = field(default_factory=dict)
    service_identities: dict[str, str] = field(default_factory=dict)
    coordinator_evidence: dict[str, Any] = field(default_factory=dict)
    mcp_readback_digest: str = ""
    cleanup_status: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "local_rehearsal"
    error_message: str = ""
    conclusion: str = "success"
    merge_authorized: bool = False
    generated_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        conclusion = "success" if self.passed else "failure"
        merge_authorized = self.passed if self.execution_mode == "hosted_qualification" else False
        return {
            "schema": REPORT_SCHEMA,
            "gate_kind": self.gate_kind,
            "approval_id": self.approval_id,
            "pr_number": self.pr_number,
            "repository": self.repository,
            "approved_base_branch": self.approved_base_branch,
            "approved_base_sha": self.approved_base_sha,
            "approved_head_branch": self.approved_head_branch,
            "approved_head_sha": self.approved_head_sha,
            "tested_candidate_sha": self.candidate_commit_sha,
            "tested_candidate_tree": self.candidate_tree_sha,
            "candidate_base_parent": self.candidate_base_parent,
            "candidate_head_parent": self.candidate_head_parent,
            "candidate_image_id": self.candidate_image_id,
            "candidate_image_tag": self.candidate_image_tag,
            "candidate_image_digest": self.candidate_image_digest,
            "candidate_image_labels": self.candidate_image_labels,
            "candidate_tree_sha": self.candidate_tree_sha,
            "candidate_commit_sha": self.candidate_commit_sha,
            "release_version_checks": self.release_version_checks,
            "service_identities": self.service_identities,
            "coordinator_evidence": self.coordinator_evidence,
            "mcp_readback_digest": self.mcp_readback_digest,
            "cleanup_status": self.cleanup_status,
            "run_id": self.run_id,
            "passed": self.passed,
            "conclusion": conclusion,
            "merge_authorized": merge_authorized,
            "overall_status": "passed" if self.passed else "failed",
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "generated_at_utc": self.generated_at_utc,
            "error_message": self.error_message,
            "step_results": [
                {
                    "step_name": step.step_name,
                    "status": step.status,
                    "duration_seconds": round(step.duration_seconds, 3),
                    "message": step.message,
                    "details": _snapshot_details(step.details),
                }
                for step in self.step_results
            ],
            "docker_projection": self.docker_projection,
            "execution_mode": self.execution_mode,
        }

    def to_binding_dict(self, system_report_sha256: str) -> dict[str, Any]:
        conclusion = "success" if self.passed else "failure"
        merge_authorized = self.passed if self.execution_mode == "hosted_qualification" else False
        return {
            "schema": BINDING_SCHEMA,
            "gate_kind": self.gate_kind,
            "approval_id": self.approval_id,
            "pr_number": self.pr_number,
            "repository": self.repository,
            "approved_base_branch": self.approved_base_branch,
            "approved_base_sha": self.approved_base_sha,
            "approved_head_branch": self.approved_head_branch,
            "approved_head_sha": self.approved_head_sha,
            "tested_candidate_sha": self.candidate_commit_sha,
            "tested_candidate_tree": self.candidate_tree_sha,
            "candidate_base_parent": self.candidate_base_parent,
            "candidate_head_parent": self.candidate_head_parent,
            "candidate_image_id": self.candidate_image_id,
            "candidate_image_digest": self.candidate_image_digest,
            "candidate_image_labels": self.candidate_image_labels,
            "system_report_file": "repomap-system-gate-report.json",
            "system_report_sha256": system_report_sha256,
            "conclusion": conclusion,
            "merge_authorized": merge_authorized,
            "generated_at_utc": self.generated_at_utc,
            "execution_mode": self.execution_mode,
        }


def write_system_report(
    result: SystemSuiteResult,
    *,
    report_dir: Path | None = None,
    evidence_dir: Path | None = None,
) -> Path | None:
    payload = result.to_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    report_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    binding_payload = result.to_binding_dict(report_sha256)
    rendered_binding = json.dumps(binding_payload, indent=2, sort_keys=True) + "\n"

    written_path: Path | None = None

    if report_dir is not None:
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "repomap-system-gate-report.json"
        report_file.write_text(rendered, encoding="utf-8")
        binding_file = report_dir / "repomap-system-gate-binding-v1.json"
        binding_file.write_text(rendered_binding, encoding="utf-8")
        written_path = report_file

    if evidence_dir is not None:
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = evidence_dir / "repomap-system-gate-report.json"
        evidence_file.write_text(rendered, encoding="utf-8")
        binding_file = evidence_dir / "repomap-system-gate-binding-v1.json"
        binding_file.write_text(rendered_binding, encoding="utf-8")
        if written_path is None:
            written_path = evidence_file

    return written_path


_MAX_AGGREGATE_DIAGNOSTIC_BYTES = 512 * 1024


def write_system_diagnostic(
    diagnostic: dict[str, Any],
    *,
    report_dir: Path | None = None,
    evidence_dir: Path | None = None,
) -> Path | None:
    payload = dict(diagnostic)
    payload.setdefault("schema", DIAGNOSTIC_SCHEMA)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    rendered_bytes = rendered.encode("utf-8")
    if len(rendered_bytes) > _MAX_AGGREGATE_DIAGNOSTIC_BYTES:
        payload["__diagnostic_aggregate_truncated__"] = True
        payload["service_logs"] = {"truncated": "aggregate diagnostic limit exceeded"}
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    written_path: Path | None = None
    write_errors: list[str] = []

    if report_dir is not None:
        try:
            r_dir = Path(report_dir)
            r_dir.mkdir(parents=True, exist_ok=True)
            diag_file = r_dir / "repomap-system-gate-diagnostic.json"
            diag_file.write_text(rendered, encoding="utf-8")
            written_path = diag_file
        except OSError as exc:
            write_errors.append(f"report_dir write error: {exc}")

    if evidence_dir is not None:
        try:
            e_dir = Path(evidence_dir)
            e_dir.mkdir(parents=True, exist_ok=True)
            diag_file = e_dir / "repomap-system-gate-diagnostic.json"
            diag_file.write_text(rendered, encoding="utf-8")
            if written_path is None:
                written_path = diag_file
        except OSError as exc:
            write_errors.append(f"evidence_dir write error: {exc}")

    if write_errors:
        print(f"WARNING: diagnostic write error: {'; '.join(write_errors)}", file=sys.stderr)
        if isinstance(diagnostic, dict):
            diagnostic["diagnostic_write_errors"] = list(write_errors)

    if written_path is None and (report_dir is not None or evidence_dir is not None):
        raise OSError(f"diagnostic write failed across all destinations: {'; '.join(write_errors)}")

    return written_path

