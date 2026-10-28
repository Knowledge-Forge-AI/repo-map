"""ADR0105 conditional D12 qualification, separate from historical diagnostic v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any

from ci.d12_system_grant import read_regular_json_object, validate_system_admission_proof
from ci.d12_hosted_state import VERIFIED_AMD64_BASE_METADATA
from repomap_test_support import d12_image_probes as d12
from tools.system.d12_candidate_assessment import verify_preflight_matches_manifest
from tools.system.config import SystemTestError
from tools.system.d12_candidate_assessment import _verify_candidate_assessment, _verify_round_trip
from tools.system.d12_debian_policy import assess_debian_delta
from tools.system.d12_system_reports import write_bounded_json_to_targets

SCHEMA = "repomap-d12-system-qualification-v2"
FILENAME = "d12-system-qualification-v2.json"
REFERENCE_KEY = "d12_qualification"
POLICY_PATHS = (
    "tools/ci/debian_stable_slim.json", "tools/system/d12_debian_policy.py",
    "tools/system/d12_candidate_assessment.py", "tools/system/d12_qualification.py",
    "tools/system/d12_qualification_export.py",
    "tools/system/d12_export_manifest.py",
)
PARTS = {
    "intent": "d12-system-build-intent.json", "preflight": "d12-preflight-exploration.json",
    "inventory": "d12-post-build-inventory.json", "assessment": "d12-post-build-result.json",
    "candidate": "d12-post-build-candidate-inventory.json", "server": "d12-post-build-server-inventory.json",
}
STEPS = frozenset({"packaged_cluster_readiness", "durable_coordinator_execution",
    "controlled_coordinator_interruption_recovery", "idempotency_and_fencing", "mcp_public_stdio_readback"})
AUTHORITY_FIELDS = ("nonce", "reservation_sha256", "grant_sha256", "expected_candidate_sha256",
    "run_id", "workflow_ordinal", "workflow_attempt", "candidate_sha", "candidate_tree",
    "candidate_base_parent", "candidate_head_parent", "d12_context", "release_manifest")


def need(condition: object, message: str) -> None:
    if not condition:
        raise SystemTestError(f"D12 qualification: {message}")


def read_part(path: Path) -> tuple[dict[str, Any], str]:
    data, _raw, digest = read_regular_json_object(path, label="D12 qualification part",
                                                max_bytes=d12.REPORT_PART_LIMIT)
    return data, digest


def policy_hashes(repo_root: Path, *, candidate_sha: str | None = None) -> dict[str, str]:
    """Outer verification uses committed blobs and refuses mutable workspace substitutes."""
    if candidate_sha is not None:
        need(re.fullmatch(r"[0-9a-f]{40}", candidate_sha), "invalid expected candidate SHA")
        # Bind every tracked assessor dependency, including transitive imports, to the committed candidate.
        result = subprocess.run(["git", "diff", "--quiet", "--no-ext-diff", "--no-textconv", candidate_sha, "--"], cwd=repo_root,
                                capture_output=True, check=False, timeout=30)
        need(result.returncode == 0, "tracked candidate source differs from committed host authority")
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
            cwd=repo_root, capture_output=True, check=False, timeout=15)
        need(untracked.returncode == 0 and not untracked.stdout, "untracked Python could change assessor imports")
    hashes = {}
    for relative in POLICY_PATHS:
        path = repo_root / relative
        need(path.is_file() and not path.is_symlink(), "policy input is missing or a symlink")
        raw = path.read_bytes()
        need(0 < len(raw) <= 200_000, "policy input exceeds its bound")
        if candidate_sha is not None:
            result = subprocess.run(["git", "show", f"{candidate_sha}:{relative}"], cwd=repo_root,
                capture_output=True, check=False, timeout=15)
            need(result.returncode == 0 and result.stdout == raw, "policy input differs from committed candidate")
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    return hashes


def verify_parts(directory: Path, proof: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Recompute functional and assembly checks from retained observations, not acceptance flags."""
    values, digests = {}, {}
    for name, filename in PARTS.items():
        values[name], digests[name] = read_part(directory / filename)
    preflight, intent = values["preflight"], values["intent"]
    verify_preflight_matches_manifest(preflight, proof=proof)
    for metadata in VERIFIED_AMD64_BASE_METADATA.values():
        need(preflight["bases"].get(metadata["reference"], {}).get("id") == metadata["config"],
             "preflight supplier config differs from pinned registry metadata")
    need(intent.get("schema") == "repomap-d12-system-build-intent-v1", "build intent schema differs")
    for key, expected in {
        "grant_id": proof["nonce"], "intent_id": proof["nonce"], "reservation_id": proof["nonce"],
        "reservation_sha256": proof["reservation_sha256"], "grant_sha256": proof["grant_sha256"],
        "preflight_sha256": digests["preflight"], "workflow_ordinal": proof["workflow_ordinal"],
        "workflow_attempt": proof["workflow_attempt"], "platform": "linux/amd64", "owner": "main-system-gate",
        "candidate_sha": proof["candidate_sha"], "candidate_tree": proof["candidate_tree"],
        "candidate_base_parent": proof["candidate_base_parent"], "candidate_head_parent": proof["candidate_head_parent"],
        "d12_source_sha256": proof["d12_context"]["source_sha256"],
        "d12_recipe_sha256": proof["d12_context"]["recipe_sha256"],
        "d12_dockerfile_sha256": proof["d12_context"]["dockerfile_sha256"],
    }.items():
        need(intent.get(key) == expected, f"build intent {key} differs from expected host authority")
    inventory, assessment = values["inventory"], values["assessment"]
    candidate, server = values["candidate"], values["server"]
    need(server == preflight["server_inventory"], "complete server inventory drifted after preflight")
    need(assessment.get("availability", {}).get("execution") == "native" and
         assessment.get("availability", {}).get("platform") == "linux/amd64", "execution was not native AMD")
    delta = assess_debian_delta(candidate, server, inventory.get("stage_hashes") or {})
    need(assessment.get("qualification") == "runtime_qualified" and assessment.get("debian_policy") == delta,
         "runtime assessment is absent or disagrees with actual assembly")
    _verify_candidate_assessment(packaging=inventory["packaging"], linkage_report=inventory["linkage"],
        candidate=candidate, server_side=assessment["server_side"], round_trip=assessment["round_trip"],
        findings=assessment["findings"], libpq=assessment["libpq_findings"],
        critical_unknown=assessment["critical_unknown"], stops=assessment["stops"],
        expected_libpq_version=proof["release_manifest"]["libpq_version"], upstream_informational=True)
    return values, digests


def verify_terminal(steps: Sequence[Mapping[str, Any]], cleanup: Mapping[str, Any], mcp_digest: str) -> None:
    names = [step.get("step_name") for step in steps]
    need(len(names) == len(STEPS) and set(names) == STEPS and all(s.get("status") == "passed" for s in steps),
         "all five unique scenario steps must pass")
    need(cleanup.get("success") is True and cleanup.get("terminal_absence_verified") is True
         and cleanup.get("errors") == [], "inner cleanup did not prove terminal absence")
    need(re.fullmatch(r"[0-9a-f]{64}", mcp_digest), "MCP readback digest is missing")


def write_qualification(
    session: Any, *, config: Any, candidate_image_id: str | None, candidate_image_digest: str,
    candidate_image_labels: Mapping[str, str], step_results: Sequence[Any], mcp_readback_digest: str,
    cleanup_status: Mapping[str, Any], temp_cleanup_errors: Sequence[str], diagnostic_steps_passed: bool,
    error_message: str, evidence_dir: Path,
) -> dict[str, str]:
    need(diagnostic_steps_passed and not error_message and not temp_cleanup_errors, "execution or cleanup failed")
    need(config.report_dir is not None and candidate_image_id == session.image_id, "candidate image identity missing")
    need(isinstance(candidate_image_id, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_image_id),
         "candidate image identity is not exact")
    need(candidate_image_digest == candidate_image_id, "local assembled image digest must be its observed config ID")
    for key, value in session.candidate_d12_labels().items():
        need(candidate_image_labels.get(key) == value, "candidate D12 label differs")
    proof = validate_system_admission_proof(session.proof)
    parts, digests = verify_parts(config.report_dir, proof)
    need(parts["intent"].get("proof_sha256") == session.proof_sha256, "intent refers to another host proof")
    steps = [{"step_name": step.step_name, "status": step.status} for step in step_results]
    verify_terminal(steps, cleanup_status, mcp_readback_digest)
    _verify_round_trip(session.roundtrip_evidence or {})
    payload = {
        "schema": SCHEMA, "policy": "ADR0105", "qualified": True,
        "authority": {key: proof[key] for key in AUTHORITY_FIELDS}, "proof_sha256": session.proof_sha256,
        "policy_sources": policy_hashes(session.repo_root), "parts": digests,
        "candidate_image_id": candidate_image_id, "candidate_image_digest": candidate_image_digest,
        "candidate_image_labels": dict(candidate_image_labels), "steps": steps,
        "mcp_readback_digest": mcp_readback_digest, "cleanup": dict(cleanup_status),
        "runtime_run_id": config.run_id, "round_trip": dict(session.roundtrip_evidence or {}),
        "upstream_debian_findings": "informational; no vulnerability-free or complete-catalogue claim",
        "incumbent_comparison": "unresolved under ADR0091; Samuel Leighton Lair",
    }
    targets = [config.report_dir, evidence_dir]
    write_bounded_json_to_targets(targets, FILENAME, payload, part_limit=d12.REPORT_PART_LIMIT,
        total_limit=d12.REPORT_TOTAL_LIMIT, cleanup_reserve=d12.REPORT_CLEANUP_RESERVE)
    _data, digest = read_part(config.report_dir / FILENAME)
    return {"schema": SCHEMA, "filename": FILENAME, "sha256": digest}
