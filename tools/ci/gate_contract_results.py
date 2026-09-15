"""repomap-ci-gate-result-v1 construction and validation."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from ci.gate_contract_bindings import (
    GateBindingError,
    GateRequest,
    MergeCandidate,
    _require,
    validate_candidate,
)
from ci.gate_contract_runtime import (
    SYSTEM_BINDING_FIELDS,
    SYSTEM_REPORT_FIELDS,
    validate_successful_system_runtime,
)

RESULT_SCHEMA = "repomap-ci-gate-result-v1"
CONCLUSIONS = frozenset({"success", "failure"})

RESULT_FIELDS = (
    "schema",
    "gate_kind",
    "approval_id",
    "pr_number",
    "repository",
    "approved_base_branch",
    "approved_base_sha",
    "approved_head_branch",
    "approved_head_sha",
    "tested_candidate_sha",
    "tested_candidate_tree",
    "candidate_base_parent",
    "candidate_head_parent",
    "conclusion",
    "merge_authorized",
    "system_report_sha256",
    "system_binding_sha256",
)


def validate_result_payload(payload: Mapping[str, Any]) -> None:
    """Reject results carrying fields outside the published schema."""
    unknown = set(payload).difference(RESULT_FIELDS)
    _require(not unknown, f"gate result carries unknown fields: {sorted(unknown)}")
    missing = set(RESULT_FIELDS).difference(payload)
    _require(not missing, f"gate result is missing fields: {sorted(missing)}")
    _require(payload["schema"] == RESULT_SCHEMA, "gate result schema mismatch")
    _require(
        payload["merge_authorized"] is (payload["conclusion"] == "success"),
        "merge_authorized must follow the recorded conclusion exactly",
    )


def build_result(
    *,
    request: GateRequest,
    candidate: MergeCandidate,
    conclusion: str,
    system_report_path: str | Path | None = None,
    system_binding_path: str | Path | None = None,
) -> dict[str, Any]:
    """Emit repomap-ci-gate-result-v1 for one qualified candidate."""
    _require(conclusion in CONCLUSIONS, f"unsupported conclusion {conclusion!r}")
    validate_candidate(request, candidate)

    system_report_sha256 = ""
    system_binding_sha256 = ""
    merge_authorized = conclusion == "success"

    if request.gate_kind == "main-system":
        if conclusion == "success":
            if system_report_path is None or system_binding_path is None:
                raise GateBindingError(
                    "main-system success result requires system report and binding paths"
                )
            report_p = Path(system_report_path)
            binding_p = Path(system_binding_path)
            _require(report_p.exists(), f"system report file not found: {report_p}")
            _require(binding_p.exists(), f"system binding file not found: {binding_p}")

            report_bytes = report_p.read_bytes()
            binding_bytes = binding_p.read_bytes()
            system_report_sha256 = hashlib.sha256(report_bytes).hexdigest()
            system_binding_sha256 = hashlib.sha256(binding_bytes).hexdigest()

            try:
                report_payload = json.loads(report_bytes.decode("utf-8"))
            except Exception as exc:
                raise GateBindingError(f"malformed JSON in system report: {exc}") from exc

            try:
                binding_payload = json.loads(binding_bytes.decode("utf-8"))
            except Exception as exc:
                raise GateBindingError(f"malformed JSON in system binding: {exc}") from exc

            # Validate closed report schema
            _require(isinstance(report_payload, dict), "system report must be a JSON object")
            unknown_report = set(report_payload).difference(SYSTEM_REPORT_FIELDS)
            _require(not unknown_report, f"system report carries unknown fields: {sorted(unknown_report)}")
            missing_report = set(SYSTEM_REPORT_FIELDS).difference(report_payload)
            _require(not missing_report, f"system report missing fields: {sorted(missing_report)}")
            _require(report_payload.get("schema") == "repomap-system-gate-report-v1", "invalid system report schema")

            # Validate closed binding schema
            _require(isinstance(binding_payload, dict), "system binding must be a JSON object")
            unknown_binding = set(binding_payload).difference(SYSTEM_BINDING_FIELDS)
            _require(not unknown_binding, f"system binding carries unknown fields: {sorted(unknown_binding)}")
            missing_binding = set(SYSTEM_BINDING_FIELDS).difference(binding_payload)
            _require(not missing_binding, f"system binding missing fields: {sorted(missing_binding)}")
            _require(binding_payload.get("schema") == "repomap-system-gate-binding-v1", "invalid system binding schema")

            # Validate exact logical gate request fields in report and binding
            for field in (
                "gate_kind",
                "approval_id",
                "pr_number",
                "repository",
            ):
                _require(
                    str(report_payload.get(field)) == str(getattr(request, field)),
                    f"system report {field} mismatch: {report_payload.get(field)!r} != {getattr(request, field)!r}",
                )
                _require(
                    str(binding_payload.get(field)) == str(getattr(request, field)),
                    f"system binding {field} mismatch: {binding_payload.get(field)!r} != {getattr(request, field)!r}",
                )

            _require(report_payload.get("approved_base_branch") == request.base_branch, "report base_branch mismatch")
            _require(binding_payload.get("approved_base_branch") == request.base_branch, "binding base_branch mismatch")
            _require(report_payload.get("approved_base_sha") == request.base_sha, "report base_sha mismatch")
            _require(binding_payload.get("approved_base_sha") == request.base_sha, "binding base_sha mismatch")
            _require(report_payload.get("approved_head_branch") == request.head_branch, "report head_branch mismatch")
            _require(binding_payload.get("approved_head_branch") == request.head_branch, "binding head_branch mismatch")
            _require(report_payload.get("approved_head_sha") == request.head_sha, "report head_sha mismatch")
            _require(binding_payload.get("approved_head_sha") == request.head_sha, "binding head_sha mismatch")

            # Validate exact candidate fields in report and binding
            _require(report_payload.get("tested_candidate_sha") == candidate.sha, "report candidate SHA mismatch")
            _require(binding_payload.get("tested_candidate_sha") == candidate.sha, "binding candidate SHA mismatch")
            _require(report_payload.get("tested_candidate_tree") == candidate.tree, "report candidate tree mismatch")
            _require(binding_payload.get("tested_candidate_tree") == candidate.tree, "binding candidate tree mismatch")
            _require(report_payload.get("candidate_base_parent") == candidate.first_parent, "report base parent mismatch")
            _require(binding_payload.get("candidate_base_parent") == candidate.first_parent, "binding base parent mismatch")
            _require(report_payload.get("candidate_head_parent") == candidate.second_parent, "report head parent mismatch")
            _require(binding_payload.get("candidate_head_parent") == candidate.second_parent, "binding head parent mismatch")

            # Validate nonempty candidate image ID and digest
            cand_img_id = report_payload.get("candidate_image_id", "")
            cand_img_digest = report_payload.get("candidate_image_digest", "")
            _require(isinstance(cand_img_id, str) and cand_img_id.startswith("sha256:"), "empty or invalid candidate_image_id in report")
            _require(isinstance(cand_img_digest, str) and len(cand_img_digest) > 0, "empty candidate_image_digest in report")
            _require(binding_payload.get("candidate_image_id") == cand_img_id, "binding candidate_image_id mismatch")
            _require(binding_payload.get("candidate_image_digest") == cand_img_digest, "binding candidate_image_digest mismatch")

            # Validate report digest in binding
            _require(
                binding_payload.get("system_report_sha256") == system_report_sha256,
                "binding system_report_sha256 does not match SHA-256 of report file",
            )

            # Validate conclusions and merge_authorized values
            _require(report_payload.get("passed") is True, "system report passed must be True")
            _require(report_payload.get("conclusion") == "success", "system report conclusion must be 'success'")
            _require(report_payload.get("merge_authorized") is True, "system report merge_authorized must be True")
            _require(report_payload.get("execution_mode") == "hosted_qualification", "system report execution_mode must be 'hosted_qualification'")
            _require(binding_payload.get("conclusion") == "success", "system binding conclusion must be 'success'")
            _require(binding_payload.get("merge_authorized") is True, "system binding merge_authorized must be True")
            _require(binding_payload.get("execution_mode") == "hosted_qualification", "system binding execution_mode must be 'hosted_qualification'")
            validate_successful_system_runtime(
                report_payload,
                binding_payload,
                report_file=report_p.name,
            )
        else:
            merge_authorized = False
            if system_report_path is not None and Path(system_report_path).exists():
                try:
                    system_report_sha256 = hashlib.sha256(Path(system_report_path).read_bytes()).hexdigest()
                except Exception:
                    pass
            if system_binding_path is not None and Path(system_binding_path).exists():
                try:
                    system_binding_sha256 = hashlib.sha256(Path(system_binding_path).read_bytes()).hexdigest()
                except Exception:
                    pass

    result = {
        "schema": RESULT_SCHEMA,
        "gate_kind": request.gate_kind,
        "approval_id": request.approval_id,
        "pr_number": request.pr_number,
        "repository": request.repository,
        "approved_base_branch": request.base_branch,
        "approved_base_sha": request.base_sha,
        "approved_head_branch": request.head_branch,
        "approved_head_sha": request.head_sha,
        "tested_candidate_sha": candidate.sha,
        "tested_candidate_tree": candidate.tree,
        "candidate_base_parent": candidate.first_parent,
        "candidate_head_parent": candidate.second_parent,
        "conclusion": conclusion,
        "merge_authorized": merge_authorized,
        "system_report_sha256": system_report_sha256,
        "system_binding_sha256": system_binding_sha256,
    }
    validate_result_payload(result)
    return result
