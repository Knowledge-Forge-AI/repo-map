"""Verify exported D12 qualification against retained host authority and committed source."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ci.d12_system_grant import loads_strict_json_object, validate_system_admission_proof
from ci.gate_contract_runtime import SYSTEM_BINDING_FIELDS, SYSTEM_REPORT_FIELDS, validate_successful_system_runtime
from common_lore_index.runtime.release import (
    GO_RELEASE_VERSION, POSTGRES_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION, PYTHON_RELEASE_VERSION,
)
from tools.system.d12_candidate_assessment import _verify_round_trip
from tools.system.d12_qualification import (
    AUTHORITY_FIELDS, FILENAME, PARTS, REFERENCE_KEY, SCHEMA, need, policy_hashes, read_part,
    verify_parts, verify_terminal,
)
from tools.system.d12_export_manifest import verify_host_manifest

SUPPLEMENT_KEYS = frozenset({"schema", "policy", "qualified", "authority", "proof_sha256", "policy_sources",
    "parts", "candidate_image_id", "candidate_image_digest", "candidate_image_labels", "steps",
    "mcp_readback_digest", "cleanup", "runtime_run_id", "round_trip", "upstream_debian_findings",
    "incumbent_comparison"})
REPORT_FILENAME = "repomap-system-gate-report.json"
BINDING_FILENAME = "repomap-system-gate-binding-v1.json"


def verify_exported_qualification(
    directory: Path, *, repo_root: Path, expected_proof_bytes: bytes, expected_export_manifest_bytes: bytes,
) -> dict[str, Any]:
    """A host-selected proof is mandatory; the exported supplement cannot choose its authority."""
    need(directory.is_dir() and not directory.is_symlink(), "report root is missing or a symlink")
    need(0 < len(expected_proof_bytes) <= 16_384, "expected host proof is absent or oversized")
    proof = validate_system_admission_proof(loads_strict_json_object(expected_proof_bytes, label="expected host proof"))
    proof_sha = hashlib.sha256(expected_proof_bytes).hexdigest()
    verify_host_manifest(directory, manifest_bytes=expected_export_manifest_bytes,
                         expected_proof_bytes=expected_proof_bytes)
    supplement, supplement_sha = read_part(directory / FILENAME)
    need(set(supplement) == SUPPLEMENT_KEYS, "supplement fields are not exact")
    need(supplement.get("schema") == SCHEMA and supplement.get("policy") == "ADR0105"
         and supplement.get("qualified") is True, "qualification supplement is not positive v2")
    need(supplement["proof_sha256"] == proof_sha, "supplement refers to another host proof")
    need(supplement["authority"] == {key: proof[key] for key in AUTHORITY_FIELDS}, "host authority differs")
    need(supplement["policy_sources"] == policy_hashes(repo_root, candidate_sha=proof["candidate_sha"]),
         "policy/assessor bytes differ from the committed host candidate")
    parts, digests = verify_parts(directory, proof)
    need(supplement["parts"] == digests and set(supplement["parts"]) == set(PARTS), "evidence part digest differs")
    need(parts["intent"].get("proof_sha256") == proof_sha, "build intent refers to another host proof")
    need(parts["intent"].get("run_id") == supplement["runtime_run_id"], "runtime resource run differs")
    _verify_round_trip(supplement["round_trip"])
    need(supplement["round_trip"] == parts["assessment"]["round_trip"], "round-trip observations disagree")
    verify_terminal(supplement["steps"], supplement["cleanup"], supplement["mcp_readback_digest"])
    report, report_sha = read_part(directory / REPORT_FILENAME)
    binding, _binding_sha = read_part(directory / BINDING_FILENAME)
    need(set(report) == set(SYSTEM_REPORT_FIELDS) and set(binding) == set(SYSTEM_BINDING_FIELDS),
         "report/binding fields are not exact")
    need(report.get("schema") == "repomap-system-gate-report-v1" and
         binding.get("schema") == "repomap-system-gate-binding-v1", "report/binding schema differs")
    for record in (report, binding):
        need(record.get("conclusion") == "success" and record.get("merge_authorized") is True and
             record.get("execution_mode") == "hosted_qualification", "report/binding did not pass hosted qualification")
        for field, value in {"tested_candidate_sha": proof["candidate_sha"],
            "tested_candidate_tree": proof["candidate_tree"], "candidate_base_parent": proof["candidate_base_parent"],
            "candidate_head_parent": proof["candidate_head_parent"], "approval_id": proof["approval_id"],
            "repository": proof["repository"], "pr_number": str(proof["pull_request"]), "gate_kind": "main-system",
            "approved_base_branch": proof["base_ref"], "approved_base_sha": proof["base"],
            "approved_head_branch": proof["head_ref"], "approved_head_sha": proof["after"]}.items():
            need(record.get(field) == value, f"report/binding {field} differs from host authority")
        for field in ("candidate_image_id", "candidate_image_digest", "candidate_image_labels"):
            need(record.get(field) == supplement[field], f"report/binding {field} differs from supplement")
    need(report.get("passed") is True, "inner report did not pass")
    need(binding["system_report_sha256"] == report_sha, "report digest differs from binding")
    need(report["coordinator_evidence"].get(REFERENCE_KEY) ==
         {"schema": SCHEMA, "filename": FILENAME, "sha256": supplement_sha}, "supplement reference differs")
    need(report["run_id"] == supplement["runtime_run_id"] and report["cleanup_status"] == supplement["cleanup"],
         "report cleanup or runtime run differs")
    need(report["mcp_readback_digest"] == supplement["mcp_readback_digest"], "MCP observations disagree")
    need([{k: step[k] for k in ("step_name", "status")} for step in report["step_results"]] == supplement["steps"],
         "scenario observations disagree")
    labels = report["candidate_image_labels"]
    for key, value in {"io.repomap.d12.grant_id": proof["nonce"],
        "io.repomap.d12.source_sha256": proof["d12_context"]["source_sha256"],
        "io.repomap.d12.recipe_sha256": proof["d12_context"]["recipe_sha256"]}.items():
        need(labels.get(key) == value, "candidate image D12 label differs from host grant")
    expected_versions = {"postgresql": POSTGRES_RELEASE_VERSION, "python": PYTHON_RELEASE_VERSION,
        "go": GO_RELEASE_VERSION, "psycopg": PSYCOPG_RELEASE_VERSION,
        "libpq": str(proof["release_manifest"]["libpq_version"])}
    need(all(report["release_version_checks"].get(key) == value for key, value in expected_versions.items()),
         "report release versions differ from admitted runtime")
    validate_successful_system_runtime(report, binding, report_file=REPORT_FILENAME)
    return {"schema": SCHEMA, "supplement_sha256": supplement_sha, "proof_sha256": proof_sha,
            "export_verified": True, "candidate_sha": proof["candidate_sha"], "candidate_tree": proof["candidate_tree"]}
