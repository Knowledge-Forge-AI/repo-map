"""Runtime evidence validation for assembled system qualification."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from ci.gate_contract_bindings import GateBindingError, _require

_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_DIGEST_PATTERN = re.compile(
    r"(?:[A-Za-z0-9._/-]+@)?sha256:[0-9a-f]{64}"
)

SYSTEM_REPORT_FIELDS = (
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
    "candidate_image_id",
    "candidate_image_tag",
    "candidate_image_digest",
    "candidate_image_labels",
    "candidate_tree_sha",
    "candidate_commit_sha",
    "release_version_checks",
    "service_identities",
    "coordinator_evidence",
    "mcp_readback_digest",
    "cleanup_status",
    "run_id",
    "passed",
    "conclusion",
    "merge_authorized",
    "overall_status",
    "total_duration_seconds",
    "generated_at_utc",
    "error_message",
    "step_results",
    "docker_projection",
    "execution_mode",
)

SYSTEM_BINDING_FIELDS = (
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
    "candidate_image_id",
    "candidate_image_digest",
    "candidate_image_labels",
    "system_report_file",
    "system_report_sha256",
    "conclusion",
    "merge_authorized",
    "generated_at_utc",
    "execution_mode",
)


def validate_successful_system_runtime(
    report: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    report_file: str,
) -> None:
    """Validate the runtime facts required before merge authorization."""
    image_id = report.get("candidate_image_id")
    image_digest = report.get("candidate_image_digest")
    _require(
        isinstance(image_id, str) and _IMAGE_ID_PATTERN.fullmatch(image_id),
        "system report candidate image ID is not exact",
    )
    _require(
        isinstance(image_digest, str)
        and _IMAGE_DIGEST_PATTERN.fullmatch(image_digest),
        "system report candidate image digest is not exact",
    )
    _require(
        report.get("candidate_tree_sha") == report.get("tested_candidate_tree"),
        "system report candidate tree aliases disagree",
    )
    _require(
        report.get("candidate_commit_sha") == report.get("tested_candidate_sha"),
        "system report candidate commit aliases disagree",
    )
    _require(
        binding.get("candidate_image_labels") == report.get("candidate_image_labels"),
        "system binding candidate image labels mismatch",
    )
    _require(
        binding.get("system_report_file") == report_file,
        "system binding report filename mismatch",
    )
    _require(
        report.get("overall_status") == "passed",
        "system overall status must be passed",
    )
    duration = report.get("total_duration_seconds")
    _require(
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and 0 <= duration <= 3600,
        "system report duration is outside the project deadline",
    )
    cleanup = report.get("cleanup_status")
    if not isinstance(cleanup, dict):
        raise GateBindingError("system cleanup status must be an object")
    _require(cleanup.get("success") is True, "system cleanup did not succeed")
    _require(
        cleanup.get("terminal_absence_verified") is True,
        "system cleanup did not prove terminal absence",
    )
    _require(cleanup.get("errors") == [], "system cleanup retained errors")
    steps = report.get("step_results")
    if not isinstance(steps, list) or not steps:
        raise GateBindingError("system report has no step results")
    required_steps = {
        "packaged_cluster_readiness",
        "durable_coordinator_execution",
        "controlled_coordinator_interruption_recovery",
        "idempotency_and_fencing",
        "mcp_public_stdio_readback",
    }
    names = [step.get("step_name") for step in steps if isinstance(step, dict)]
    _require(
        len(names) == len(steps),
        "system report contains malformed step results",
    )
    _require(
        set(names) == required_steps and len(names) == len(required_steps),
        "system report step set is incomplete",
    )
    _require(
        all(step.get("status") == "passed" for step in steps),
        "system report contains a failed runtime step",
    )
    releases = report.get("release_version_checks")
    if not isinstance(releases, dict):
        raise GateBindingError("system release checks must be an object")
    for component in ("postgresql", "python", "go", "psycopg", "libpq"):
        _require(
            isinstance(releases.get(component), str) and releases[component],
            f"system release check missing {component}",
        )
    _require(
        isinstance(report.get("mcp_readback_digest"), str)
        and re.fullmatch(r"[0-9a-f]{64}", report["mcp_readback_digest"]),
        "system MCP digest is invalid",
    )
    _require(
        isinstance(report.get("coordinator_evidence"), dict)
        and report["coordinator_evidence"].get("recovered_terminal_state")
        == "succeeded",
        "system coordinator recovery evidence is incomplete",
    )


_validate_successful_system_runtime = validate_successful_system_runtime
