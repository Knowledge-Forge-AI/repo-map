"""Unit tests for post-build D12 candidate probes, disposable round-trip, and sidecar emission."""

from __future__ import annotations

import copy, hashlib, json, subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from ci.d12_hosted_evidence import validate_expected_candidate_record
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH, DEFAULT_GRANT_RELPATH, build_system_admission_proof,
    load_and_validate_system_build_grant, write_system_admission_proof,
)
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, POSTGRES_RELEASE_VERSION,
    PYTHON_RELEASE_IMAGE,
)
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST
from repomap_test_support import resource_run as resource_run_mod
from repomap_test_support.d12_image_probes import CLIENTS, SERVER
from tools.system import d12_system_evidence as evidence_mod, d12_system_session as session_mod
from tools.system.config import SystemDeadline, SystemTestConfig, SystemTestError, SystemTimeoutError
from tools.system.d12_system_evidence import (
    APPROVED_DIAGNOSTIC_STOPS, D12CandidateAssessmentError, SYSTEM_CANDIDATE_EVIDENCE_FILENAME,
    SYSTEM_CANDIDATE_EVIDENCE_SCHEMA, build_and_write_d12_system_candidate_evidence,
    observe_and_assess_candidate, run_disposable_roundtrip_probe,
    run_post_build_candidate_probes, validate_d12_system_candidate_evidence,
)
from tools.system.d12_system_session import D12SystemSession
from tools.system.report import SystemStepResult

REPO_ROOT = Path(__file__).resolve().parents[6]
BASE_SHA = "5ad00d162ad8a04430874275246a53227578c533"
LIBC, SRV_IMAGE = "/usr/lib/x86_64-linux-gnu/libc.so.6", "sha256:" + "5" * 64


@pytest.fixture(autouse=True)
def _ensure_canonical_resource_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    current = resource_run_mod.active_resource_run()
    if current is not None:
        return current
    run_root = tmp_path / "run-d12-ev"
    fake_run = SimpleNamespace(
        ledger=SimpleNamespace(identity=SimpleNamespace(run_id=run_root.name)),
        layout=SimpleNamespace(run_root=run_root),
    )
    monkeypatch.setattr(resource_run_mod, "active_resource_run", lambda: fake_run)
    monkeypatch.setattr(session_mod, "active_resource_run", lambda: fake_run)
    monkeypatch.setattr(evidence_mod, "active_resource_run", lambda: fake_run)
    return fake_run


def _active_run_id() -> str:
    run = session_mod.active_resource_run()
    return str(run.ledger.identity.run_id) if run is not None else "run-d12-ev"


def _matching_preflight_report(d12_ctx: dict[str, Any]) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    zero_counts = {
        "managed_system_candidate_image_build_count": 0, "product_or_build_profile_build_count": 0,
        "unmanaged_build_count": 0, "unmanaged_pull_count": 0,
    }
    return {
        "mode": "exploration", "result": "observed", "refusals": [],
        "availability": {"platform": "linux/amd64", "execution": "native", "builder_platforms": ["linux/amd64"]},
        "bases": {
            POSTGRES_RELEASE_IMAGE: {"id": "sha256:" + "1" * 64},
            PYTHON_RELEASE_IMAGE: {"id": "sha256:" + "2" * 64},
            GO_RELEASE_IMAGE: {"id": "sha256:" + "3" * 64},
        },
        "bindings": {"run_id": _active_run_id(), "daemon_id": "daemon-1"},
        "identity": dict(d12_ctx),
        "steps": {
            "libpq5_version": pkg.libpq5_version,
            "candidate": {
                "architecture": "amd64", "manifest": pkg._asdict(), "libpq_version": D12_CANDIDATE_LIBPQ_VERSION,
                "package_forecast": D12_CANDIDATE_LIBPQ_VERSION,
                "libpq_label": "runtime PQlibVersion; forecast is equality only",
                "written_to_source": False, "valid": True,
            },
            "libpq_runtime": {
                "api": D12_CANDIDATE_LIBPQ_VERSION,
                "library": {
                    "path": pkg.libpq_path, "sha256": pkg.libpq_sha256, "package": "libpq5",
                    "version": pkg.libpq5_version, "architecture": "amd64",
                },
            },
        },
        "server_inventory": {
            "files": [{"role": "libpq", "owner": "libpq5", "resolved": pkg.libpq_path, "sha256": pkg.libpq_sha256}],
            "packages": [["libpq5", pkg.libpq5_version, "amd64"]],
        },
        "cleanup": {
            "server": "removed", "containers": "baseline_verified",
            "budget": dict(zero_counts), "zero_build": dict(zero_counts),
        },
    }


def _setup_session(tmp_path: Path, *, reserve_intent: bool = True) -> D12SystemSession:
    live_cand_path, grant_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH, REPO_ROOT / DEFAULT_GRANT_RELPATH
    raw_grant, _ = load_and_validate_system_build_grant(grant_path)
    live_cand = validate_expected_candidate_record(json.loads(live_cand_path.read_text(encoding="utf-8")))
    expected_cand = validate_expected_candidate_record(
        {**live_cand, "d12_context": dict(raw_grant["d12_context"])}
    )
    cand_path = tmp_path / "ci72-candidate.json"
    cand_raw = (json.dumps(expected_cand, indent=2, sort_keys=True) + "\n").encode("utf-8")
    cand_path.write_bytes(cand_raw)
    cand_sha = hashlib.sha256(cand_raw).hexdigest()
    d12_ctx = dict(expected_cand["d12_context"])
    grant, grant_sha = load_and_validate_system_build_grant(
        grant_path, expected_candidate=expected_cand, frozen_identity=d12_ctx
    )
    (ev := tmp_path / "event.json").write_text(json.dumps({"number": 23, "draft": True}), encoding="utf-8")
    proof = build_system_admission_proof(
        grant=grant, grant_sha256=grant_sha, expected_candidate_sha256=cand_sha,
        raw_event_sha256=hashlib.sha256(ev.read_bytes()).hexdigest(),
        after="d" * 40, candidate_sha="a" * 40, candidate_tree="b" * 40,
        candidate_base_parent=str(grant["base"]), candidate_head_parent="d" * 40, run_id="12345678",
        native_host={"runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux", "host_arch": "x86_64"},
    )
    proof_file = tmp_path / "proof-dir" / "proof.json"
    write_system_admission_proof(proof_file, proof)
    config = SystemTestConfig.create(
        timeout_seconds=1500, report_dir=tmp_path / "report", candidate_tree_sha="b" * 40,
        run_id=_active_run_id(), gate_kind="main-system", approval_id="pr-23", pr_number="23",
        repository="Knowledge-Forge-AI/repo-map", approved_base_branch="main", approved_base_sha=BASE_SHA,
        approved_head_branch="staging", approved_head_sha="d" * 40, candidate_commit_sha="a" * 40,
        candidate_base_parent=BASE_SHA, candidate_head_parent="d" * 40, execution_mode="hosted_qualification",
    )

    def fake_git(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        mapping = {"HEAD": "a" * 40, "HEAD^{tree}": "b" * 40, "HEAD^1": BASE_SHA, "HEAD^2": "d" * 40}
        return subprocess.CompletedProcess(cmd, 0, mapping[cmd[-1]] + "\n", "")

    session = D12SystemSession.establish(
        repo_root=REPO_ROOT, config=config, proof_json_arg=str(proof_file), target_arch_fn=lambda: "amd64",
        tree_sha_fn=lambda _r: "b" * 40, frozen_identity_fn=lambda _r, _p: d12_ctx, run_git_fn=fake_git,
        expected_candidate_path=cand_path,
    )
    session.run_same_daemon_preflight(explore_fn=lambda *_a, **_kw: _matching_preflight_report(d12_ctx))
    if reserve_intent:
        session.reserve_one_use_candidate_build()
    return session


from src.test.unit.python.tools.system.d12_qualification_fixtures import (
    _valid_packaging_report, _valid_linkage_report, _valid_inventory, _valid_round_trip,
)


def test_observe_and_assess_candidate_validates_gates_and_refuses_defects(monkeypatch: pytest.MonkeyPatch) -> None:
    # This case preserves ADR0101's historical finite-base policy. Current qualification uses ADR0105.
    monkeypatch.setattr(evidence_mod, "POSTGRES_RELEASE_IMAGE",
        "postgres:16.15-trixie@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97")
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    server_side = {p: f"postgres (PostgreSQL) {POSTGRES_RELEASE_VERSION}" for p in (SERVER, *CLIENTS)}
    srv_env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": "secret"}
    avail = {"platform": "linux/amd64", "execution": "native"}
    with pytest.raises(ValueError, match="expected_libpq_version"):
        observe_and_assess_candidate(
            None, None, image_id="sha256:" + "1" * 64, platform="linux/amd64", server_id="srv-1",
            server_env=srv_env, server_side=server_side, server_inventory=_valid_inventory(),
            availability=avail, expected_libpq_version=None, server_image_id=SRV_IMAGE,
        )

    def _make_run_once(
        packaging: dict[str, Any], linkage_rep: dict[str, Any], rt: dict[str, Any]
    ) -> Any:
        def _fake_run_once(*_a: object, role: str = "", **_kw: object) -> str:
            if role == "d12-packaging":
                return json.dumps(packaging)
            if role == "d12-linkage":
                return json.dumps(linkage_rep)
            return json.dumps(rt)
        return _fake_run_once

    common: dict[str, Any] = {
        "image_id": "sha256:" + "1" * 64, "platform": "linux/amd64", "server_id": "srv-1", "server_env": srv_env,
        "server_side": server_side, "server_inventory": _valid_inventory(), "availability": avail,
        "inventory_fn": lambda *_a, **_kw: copy.deepcopy(_valid_inventory()),
        "hashes_fn": lambda *_a, **_kw: {pkg.libpq_path: pkg.libpq_sha256, LIBC: "e" * 64}}
    good_run_once = _make_run_once(_valid_packaging_report(), _valid_linkage_report(), _valid_round_trip())
    reports: dict[str, dict[str, Any]] = {}
    out = observe_and_assess_candidate(
        None, None, **common, expected_libpq_version=D12_CANDIDATE_LIBPQ_VERSION, server_image_id=SRV_IMAGE,
        write_report=lambda name, payload: reports.setdefault(name, payload), run_once_fn=good_run_once)
    assert out["result"]["qualification"] == "stop_pending_disposition"
    assert out["result"]["stops"] == list(APPROVED_DIAGNOSTIC_STOPS)
    assert set(reports) == {"inventory", "result"}
    glibc = reports["result"]["glibc_disposition"]
    assert glibc["status"] == "accepted_unresolved" and glibc["image_qualified"] is False
    assert [(i["label"], i["image_id"]) for i in glibc["images"]] == [("candidate", "sha256:" + "1" * 64),
                                                                      ("server", SRV_IMAGE)]
    # Unknown service identity refuses despite the accepted risk; the refusal is retained before the run fails.
    refused: dict[str, dict[str, Any]] = {}
    with pytest.raises(D12CandidateAssessmentError, match="glibc disposition refused: server: image identity"):
        observe_and_assess_candidate(
            None, None, **common, server_image_id=None,
            write_report=lambda n, p: refused.setdefault(n, p), run_once_fn=good_run_once)
    assert refused["result"]["glibc_disposition"]["status"] == "refused"
    assert refused["result"]["stops"] == list(APPROVED_DIAGNOSTIC_STOPS)

    bad_rt = _valid_round_trip()
    bad_rt["restored"]["fixture_rows"] = 1
    with pytest.raises(D12CandidateAssessmentError, match="2000-row mismatch"):
        observe_and_assess_candidate(
            None, None, **common, server_image_id=SRV_IMAGE,
            run_once_fn=_make_run_once(_valid_packaging_report(), _valid_linkage_report(), bad_rt))

    with pytest.raises(D12CandidateAssessmentError, match="unattributed bytes"):
        observe_and_assess_candidate(
            None, None, **{**common, "hashes_fn": lambda *_a, **_kw: {}}, server_image_id=SRV_IMAGE,
            run_once_fn=good_run_once)


def test_post_build_probes_roundtrip_and_sidecar_keep_acceptance_false(tmp_path: Path) -> None:
    session = _setup_session(tmp_path)
    try:
        labels = session.candidate_d12_labels()
        owner = SimpleNamespace(cleanup=MagicMock(), verify_baseline=MagicMock())
        srv_container = SimpleNamespace(
            attrs={"Image": "sha256:" + "1" * 64},
            exec_run=lambda _cmd: SimpleNamespace(
                output=f"postgres (PostgreSQL) {POSTGRES_RELEASE_VERSION}\n".encode("utf-8")
            ),
        )
        inv_payload = {
            "candidate": _valid_inventory(), "server": _valid_inventory(),
            "packaging": _valid_packaging_report(), "linkage": _valid_linkage_report(),
        }
        res_payload = {
            "observed_versions": {"candidate": _valid_packaging_report()["versions"]},
            "tls_runtime": {"server": [["libssl3t64", "3.5.7-1~deb13u3", "amd64"]]},
            "findings": [], "libpq_findings": [], "critical_unknown": [],
            "availability": {"execution": "native"}, "glibc_disposition": {"status": "accepted_unresolved"},
            "qualification": "stop_pending_disposition",
            "stops": list(APPROVED_DIAGNOSTIC_STOPS),
            "round_trip": _valid_round_trip(),
        }

        seen: list[object] = []
        def fake_observe(*_a: object, write_report: Any = None, **_kw: object) -> dict[str, Any]:
            seen.append(_kw.get("server_image_id"))
            if write_report is not None:
                write_report("inventory", inv_payload)
                write_report("result", res_payload)
            return {"inventory": inv_payload, "result": res_payload}

        with pytest.raises(SystemTestError, match="must accept 'create_fn'"):
            run_post_build_candidate_probes(
                session, image_id="sha256:" + "1" * 64, image_labels=labels,
                owner=owner, client=MagicMock(),
                start_server_fn=lambda _o, _c, _e, _p: ("srv-cid-bad", srv_container),
                inventory_fn=lambda *_a, **_kw: _valid_inventory(),
                observe_fn=fake_observe,
            )

        with pytest.raises(SystemTestError, match="must accept 'deadline'"):
            run_post_build_candidate_probes(
                session, image_id="sha256:" + "1" * 64, image_labels=labels,
                deadline=SystemDeadline(1500, 120), owner=owner, client=MagicMock(),
                start_server_fn=lambda _o, _c, _e, _p, *, create_fn=None: ("srv-cid-bad", srv_container),
                inventory_fn=lambda *_a, **_kw: _valid_inventory(),
                observe_fn=fake_observe,
            )

        ticks = iter((0.0,))
        exhausted = SystemDeadline(1500, 120, clock=lambda: next(ticks, 2000.0))
        with pytest.raises(SystemTimeoutError, match="system test budget exhausted before d12 post-build probes"):
            run_post_build_candidate_probes(
                session, image_id="sha256:" + "1" * 64, image_labels=labels,
                deadline=exhausted, owner=owner, client=MagicMock(),
            )
        with pytest.raises(SystemTimeoutError, match="system test budget exhausted before d12 disposable round-trip"):
            run_disposable_roundtrip_probe(
                session, image_id="sha256:" + "1" * 64, deadline=exhausted,
            )

        bad_srv = SimpleNamespace(attrs={"Image": "sha256:" + "9" * 64}, exec_run=srv_container.exec_run)
        with pytest.raises(SystemTestError, match="server container image digest mismatch"):
            run_post_build_candidate_probes(
                session, image_id="sha256:" + "1" * 64, image_labels=labels,
                owner=owner, client=MagicMock(),
                start_server_fn=lambda *_a, **_kw: ("srv-cid-bad", bad_srv),
                inventory_fn=lambda *_a, **_kw: _valid_inventory(),
                observe_fn=fake_observe,
            )
        owner.cleanup.assert_called_once_with("srv-cid-bad")
        owner.cleanup.reset_mock()
        owner.verify_baseline.reset_mock()

        assert session.preflight_report is not None
        saved_bases = session.preflight_report.pop("bases", None)
        try:
            with pytest.raises(SystemTestError, match="observed PostgreSQL base image ID"):
                run_post_build_candidate_probes(
                    session, image_id="sha256:" + "1" * 64, image_labels=labels,
                    owner=owner, client=MagicMock(),
                    start_server_fn=lambda *_a, **_kw: ("srv-cid-1", srv_container),
                    inventory_fn=lambda *_a, **_kw: _valid_inventory(),
                    observe_fn=fake_observe,
                )
        finally:
            if saved_bases is not None:
                session.preflight_report["bases"] = saved_bases

        probes = run_post_build_candidate_probes(
            session, image_id="sha256:" + "1" * 64, image_labels=labels,
            owner=owner, client=MagicMock(),
            start_server_fn=lambda *_a, **_kw: ("srv-cid-1", srv_container),
            inventory_fn=(inv_fn := MagicMock(side_effect=lambda *_a, **_kw: _valid_inventory())),
            observe_fn=fake_observe,
        )
        assert probes["packaging"]["libpq"] == D12_CANDIDATE_LIBPQ_VERSION
        assert seen[-1] == inv_fn.call_args.args[2] == "sha256:" + "1" * 64  # server bytes and identity: base ID
        owner.cleanup.assert_called_once_with("srv-cid-1")
        owner.verify_baseline.assert_called_once()

        rt = run_disposable_roundtrip_probe(session, image_id="sha256:" + "1" * 64)
        assert rt["restored"]["fixture_rows"] == 2000

        written = build_and_write_d12_system_candidate_evidence(
            session, config=session.config, candidate_image_id="sha256:" + "1" * 64,
            candidate_image_digest="sha256:" + "2" * 64, candidate_image_labels=labels,
            step_results=(SystemStepResult("step_1_packaged_cluster_readiness", "passed", 1.2, "ok"),),
            mcp_readback_digest="3" * 64, cleanup_status={"success": True, "errors": []},
            temp_cleanup_errors=(), diagnostic_steps_passed=True, error_message="",
            evidence_dir=tmp_path / "evidence",
        )
        assert written is not None and written.name == SYSTEM_CANDIDATE_EVIDENCE_FILENAME
        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload["schema"] == SYSTEM_CANDIDATE_EVIDENCE_SCHEMA
        assert payload["sdk_sandbox"] == dict(session.expected_candidate["sdk_sandbox"])
        assert payload["diagnostic_steps_passed"] is True and payload["cleanup_succeeded"] is True
        assert payload["image_accepted"] is False and payload["p3_accepted"] is False
        assert payload["merge_authorized"] is False and payload["qualified"] is False
        assert payload["post_build_assessments"]["glibc_disposition"] == {"status": "accepted_unresolved"}

        with pytest.raises(SystemTestError, match="must remain False"):
            validate_d12_system_candidate_evidence({**payload, "p3_accepted": True})
    finally:
        session.close_lock()
