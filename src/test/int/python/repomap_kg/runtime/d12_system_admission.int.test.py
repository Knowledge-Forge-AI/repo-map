"""Containerized integration tests for Route B D12 system admission, hold, and runner execution."""

from __future__ import annotations

import json, stat, subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ci.d12_hosted_evidence import SYSTEM_HOLD_REFUSAL_SCHEMA, validate_expected_candidate_record
from ci.d12_hosted_qualification import main as qualification_main
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH, DEFAULT_GRANT_RELPATH, D12SystemGrantError,
    SYSTEM_ADMISSION_PROOF_SCHEMA, load_and_validate_system_build_grant, verify_host_system_proof_for_dispatch,
)
from repomap_kg.runtime import release as release_mod
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST
from repomap_test_support import d12_core_image as d12, d12_recipe
from repomap_test_support.d12_image_probes import _create
from repomap_test_support.d12_system_test_children import (
    hold_exclusive_flock, poisoned_coverage_base_env, transfer_proof_locally,
)
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import ensure_canonical_runtime_image
from test_sandbox_arguments import sandbox_report_arguments
from test_sandbox_dispatch import integration_sandbox_dispatch
from tools.system.candidate_image import CandidateImageMetadata
from tools.system.compose_command import normalize_compose_args
from tools.system.compose_topology import APPLICATION_SERVICES, prepare_system_compose_topology
from tools.system.config import SystemDeadline, SystemTestConfig, SystemTestError
from tools.system.d12_exec import wrap_create_with_bounded_exec
from tools.system.d12_system_evidence import SYSTEM_CANDIDATE_EVIDENCE_FILENAME
from tools.system.d12_qualification import FILENAME as QUALIFICATION_FILENAME
from tools.system.d12_system_session import D12SystemSession, SYSTEM_BUILD_LOCK_FILENAME
from tools.system.report import SystemStepResult, SystemSuiteResult
from tools.system.runner_execution import execute_system_run
from tools.system.scenario import MonotonicTimer

REPO_ROOT = Path(__file__).resolve().parents[6]
BASE_SHA = "24d15650a2d4563d188acb8bbf34a0dabf8f3d65"


def _setup_hosted_pr_env(tmp_path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    cand_doc = json.loads((REPO_ROOT / DEFAULT_CANDIDATE_RELPATH).read_text(encoding="utf-8"))
    grant, _ = load_and_validate_system_build_grant(REPO_ROOT / DEFAULT_GRANT_RELPATH)
    expected_cand = validate_expected_candidate_record({**cand_doc, "d12_context": dict(grant["d12_context"])})
    (tmp_path / "ci72-candidate.json").write_text(json.dumps(expected_cand, indent=2, sort_keys=True) + "\n", "utf-8")
    event_path = tmp_path / "github_event.json"
    repo_info = {"full_name": grant["repository"], "fork": False}
    pr_payload = {
        "number": 13, "draft": True,
        "base": {"ref": "main", "sha": grant["base"], "repo": repo_info},
        "head": {"ref": "staging", "sha": "d" * 40, "repo": repo_info},
    }
    event_doc = {"action": "synchronize", "before": grant["before"], "after": "d" * 40,
                 "number": 13, "pull_request": pr_payload}
    event_path.write_text(json.dumps(event_doc), encoding="utf-8")
    wf_ref = f"{grant['repository']}/{grant['workflow_path']}@refs/pull/13/merge"
    env = {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": str(grant["repository"]), "GITHUB_BASE_REF": "main",
        "GITHUB_HEAD_REF": "staging", "GITHUB_WORKFLOW_REF": wf_ref,
        "GITHUB_RUN_NUMBER": str(grant["workflow_ordinal"]), "GITHUB_RUN_ID": "87654321",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40, "GITHUB_EVENT_PATH": str(event_path),
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "PR_NUMBER": "13",
    }
    return env, dict(expected_cand["d12_context"])


def _fake_git(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    rev = cmd[-1]
    mapping = {"HEAD": "a" * 40, "HEAD^{tree}": "b" * 40, "HEAD^1": BASE_SHA, "HEAD^2": "d" * 40}
    return (subprocess.CompletedProcess(cmd, 1, "", "no parent 3") if rev == "HEAD^3"
            else subprocess.CompletedProcess(cmd, 0, mapping[rev] + "\n", ""))


def _active_run_id() -> str:
    return str(r.ledger.identity.run_id) if (r := active_resource_run()) is not None else "int-run-d12"


def _matching_preflight_doc(d12_ctx: dict[str, Any]) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    zero = dict.fromkeys(
        ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
         "unmanaged_build_count", "unmanaged_pull_count"), 0,
    )
    return {
        "mode": "exploration", "result": "observed", "refusals": [],
        "availability": {"platform": "linux/amd64", "execution": "native", "builder_platforms": ["linux/amd64"]},
        "bases": {
            release_mod.POSTGRES_RELEASE_IMAGE: {"id": "sha256:" + "1" * 64},
            release_mod.PYTHON_RELEASE_IMAGE: {"id": "sha256:" + "2" * 64},
            release_mod.GO_RELEASE_IMAGE: {"id": "sha256:" + "3" * 64},
        },
        "bindings": {"run_id": _active_run_id(), "daemon_id": "daemon-1"},
        "identity": dict(d12_ctx),
        "steps": {
            "libpq5_version": pkg.libpq5_version,
            "candidate": {
                "architecture": "amd64", "manifest": pkg._asdict(), "libpq_version": D12_CANDIDATE_LIBPQ_VERSION,
                "package_forecast": D12_CANDIDATE_LIBPQ_VERSION,
                "libpq_label": "runtime PQlibVersion; forecast is equality only", "written_to_source": False,
                "valid": True,
            },
            "libpq_runtime": {
                "api": D12_CANDIDATE_LIBPQ_VERSION,
                "library": {
                    "path": pkg.libpq_path, "sha256": pkg.libpq_sha256,
                    "package": "libpq5", "version": pkg.libpq5_version, "architecture": "amd64",
                },
            },
        },
        "server_inventory": {
            "files": [{"role": "libpq", "owner": "libpq5", "resolved": pkg.libpq_path, "sha256": pkg.libpq_sha256}],
            "packages": [["libpq5", pkg.libpq5_version, "amd64"]],
        },
        "cleanup": {
            "server": "removed", "containers": "baseline_verified",
            "budget": dict(zero), "zero_build": dict(zero),
        },
    }


def _make_config(report_dir: Path, run_id: str | None = None) -> SystemTestConfig:
    return SystemTestConfig.create(
        timeout_seconds=1500, report_dir=report_dir, candidate_tree_sha="b" * 40,
        run_id=run_id or _active_run_id(), gate_kind="main-system", approval_id="pr-13", pr_number="13",
        repository="Knowledge-Forge-AI/repo-map", approved_base_branch="main", approved_base_sha=BASE_SHA,
        approved_head_branch="staging", approved_head_sha="d" * 40, candidate_commit_sha="a" * 40,
        candidate_base_parent=BASE_SHA, candidate_head_parent="d" * 40, execution_mode="hosted_qualification",
    )


def _hold_argv(out_path: Path, proof_path: Path | None = None) -> list[str]:
    argv = [
        "system-hold", "--repo-root", str(REPO_ROOT), "--candidate-sha", "a" * 40,
        "--candidate-tree", "b" * 40, "--candidate-base-parent", BASE_SHA,
        "--candidate-head-parent", "d" * 40, "--output-json", str(out_path),
    ]
    if proof_path is None:
        return argv
    return [*argv, "--proof-json", str(proof_path),
            "--expected-json", str(proof_path.parents[1] / "ci72-candidate.json")]


def test_system_hold_proof_capture_and_child_secure_writer(tmp_path: Path) -> None:
    assert release_mod.PSYCOPG_LIBPQ_VERSION is None and release_mod.DYNAMIC_PACKAGE_MANIFEST == {}
    assert d12_recipe.frozen_identity(REPO_ROOT, "linux/amd64") == d12.frozen_identity(REPO_ROOT, "linux/amd64")
    out_refused = tmp_path / "hold-refused.json"
    assert qualification_main(_hold_argv(out_refused)) == 1
    refused_doc = json.loads(out_refused.read_text(encoding="utf-8"))
    assert refused_doc["schema"] == SYSTEM_HOLD_REFUSAL_SCHEMA
    assert refused_doc["result"] == "refused_release_prerequisites_unresolved"
    assert refused_doc["qualified"] is False and refused_doc["sdk_builds_started"] == 0
    assert refused_doc["application_candidate_builds_started"] == 0

    env, d12_ctx = _setup_hosted_pr_env(tmp_path)
    adm_dir = tmp_path / "repomap-d12-system-admission"
    out_resolved, proof_file = adm_dir / "hold.json", adm_dir / "proof.json"
    ev_path = Path(env["GITHUB_EVENT_PATH"])
    valid_ev = json.loads(ev_path.read_text(encoding="utf-8"))
    with patch("ci.d12_system_hold.os.environ", env), patch(
        "ci.d12_system_hold._default_uname", return_value=("Linux", "x86_64")
    ), patch("ci.d12_system_hold.frozen_identity", return_value=d12_ctx), patch(
        "ci.d12_system_hold.subprocess.run", side_effect=_fake_git
    ):
        for bad_draft in (False, None, 0, 1, "true", ...):
            pr_mut = {k: v for k, v in valid_ev["pull_request"].items() if k != "draft"}
            if bad_draft is not ...:
                pr_mut["draft"] = bad_draft
            ev_path.write_text(json.dumps({**valid_ev, "pull_request": pr_mut}), encoding="utf-8")
            assert qualification_main(_hold_argv(out_resolved, proof_file)) == 1 and not proof_file.exists()
        ev_path.write_text(json.dumps(valid_ev), encoding="utf-8")
        assert qualification_main(_hold_argv(out_resolved, proof_file)) == 0
    resolved_doc = json.loads(out_resolved.read_text(encoding="utf-8"))
    assert resolved_doc["result"] == "prerequisites_resolved" and resolved_doc["qualified"] is False
    assert stat.S_IMODE(adm_dir.lstat().st_mode) == 0o700 and stat.S_IMODE(proof_file.lstat().st_mode) == 0o600
    assert json.loads(proof_file.read_text(encoding="utf-8"))["schema"] == SYSTEM_ADMISSION_PROOF_SCHEMA
    args = SimpleNamespace(
        d12_system_proof_json=str(proof_file), candidate_sha="a" * 40, candidate_tree="b" * 40,
        candidate_base_parent=BASE_SHA, candidate_head_parent="d" * 40, approval_id="pr-13",
        pr_number="13", repository="Knowledge-Forge-AI/repo-map",
    )
    drift_root = tmp_path / "drift-repo"
    (drift_root / "tools/test_sandbox").mkdir(parents=True, exist_ok=True)
    sdk_df = (REPO_ROOT / "tools/test_sandbox/Dockerfile").read_bytes()
    (drift_root / "tools/native_apt_prerequisites.py").write_bytes(
        (REPO_ROOT / "tools/native_apt_prerequisites.py").read_bytes())
    (drift_root / "tools/test_sandbox/Dockerfile").write_bytes(sdk_df + b"\n# drift\n")
    common_disp: dict[str, Any] = {"repo_root": drift_root, "env": env, "uname_fn": lambda: ("Linux", "x86_64"),
                   "runner": _fake_git, "frozen_identity_fn": lambda _r, _p: d12_ctx,
                   "grant_path": REPO_ROOT / DEFAULT_GRANT_RELPATH,
                   "expected_candidate_path": tmp_path / "ci72-candidate.json"}
    with pytest.raises(D12SystemGrantError, match="live SDK recipe SHA256 disagrees with system build grant"):
        verify_host_system_proof_for_dispatch(args, **common_disp)
    (drift_root / "tools/test_sandbox/Dockerfile").write_bytes(sdk_df)
    verified = verify_host_system_proof_for_dispatch(args, **common_disp)
    assert verified["pull_request"] == 13
    arg_res = sandbox_report_arguments(
        ["--suite", "system", "--d12-system-proof-json", str(proof_file)], repo_root=REPO_ROOT)
    assert arg_res.d12_proof_bytes == proof_file.read_bytes()
    inner_target = tmp_path / "inner-run" / "repomap-d12-system-proof.json"
    assert (proof_raw := arg_res.d12_proof_bytes) is not None
    poisoned = poisoned_coverage_base_env()
    transfer_proof_locally(MagicMock(), "local-cid", proof_raw, target_path=inner_target, base_env=poisoned)
    assert inner_target.read_bytes() == proof_raw and stat.S_IMODE(inner_target.lstat().st_mode) == 0o600
    with pytest.raises(RuntimeError, match="integration sandbox D12 system proof transfer failed"):
        transfer_proof_locally(MagicMock(), "local-cid", proof_raw, target_path=inner_target, base_env=poisoned)


def test_sandbox_dispatch_blocks_system_suite_without_valid_proof() -> None:
    ensure_image_mock = MagicMock()
    with patch("test_sandbox.active_sandbox", return_value=False), patch(
        "test_sandbox.ensure_sandbox_image", ensure_image_mock
    ):
        rc = integration_sandbox_dispatch(
            SimpleNamespace(suite="system", d12_system_proof_json=None), ["--suite", "system"], repo_root=REPO_ROOT
        )
    assert rc == 2 and not ensure_image_mock.called


def test_cross_process_flock_and_o_excl_race_and_execute_system_run(tmp_path: Path) -> None:
    env, d12_ctx = _setup_hosted_pr_env(tmp_path)
    adm_dir = tmp_path / "repomap-d12-system-admission"
    out_resolved, proof_file = adm_dir / "hold.json", adm_dir / "proof.json"
    with patch("ci.d12_system_hold.os.environ", env), patch(
        "ci.d12_system_hold._default_uname", return_value=("Linux", "x86_64")
    ), patch("ci.d12_system_hold.frozen_identity", return_value=d12_ctx), patch(
        "ci.d12_system_hold.subprocess.run", side_effect=_fake_git
    ):
        assert qualification_main(_hold_argv(out_resolved, proof_file)) == 0

    lock_report_dir = tmp_path / "lock-race-report"
    lock_report_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_report_dir / SYSTEM_BUILD_LOCK_FILENAME
    preflight_doc = _matching_preflight_doc(d12_ctx)
    cand_path = tmp_path / "ci72-candidate.json"

    def _new_session(rep_dir: Path) -> D12SystemSession:
        sess = D12SystemSession.establish(
            repo_root=REPO_ROOT, config=_make_config(rep_dir), proof_json_arg=str(proof_file),
            target_arch_fn=lambda: "amd64", tree_sha_fn=lambda _r: "b" * 40,
            frozen_identity_fn=lambda _r, _p: d12_ctx, run_git_fn=_fake_git, expected_candidate_path=cand_path,
        )
        sess.run_same_daemon_preflight(explore_fn=lambda *_a, **_kw: preflight_doc)
        return sess

    race_session = _new_session(lock_report_dir)
    with hold_exclusive_flock(lock_file, base_env=poisoned_coverage_base_env()):
        with pytest.raises(SystemTestError, match="unable to acquire exclusive D12 system build lock"):
            race_session.reserve_one_use_candidate_build()
    race_session.reserve_one_use_candidate_build()
    race_session.close_lock()
    second_session = _new_session(lock_report_dir)
    try:
        with pytest.raises(SystemTestError, match="already exists"):
            second_session.reserve_one_use_candidate_build()
    finally:
        second_session.close_lock()

    report_dir = tmp_path / "report"
    config = _make_config(report_dir)
    session = D12SystemSession.establish(
        repo_root=REPO_ROOT, config=config, proof_json_arg=str(proof_file), target_arch_fn=lambda: "amd64",
        tree_sha_fn=lambda _r: "b" * 40, frozen_identity_fn=lambda _r, _p: d12_ctx,
        run_git_fn=_fake_git, expected_candidate_path=cand_path,
    )

    def fake_build(
        _r: Path, _c: SystemTestConfig, *, d12_session: D12SystemSession | None = None, **_kw: object
    ) -> CandidateImageMetadata:
        assert d12_session is not None
        d12_session.reserve_one_use_candidate_build()
        d12_session.record_built_image_id("sha256:" + "7" * 64)
        return CandidateImageMetadata(
            image_id="sha256:" + "7" * 64, image_tag=_c.candidate_tag,
            image_digest="sha256:" + "8" * 64, labels=d12_session.candidate_d12_labels(),
            release_versions={"libpq": str(D12_CANDIDATE_LIBPQ_VERSION)},
            created_image_ids=("sha256:" + "7" * 64,),
        )

    def fake_post(sess: D12SystemSession, **_kw: object) -> dict[str, Any]:
        sess.post_build_probes = {"packaging": {"libpq": D12_CANDIDATE_LIBPQ_VERSION}}
        sess.post_build_assessments = {"qualification": "stop_pending_disposition"}
        return sess.post_build_probes

    def fake_rt(sess: D12SystemSession, **_kw: object) -> dict[str, Any]:
        sess.roundtrip_evidence = {"restored": {"fixture_rows": 2000}}
        return sess.roundtrip_evidence

    write_report_mock = MagicMock()
    orig_preflight = D12SystemSession.run_same_daemon_preflight
    step = SystemStepResult("step_1_packaged_cluster_readiness", "passed", 0.5, "ok")
    plan_ret: tuple[Any, Path, Path, dict[str, Any]] = (
        SimpleNamespace(database="repomap", user="repomap"), tmp_path / "c.yml", tmp_path / "o.yml", {}
    )
    with patch.object(
        session, "run_same_daemon_preflight",
        side_effect=lambda **_kw: orig_preflight(session, explore_fn=lambda *_a, **_k: preflight_doc),
    ):
        rc = execute_system_run(
            repo_root=REPO_ROOT, candidate_tree_sha="b" * 40, execution_mode="hosted_qualification",
            config=config, deadline=SystemDeadline(100.0, cleanup_reserve_seconds=20.0),
            timer=MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0),
            docker_boundary=SimpleNamespace(client=MagicMock(), projection=lambda: {}),
            fixture_dir=tmp_path / "fixture", compose_dir=tmp_path / "compose",
            repo_map_home=tmp_path / "home", evidence_dir=tmp_path / "evidence",
            system_start_epoch_env="1700000000.0", system_suite_result_cls=SystemSuiteResult,
            materialize_fixture_repository_fn=MagicMock(), build_and_verify_candidate_image_fn=fake_build,
            prepare_system_compose_topology_fn=MagicMock(return_value=plan_ret),
            execute_all_scenarios_fn=MagicMock(return_value=((step,), {}, {}, "9" * 64)),
            load_plan_env_fn=MagicMock(return_value={}),
            perform_system_cleanup_fn=MagicMock(return_value={"success": True, "errors": []}),
            write_system_report_fn=write_report_mock, d12_session=session,
            run_post_build_candidate_probes_fn=fake_post, run_disposable_roundtrip_probe_fn=fake_rt,
        )

    assert rc == 1
    suite_result = write_report_mock.call_args.args[0]
    assert suite_result.passed is False and suite_result.merge_authorized is False
    # Injected image/observations do not satisfy the conditional qualification.
    assert "D12 qualification" in suite_result.error_message
    assert not (report_dir / QUALIFICATION_FILENAME).exists()
    assert not (report_dir / SYSTEM_CANDIDATE_EVIDENCE_FILENAME).exists()


def test_real_container_bounded_exec_timeout_cleanup_and_merged_compose_no_build(tmp_path: Path) -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None
    client = boundary.client
    image_id = ensure_canonical_runtime_image(repo_root=REPO_ROOT, resource_run=run, client=client, boundary=boundary)
    owner = CurrentRunDockerContainers(run, client)
    wrapped_create = wrap_create_with_bounded_exec(_create, default_timeout_seconds=15.0)
    cid, container = wrapped_create(
        owner, client, image_id, ["-c", "import time; time.sleep(60)"],
        role="d12-bounded-exec-int", entrypoint=["python"], network_mode="none",
    )
    try:
        container.start()
        comb = container.exec_run(
            ["python", "-c", "import sys; sys.stdout.write('ok\\n'); sys.stderr.write('err\\n')"], demux=False)
        assert comb.exit_code == 0 and isinstance(comb.output, bytes)
        assert b"ok\n" in comb.output and b"err\n" in comb.output
        dmx = container.exec_run(
            ["python", "-c", "import sys; sys.stdout.write('out\\n'); sys.stderr.write('warn\\n')"], demux=True)
        assert dmx.exit_code == 0 and dmx.output == (b"out\n", b"warn\n")
        # Runtime probes observe container files; exported SDK names use /nonexistent for compiler-name refusal only.
        assert Path("/usr/bin/dpkg-query").is_file()
        sdk_cmd = ["dpkg-query", "-W", "-f=${Package}\t${db:Status-Abbrev}\n"]
        sdk_q = subprocess.run(sdk_cmd, check=True, capture_output=True, text=True).stdout.splitlines()
        sdk_names = [r.split("\t")[0] for r in sdk_q if r.split("\t")[1].startswith("ii")]
        pkg_probe = (
            release_mod.RELEASE_PROBE_HELPERS_PY + release_mod.RELEASE_FINAL_PACKAGE_CHECK_PY + "import json\n"
            f"sdk_names = {sdk_names!r}\narch = run('dpkg', '--print-architecture')[1]\n"
            "q = run('dpkg-query', '-W', '-f=${Package}\\t${db:Status-Abbrev}\\n')[1].splitlines()\n"
            "pkgs = [r.split('\\t')[0] for r in q if r.split('\\t')[1].startswith('ii')]\n"
            "res = {'arch': arch, 'runtime_live': forbidden_packages(pkgs), "
            "'sdk_compiler_names': forbidden_packages(sdk_names, root='/nonexistent'), "
            "'unqualified': forbidden_packages(pkgs, root='/nonexistent'), "
            "'tooling': forbidden_packages([*pkgs, 'gcc', 'libpq-dev'])}\nprint(json.dumps(res))\n"
        )
        pkg_res = container.exec_run(["python", "-I", "-c", pkg_probe], demux=False)
        assert pkg_res.exit_code == 0 and isinstance(pkg_res.output, bytes)
        pkg_obs = json.loads(pkg_res.output.decode("utf-8").strip().splitlines()[-1])
        assert isinstance(pkg_obs["runtime_live"], list) and "gcc-14-base" in pkg_obs["unqualified"]
        assert {"gcc", "binutils", "cpp", "libpq-dev"} <= set(pkg_obs["sdk_compiler_names"])
        assert {"gcc", "libpq-dev"} <= set(pkg_obs["tooling"]) and (
            pkg_obs["arch"] == "amd64" or pkg_obs["runtime_live"] == ["gcc-14-base"])
        short_container = wrap_create_with_bounded_exec(
            lambda *_a, **_kw: (cid, container._container), default_timeout_seconds=0.3
        )(owner, client, image_id, ["true"])[1]
        with pytest.raises(SystemTestError, match="timed out"):
            short_container.exec_run(["python", "-c", "import time; time.sleep(10)"])
    finally:
        owner.cleanup(cid)
    owner.verify_baseline()

    fixture_repo = tmp_path / "fixture-repo"
    fixture_repo.mkdir(parents=True, exist_ok=True)
    (fixture_repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    compose_cfg = _make_config(tmp_path / "compose-report", run_id="compose-int")
    _plan, _base_p, _over_p, topology = prepare_system_compose_topology(
        compose_dir=tmp_path / "compose-dir", repo_map_home=tmp_path / "repomap-home",
        fixture_repo=fixture_repo, repo_root=REPO_ROOT, config=compose_cfg,
    )
    services = topology["services"]
    for svc_name in APPLICATION_SERVICES:
        assert services[svc_name]["image"] == compose_cfg.candidate_tag
        assert services[svc_name].get("build") is None and services[svc_name]["pull_policy"] == "never"
    assert services["postgres"]["pull_policy"] == "never"
    assert normalize_compose_args(["up", "-d"]) == ["up", "--no-build", "--pull", "never", "-d"]
    with pytest.raises(SystemTestError, match="forbidden"):
        normalize_compose_args(["build"])
