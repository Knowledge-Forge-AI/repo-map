"""Qualification accepts upstream diagnostics and rejects damaged or foreign evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ci.d12_hosted_reports import VERIFIED_AMD64_BASE_METADATA
from ci.gate_contract_bindings import GateBindingError, GateRequest, MergeCandidate
from ci.gate_contract_results import build_result
from common_lore_index.runtime.release import GO_RELEASE_VERSION, POSTGRES_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION, PYTHON_RELEASE_VERSION
from common_lore_index.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION
from tools.system.config import SystemTestError
from tools.system.d12_debian_policy import assess_debian_delta
from tools.system import d12_qualification as qualification
from tools.system import d12_qualification_export as exported
from tools.system.d12_export_manifest import manifest_from_archive, retain_host_manifest
from src.test.unit.python.tools.sandbox_hosted_test_fixtures import report_archive
from tools.system.report import SystemStepResult, SystemSuiteResult, write_system_report
from src.test.unit.python.tools.system.d12_system_session_fixtures import _establish, _matching_preflight_report
from src.test.unit.python.tools.system.d12_qualification_fixtures import (
    _valid_inventory, _valid_packaging_report, _valid_linkage_report, _valid_round_trip,
)


def complete_inventory():
    inventory = _valid_inventory()
    inventory.update(schema="repomap-d12-complete-inventory-v2",
        source_packages=[[row[0], row[0], row[1]] for row in inventory["packages"]],
        dpkg_configs={"/etc/dpkg/dpkg.cfg": "d" * 64}, path_filters=[],
        package_verification={"count": 1, "rows": [{"package": "libc6", "status": "missing", "conffile": False,
            "path": "/usr/share/doc/libc6/NEWS", "raw": "missing /usr/share/doc/libc6/NEWS"}],
            "checks": [{"package": row[0], "md5sums_sha256": "d" * 64} for row in inventory["packages"]]})
    return inventory


def make_bundle(tmp_path, monkeypatch, *, verification_rows=1):
    session, context = _establish(tmp_path)
    report = _matching_preflight_report(context)
    for metadata in VERIFIED_AMD64_BASE_METADATA.values():
        report["bases"][metadata["reference"]]["id"] = metadata["config"]
    candidate = complete_inventory()
    if verification_rows > 1:
        verification = candidate["package_verification"]
        verification["rows"] = [{**verification["rows"][0],
            "path": f"/usr/share/doc/libc6/retained-slim-observation-{number:05d}",
            "raw": f"missing /usr/share/doc/libc6/retained-slim-observation-{number:05d}"}
            for number in range(verification_rows)]
        verification["count"] = verification_rows
    report["server_inventory"] = copy.deepcopy(candidate)
    session.run_same_daemon_preflight(explore_fn=lambda *_a, **_kw: report)
    session.reserve_one_use_candidate_build()
    session.image_id = "sha256:" + "f" * 64
    directory = session.config.report_dir
    assert directory is not None
    stages = {"postgres": {row["resolved"]: row["sha256"] for row in candidate["files"]}, "python": {}}
    delta = assess_debian_delta(candidate, candidate, stages)
    payloads = {
        "candidate": candidate, "server": copy.deepcopy(candidate),
        "inventory": {"packaging": _valid_packaging_report(), "linkage": _valid_linkage_report(), "stage_hashes": stages},
        "assessment": {"qualification": "runtime_qualified", "debian_policy": delta,
            "availability": {"platform": "linux/amd64", "execution": "native"},
            "server_side": _valid_packaging_report()["versions"], "round_trip": _valid_round_trip(),
            "findings": [{"class": "outside_affected_range"}], "libpq_findings": [{"class": "outside_affected_range"}],
            "upstream_diagnostics": ["Debian OS finding: affected critical", "Debian OS finding: unknown"],
            "critical_unknown": [], "stops": []},
    }
    for key, value in payloads.items():
        (directory / qualification.PARTS[key]).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    session.roundtrip_evidence = _valid_round_trip()
    cleanup = {"success": True, "terminal_absence_verified": True, "errors": []}
    steps = tuple(SystemStepResult(step_name=name, status="passed", duration_seconds=.1) for name in sorted(qualification.STEPS))
    reference = qualification.write_qualification(session, config=session.config,
        candidate_image_id=session.image_id, candidate_image_digest=session.image_id,
        candidate_image_labels=session.candidate_d12_labels(), step_results=steps, mcp_readback_digest="e" * 64,
        cleanup_status=cleanup, temp_cleanup_errors=[], diagnostic_steps_passed=True, error_message="",
        evidence_dir=tmp_path / "evidence")
    config = session.config
    result = SystemSuiteResult(candidate_image_id=session.image_id, candidate_image_tag=config.candidate_tag,
        candidate_tree_sha=config.candidate_tree_sha, run_id=config.run_id, passed=True, total_duration_seconds=10.,
        step_results=steps, candidate_commit_sha=config.candidate_commit_sha, gate_kind=config.gate_kind,
        approval_id=config.approval_id, pr_number=config.pr_number, repository=config.repository,
        approved_base_branch=config.approved_base_branch, approved_base_sha=config.approved_base_sha,
        approved_head_branch=config.approved_head_branch, approved_head_sha=config.approved_head_sha,
        candidate_base_parent=config.candidate_base_parent, candidate_head_parent=config.candidate_head_parent,
        candidate_image_digest=session.image_id, candidate_image_labels=session.candidate_d12_labels(),
        release_version_checks={"postgresql": POSTGRES_RELEASE_VERSION, "python": PYTHON_RELEASE_VERSION,
            "go": GO_RELEASE_VERSION, "psycopg": PSYCOPG_RELEASE_VERSION, "libpq": str(D12_CANDIDATE_LIBPQ_VERSION)},
        coordinator_evidence={"recovered_terminal_state": "succeeded", qualification.REFERENCE_KEY: reference},
        mcp_readback_digest="e" * 64, cleanup_status=cleanup, execution_mode="hosted_qualification")
    write_system_report(result, report_dir=directory)
    # Synthetic candidate SHA has no Git object; test only the committed-source acquisition seam here.
    expected_sources = qualification.policy_hashes(session.repo_root)
    monkeypatch.setattr(exported, "policy_hashes", lambda *_a, **_kw: expected_sources)
    session.close_lock()
    archive = report_archive({path.name: path.read_text() for path in directory.glob("*.json")})
    manifest = (json.dumps(manifest_from_archive(archive, session.proof_path.read_bytes()), indent=2, sort_keys=True) + "\n").encode()
    return session, directory, manifest


def test_exported_qualification_recomputes_valid_runtime_with_affected_unknown_debian(tmp_path, monkeypatch):
    session, directory, manifest = make_bundle(tmp_path, monkeypatch)
    result = exported.verify_exported_qualification(directory, repo_root=session.repo_root,
        expected_proof_bytes=session.proof_path.read_bytes(), expected_export_manifest_bytes=manifest)
    assert result["export_verified"] is True
    assert result["proof_sha256"] == session.proof_sha256


def test_complete_slim_sized_bundle_fits_existing_transport_and_part_limits(tmp_path, monkeypatch):
    # The native suppliers produced 3,649 / 3,558 rows and 857 / 927 kB parts.
    # Exercise the whole writer/export/verifier with a larger synthetic observation.
    from repomap_test_support import d12_core_image as d12

    session, directory, manifest = make_bundle(tmp_path, monkeypatch, verification_rows=4000)
    sizes = {path.name: path.stat().st_size for path in directory.glob("*.json")}
    assert sizes[qualification.PARTS["candidate"]] > 927_172
    assert max(sizes.values()) < d12.REPORT_PART_LIMIT
    assert sum(sizes.values()) < d12.REPORT_TOTAL_LIMIT - d12.REPORT_CLEANUP_RESERVE
    from test_sandbox_contract import MAX_REPORT_CONTENT_BYTES, MAX_REPORT_MEMBERS
    from test_sandbox_report import export_sandbox_report

    archive = report_archive({path.name: path.read_text() for path in directory.glob("*.json")})
    destination = tmp_path / "actual-export"
    export_sandbox_report(archive, destination, max_members=MAX_REPORT_MEMBERS,
                          max_content_bytes=MAX_REPORT_CONTENT_BYTES)
    assert exported.verify_exported_qualification(destination, repo_root=session.repo_root,
        expected_proof_bytes=session.proof_path.read_bytes(), expected_export_manifest_bytes=manifest)["export_verified"]


@pytest.mark.parametrize("damage", ["part_bytes", "missing_part", "part_symlink", "wrong_proof", "foreign_policy",
    "missing_supplement", "supplement_reference", "failed_scenario", "cleanup", "foreign_image", "missing_label"])
def test_exported_qualification_refuses_damaged_evidence(tmp_path, monkeypatch, damage):
    session, directory, manifest = make_bundle(tmp_path, monkeypatch)
    proof_bytes = session.proof_path.read_bytes()
    if damage == "part_bytes":
        (directory / qualification.PARTS["candidate"]).write_text('{}\n')
    elif damage == "missing_part":
        (directory / qualification.PARTS["server"]).unlink()
    elif damage == "part_symlink":
        file = directory / qualification.PARTS["server"]
        copied = tmp_path / "outside.json"; copied.write_bytes(file.read_bytes()); file.unlink(); file.symlink_to(copied)
    elif damage == "wrong_proof":
        proof_bytes += b' '
    elif damage == "foreign_policy":
        monkeypatch.setattr(exported, "policy_hashes", lambda *_a, **_kw: {})
    elif damage == "missing_supplement":
        (directory / qualification.FILENAME).unlink()
    else:
        path = directory / exported.REPORT_FILENAME
        report = json.loads(path.read_text())
        if damage == "supplement_reference":
            report["coordinator_evidence"][qualification.REFERENCE_KEY]["filename"] = "../foreign.json"
        elif damage == "failed_scenario":
            report["step_results"][0]["status"] = "failed"
        elif damage == "cleanup":
            report["cleanup_status"]["terminal_absence_verified"] = False
        elif damage == "foreign_image":
            report["candidate_image_id"] = "sha256:" + "a" * 64
        elif damage == "missing_label":
            report["candidate_image_labels"] = {}
        path.write_text(json.dumps(report))
    with pytest.raises((SystemTestError, RuntimeError, ValueError)):
        exported.verify_exported_qualification(directory, repo_root=session.repo_root, expected_proof_bytes=proof_bytes, expected_export_manifest_bytes=manifest)


def test_policy_acquisition_refuses_uncommitted_or_missing_candidate_blobs(tmp_path):
    with pytest.raises(SystemTestError):
        qualification.policy_hashes(tmp_path, candidate_sha="a" * 40)


def test_successful_report_cannot_replace_missing_runtime_observations(tmp_path, monkeypatch):
    session, directory, manifest = make_bundle(tmp_path, monkeypatch)
    file = directory / qualification.PARTS["assessment"]
    data = json.loads(file.read_text()); data["round_trip"]["restored"]["fixture_rows"] = 1
    file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    # Rehashing every inner claim cannot replace the independent host archive manifest.
    supplement_file = directory / qualification.FILENAME
    supplement = json.loads(supplement_file.read_text())
    supplement["parts"]["assessment"] = hashlib.sha256(file.read_bytes()).hexdigest()
    supplement_file.write_text(json.dumps(supplement))
    with pytest.raises(SystemTestError, match="host-retained archive"):
        exported.verify_exported_qualification(directory, repo_root=session.repo_root,
            expected_proof_bytes=session.proof_path.read_bytes(), expected_export_manifest_bytes=manifest)


def test_postgresql_component_findings_remain_blocking(tmp_path, monkeypatch):
    session, directory, manifest = make_bundle(tmp_path, monkeypatch)
    file = directory / qualification.PARTS["assessment"]
    data = json.loads(file.read_text()); data["findings"][0]["class"] = "affected"
    file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemTestError, match="host-retained archive"):
        exported.verify_exported_qualification(directory, repo_root=session.repo_root,
            expected_proof_bytes=session.proof_path.read_bytes(), expected_export_manifest_bytes=manifest)


def test_committed_policy_acquisition_covers_transitive_source_and_untracked_python(tmp_path):
    root = Path(__file__).resolve().parents[6]
    for relative in qualification.POLICY_PATHS:
        target = tmp_path / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    transitive = tmp_path / "tools/transitive.py"; transitive.write_text('VALUE = 1\n')
    def git(*arguments):
        return subprocess.run(["git", "-c", "user.name=RepoMap Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgSign=false", "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *arguments],
            cwd=tmp_path, capture_output=True, check=True).stdout.decode().strip()
    git("init"); git("add", "."); git("commit", "-m", "Synthetic source acquisition fixture")
    commit = git("rev-parse", "HEAD")
    assert qualification.policy_hashes(tmp_path, candidate_sha=commit) == qualification.policy_hashes(tmp_path)
    transitive.write_text('VALUE = 2\n')
    with pytest.raises(SystemTestError, match="tracked candidate source differs"):
        qualification.policy_hashes(tmp_path, candidate_sha=commit)
    transitive.write_text('VALUE = 1\n'); (tmp_path / "foreign.py").write_text('VALUE = 3\n')
    with pytest.raises(SystemTestError, match="untracked Python"):
        qualification.policy_hashes(tmp_path, candidate_sha=commit)


def test_gate_result_requires_host_authority_even_if_report_markers_are_stripped(tmp_path, monkeypatch):
    session, directory, manifest = make_bundle(tmp_path, monkeypatch)
    config = session.config
    request = GateRequest(config.gate_kind, int(config.pr_number), config.approved_base_branch,
        config.approved_base_sha, config.approved_head_branch, config.approved_head_sha, config.approval_id, config.repository)
    candidate = MergeCandidate(config.candidate_commit_sha, config.candidate_tree_sha,
        config.candidate_base_parent, config.candidate_head_parent)
    arguments: dict[str, Any] = dict(request=request, candidate=candidate, conclusion="success",
        system_report_path=directory / exported.REPORT_FILENAME, system_binding_path=directory / exported.BINDING_FILENAME)
    result = build_result(**arguments, d12_expected_proof_bytes=session.proof_path.read_bytes(),
        d12_expected_export_manifest_bytes=manifest, repo_root=session.repo_root)
    assert result["merge_authorized"] is True
    report_path = directory / exported.REPORT_FILENAME; binding_path = directory / exported.BINDING_FILENAME
    report = json.loads(report_path.read_text()); binding = json.loads(binding_path.read_text())
    report["candidate_image_labels"] = {}; report["coordinator_evidence"].pop(qualification.REFERENCE_KEY)
    report_path.write_text(json.dumps(report)); binding["candidate_image_labels"] = {}
    binding["system_report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    binding_path.write_text(json.dumps(binding))
    with pytest.raises(GateBindingError, match="retained expected host proof and export manifest"):
        build_result(**arguments)


def test_host_export_receipt_is_exclusive_and_outside_exported_report(tmp_path, monkeypatch):
    session, directory, expected = make_bundle(tmp_path, monkeypatch)
    archive = report_archive({path.name: path.read_text() for path in directory.glob("*.json")})
    actual = retain_host_manifest(archive, expected_proof_bytes=session.proof_path.read_bytes(),
                                 host_proof_path=session.proof_path)
    assert actual == expected
    receipt = session.proof_path.parent / "export-manifest.json"
    assert receipt.parent != directory and receipt.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemTestError, match="already exists"):
        retain_host_manifest(archive, expected_proof_bytes=session.proof_path.read_bytes(), host_proof_path=session.proof_path)
