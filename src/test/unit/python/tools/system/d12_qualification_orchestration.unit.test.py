"""Conditional system results and failure-safe post-export validation, with injected images."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import test_sandbox as sandbox
from tools.system import d12_qualification_export as exported
from tools.system import d12_export_manifest as host_manifest
from tools.system.config import SystemDeadline, SystemTestError
from tools.system.d12_qualification import REFERENCE_KEY
from tools.system.report import SystemSuiteResult
from tools.system.runner_execution import execute_system_run
from src.test.unit.python.tools.system.d12_system_session_fixtures import _make_config
from src.test.unit.python.tools.sandbox_test_fixtures import (
    _capacity_boundary as _capacity_boundary, completed, finished_follower,
)
from src.test.unit.python.tools.sandbox_hosted_test_fixtures import report_archive


@pytest.mark.parametrize("failure", [None, "qualification", "cleanup", "scenario"])
def test_runner_qualifies_only_after_scenarios_probes_and_cleanup(tmp_path, failure):
    config = _make_config(tmp_path / "report")
    calls, results = [], []
    image_id = "sha256:" + "f" * 64
    session = SimpleNamespace(image_id=image_id, temp_container_ids=[],
        proof={"release_manifest": {"libpq_version": 180006}},
        run_same_daemon_preflight=lambda **_kw: calls.append("preflight"),
        cleanup_temp_containers=lambda _client: [], close_lock=lambda: calls.append("unlock"))
    def scenarios(*_a, **_kw):
        calls.append("scenarios")
        if failure == "scenario":
            raise SystemTestError("injected scenario failure")
        return (), {}, {"recovered_terminal_state": "succeeded"}, "a" * 64
    def probes(*_a, **kwargs):
        assert kwargs["upstream_informational"] is True
        calls.append("probes")
    def qualify(*_a, **kwargs):
        calls.append("qualify")
        if failure == "qualification":
            raise SystemTestError("injected evidence failure")
        assert kwargs["diagnostic_steps_passed"] is (failure != "scenario")
        return {"schema": "unit-injected", "filename": "unit.json", "sha256": "e" * 64}
    rc = execute_system_run(repo_root=tmp_path, candidate_tree_sha=config.candidate_tree_sha,
        execution_mode="hosted_qualification", config=config, deadline=SystemDeadline(1500, 120),
        timer=SimpleNamespace(check_budget=lambda: None), docker_boundary=SimpleNamespace(client=object()),
        fixture_dir=tmp_path / "fixture", compose_dir=tmp_path / "absent-compose", repo_map_home=tmp_path / "home",
        evidence_dir=tmp_path / "evidence", system_start_epoch_env="REPOMAP_UNIT_D12_START_EPOCH",
        system_suite_result_cls=SystemSuiteResult, materialize_fixture_repository_fn=lambda _p: None,
        build_and_verify_candidate_image_fn=lambda *_a, **_k: SimpleNamespace(image_id=image_id,
            image_digest=image_id, labels={}, release_versions={}, created_image_ids=(image_id,)),
        prepare_system_compose_topology_fn=lambda *_a, **_k: (object(), None, None, {}),
        execute_all_scenarios_fn=scenarios, load_plan_env_fn=lambda _p: {},
        perform_system_cleanup_fn=lambda **_k: {"success": failure != "cleanup", "errors": []},
        write_system_report_fn=lambda result, **_k: results.append(result), d12_session=cast(Any, session),
        run_post_build_candidate_probes_fn=probes, run_disposable_roundtrip_probe_fn=lambda *_a, **_k: None,
        write_qualification_fn=qualify)
    assert rc == (0 if failure is None else 1)
    assert results[0].passed is (failure is None)
    assert results[0].merge_authorized is (failure is None)
    assert calls.index("preflight") < calls.index("probes") < calls.index("scenarios") < calls.index("qualify")
    assert calls[-1] == "unlock"
    if failure is None:
        assert REFERENCE_KEY in results[0].coordinator_evidence


@pytest.mark.parametrize("failure", [None, "verification", "outer_cleanup", "export_missing", "archive_reader_error", "export_error"])
def test_outer_command_requires_export_verification_and_still_cleans_up(tmp_path, monkeypatch, failure):
    proof = tmp_path / "host-proof.json"; proof.write_bytes(b'{"host-selected":true}\n')
    outer_id, calls, verifications = "d" * 64, [], []
    empty = sandbox.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())
    def runner(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="0\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        if failure == "outer_cleanup" and command[:2] == ["docker", "rm"]:
            return completed(command, status=1)
        return completed(command)
    def verifier(directory, *, repo_root, expected_proof_bytes, expected_export_manifest_bytes):
        assert expected_export_manifest_bytes == b"host-manifest"
        verifications.append((directory, repo_root, expected_proof_bytes))
        if failure == "verification":
            raise ValueError("injected malformed exported evidence")
        return {"export_verified": True}
    monkeypatch.setattr(exported, "verify_exported_qualification", verifier)
    monkeypatch.setattr(host_manifest, "retain_host_manifest", lambda *_a, **_kw: b"host-manifest")
    def read_archive(*_a):
        if failure == "archive_reader_error":
            raise ValueError("injected malformed archive reader result")
        return None if failure == "export_missing" else report_archive({"index.html": "unit"})
    if failure == "export_error":
        def broken_export(*_a):
            raise ValueError("injected exporter error")
        monkeypatch.setattr(sandbox, "_export_sandbox_report", broken_export)
    rc = sandbox.run_in_sandbox(["--suite", "system", "--report", "--report-dir", str(tmp_path / "export"),
        "--d12-system-proof-json", str(proof)], repo_root=tmp_path, image_id="sha256:" + "e" * 64,
        runner=runner, follower_factory=finished_follower, snapshotter=lambda _r: empty,
        boundary_prover=lambda *_a, **_kw: None,
        archive_reader=read_archive)
    assert rc == (0 if failure is None else 2)
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    if failure not in ("export_missing", "archive_reader_error", "export_error"):
        assert verifications == [(tmp_path / "export", tmp_path, proof.read_bytes())]
