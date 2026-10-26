"""Unit tests for Route B D12SystemSession inner validation, preflight, and one-use build lock."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib, json, stat, subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from docker.errors import ImageNotFound
import pytest

from ci.d12_hosted_evidence import validate_expected_candidate_record
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH, DEFAULT_GRANT_RELPATH, build_system_admission_proof,
    load_and_validate_system_build_grant, write_system_admission_proof,
)
from repomap_kg.runtime.release import GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST
from repomap_test_support import d12_image_probes as probes_mod, resource_run as resource_run_mod
from tools.system import d12_system_session as session_mod
from tools.system.config import SystemDeadline, SystemTestConfig, SystemTestError
from tools.system.d12_system_session import (
    D12SystemSession, LABEL_D12_GRANT_ID, LABEL_D12_RECIPE_SHA256, LABEL_D12_SOURCE_SHA256,
    SYSTEM_BUILD_INTENT_FILENAME, SYSTEM_BUILD_INTENT_SCHEMA, SYSTEM_BUILD_LOCK_FILENAME,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
BASE_SHA = "24d15650a2d4563d188acb8bbf34a0dabf8f3d65"


@pytest.fixture(autouse=True)
def _ensure_canonical_resource_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    current = resource_run_mod.active_resource_run()
    if current is not None:
        return current
    run_root = tmp_path / "run-d12-session"
    fake_run = SimpleNamespace(
        ledger=SimpleNamespace(identity=SimpleNamespace(run_id=run_root.name)),
        layout=SimpleNamespace(run_root=run_root),
    )
    monkeypatch.setattr(resource_run_mod, "active_resource_run", lambda: fake_run)
    monkeypatch.setattr(session_mod, "active_resource_run", lambda: fake_run)
    return fake_run


def _active_run_id() -> str:
    return str(r.ledger.identity.run_id) if (r := session_mod.active_resource_run()) is not None else "run-d12-session"


def _make_valid_proof(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    cand_path, grant_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH, REPO_ROOT / DEFAULT_GRANT_RELPATH
    cand_sha = hashlib.sha256(cand_path.read_bytes()).hexdigest()
    expected_cand = validate_expected_candidate_record(json.loads(cand_path.read_text(encoding="utf-8")))
    grant, grant_sha = load_and_validate_system_build_grant(
        grant_path, expected_candidate=expected_cand, frozen_identity=dict(expected_cand["d12_context"])
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    (ev := tmp_path / "event.json").write_text(json.dumps({"number": 13, "draft": True}), encoding="utf-8")
    proof = build_system_admission_proof(
        grant=grant, grant_sha256=grant_sha, expected_candidate_sha256=cand_sha,
        raw_event_sha256=hashlib.sha256(ev.read_bytes()).hexdigest(),
        after="d" * 40, candidate_sha="a" * 40, candidate_tree="b" * 40,
        candidate_base_parent=str(grant["base"]), candidate_head_parent="d" * 40, run_id="12345678",
        native_host={"runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux", "host_arch": "x86_64"},
    )
    write_system_admission_proof(proof_file := tmp_path / "proof-dir" / "proof.json", proof)
    return proof_file, dict(expected_cand["d12_context"])


def _fake_git(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    mapping = {"HEAD": "a" * 40, "HEAD^{tree}": "b" * 40, "HEAD^1": BASE_SHA, "HEAD^2": "d" * 40}
    return subprocess.CompletedProcess(cmd, 0, mapping[cmd[-1]] + "\n", "")


def _matching_preflight_report(d12_ctx: dict[str, Any]) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    zero_counts = dict.fromkeys(
        ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
         "unmanaged_build_count", "unmanaged_pull_count"), 0,
    )
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
                "libpq_label": "runtime PQlibVersion; forecast is equality only", "written_to_source": False,
                "valid": True,
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


def _make_config(report_dir: Path, run_id: str | None = None) -> SystemTestConfig:
    return SystemTestConfig.create(
        timeout_seconds=1500, report_dir=report_dir, candidate_tree_sha="b" * 40,
        run_id=run_id or _active_run_id(), gate_kind="main-system", approval_id="pr-13", pr_number="13",
        repository="Knowledge-Forge-AI/repo-map", approved_base_branch="main", approved_base_sha=BASE_SHA,
        approved_head_branch="staging", approved_head_sha="d" * 40, candidate_commit_sha="a" * 40,
        candidate_base_parent=BASE_SHA, candidate_head_parent="d" * 40, execution_mode="hosted_qualification",
    )


def _establish(
    tmp_path: Path, report_dir: Path | None = None, **overrides: Any
) -> tuple[D12SystemSession, dict[str, Any]]:
    proof_file, d12_ctx = _make_valid_proof(tmp_path)
    config = _make_config(report_dir or (tmp_path / "report"))
    return D12SystemSession.establish(
        repo_root=REPO_ROOT, config=config, proof_json_arg=str(proof_file), target_arch_fn=lambda: "amd64",
        tree_sha_fn=lambda _r: "b" * 40, frozen_identity_fn=lambda _r, _p: dict(d12_ctx),
        run_git_fn=_fake_git, **overrides,
    ), d12_ctx


def test_establish_session_preflight_and_one_use_reservation(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    session, d12_ctx = _establish(tmp_path, report_dir)
    config = session.config
    try:
        with pytest.raises(SystemTestError, match="same-daemon preflight must succeed"):
            session.validate_for_candidate_build(repo_root=REPO_ROOT, config=config)

        preflight = session.run_same_daemon_preflight(
            explore_fn=lambda *_a, **_kw: _matching_preflight_report(d12_ctx)
        )
        assert preflight["result"] == "observed"
        assert "build" not in preflight and "image_cleanup" not in preflight
        assert preflight["cleanup"]["zero_build"]["managed_system_candidate_image_build_count"] == 0
        session.validate_for_candidate_build(repo_root=REPO_ROOT, config=config)

        orig_after = session.proof["after"]
        session.proof["after"] = "e" * 40
        try:
            with pytest.raises(SystemTestError, match="in-memory binding digest drifted"):
                session.validate_for_candidate_build(repo_root=REPO_ROOT, config=config)
        finally:
            session.proof["after"] = orig_after
        assert session.preflight_report is not None
        saved_bindings = session.preflight_report.pop("bindings", None)
        try:
            with pytest.raises(SystemTestError, match="preflight bindings.run_id disagrees"):
                session.validate_for_candidate_build(repo_root=REPO_ROOT, config=config)
        finally:
            if saved_bindings is not None:
                session.preflight_report["bindings"] = saved_bindings

        with pytest.raises(SystemTestError, match="reservation nonce must equal established"):
            session.reserve_one_use_candidate_build(nonce_fn=lambda: "0123456789abcdef0123456789abcdef")
        assert not (report_dir / SYSTEM_BUILD_LOCK_FILENAME).exists()
        assert not (report_dir / SYSTEM_BUILD_INTENT_FILENAME).exists()

        nonce = str(session.grant["nonce"])
        intent = session.reserve_one_use_candidate_build(nonce_fn=lambda: nonce)
        assert intent["schema"] == SYSTEM_BUILD_INTENT_SCHEMA and intent["intent_id"] == nonce
        assert intent["reservation_id"] == nonce and intent["grant_id"] == nonce
        assert (report_dir / SYSTEM_BUILD_LOCK_FILENAME).is_file()
        intent_path = report_dir / SYSTEM_BUILD_INTENT_FILENAME
        assert intent_path.is_file() and stat.S_IMODE(intent_path.lstat().st_mode) == 0o600

        assert session.candidate_d12_labels() == {
            LABEL_D12_GRANT_ID: nonce,
            LABEL_D12_SOURCE_SHA256: str(d12_ctx["source_sha256"]),
            LABEL_D12_RECIPE_SHA256: str(d12_ctx["recipe_sha256"]),
        }
        with pytest.raises(SystemTestError, match="second system candidate image build attempt"):
            session.reserve_one_use_candidate_build()
    finally:
        session.close_lock()


def test_preflight_rejects_package_drift_and_preserves_failure_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_dir = tmp_path / "report"
    session, d12_ctx = _establish(tmp_path, report_dir)
    base_rep = _matching_preflight_report(d12_ctx)
    steps = base_rep["steps"]
    for mut, msg in (
        ({"build": {"succeeded": True}}, "must not claim build/image"),
        ({"server_inventory": None}, "missing server_inventory"),
        ({"steps": {**steps, "candidate": {
            **steps["candidate"], "manifest": {**steps["candidate"]["manifest"], "libpq_sha256": "f" * 64}}}},
         "candidate manifest mismatch"),
        ({"steps": {**steps, "libpq_runtime": {
            **steps["libpq_runtime"], "library": {**steps["libpq_runtime"]["library"], "sha256": "f" * 64}}}},
         "libpq_runtime.library mismatch"),
    ):
        with pytest.raises(SystemTestError, match=msg):
            session.run_same_daemon_preflight(explore_fn=lambda *_a, _m=mut, **_k: {**base_rep, **_m})

    def _failing_explore(*_a: object, report_sink: dict[str, Any] | None = None, **_kw: object) -> dict[str, Any]:
        if report_sink is not None:
            report_sink.update(result="refused", refusals=["builder: package mismatch"])
        raise RuntimeError("inner explore refused")

    for limit in (session_mod.d12.REPORT_PART_LIMIT, 4):
        monkeypatch.setattr(session_mod.d12, "REPORT_PART_LIMIT", limit)
        with pytest.raises(SystemTestError, match="preflight failed: inner explore refused"):
            session.run_same_daemon_preflight(explore_fn=_failing_explore)
    assert session.preflight_report is not None and session.preflight_report["result"] == "refused"
    assert session.intent_sha256 == "" and not (report_dir / SYSTEM_BUILD_INTENT_FILENAME).exists()


def test_session_records_built_image_id_immediately_for_cleanup(tmp_path: Path) -> None:
    session, _ = _establish(tmp_path)
    assert session.record_built_image_id("sha256:" + "9" * 64 + "\n") == "sha256:" + "9" * 64
    assert session.image_id == "sha256:" + "9" * 64


def test_candidate_image_uses_staged_session_context_and_captures_iidfile_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.system import candidate_image

    staged_dir = tmp_path / "staged-ctx"
    session, d12_ctx = _establish(
        tmp_path, stage_context_fn=lambda _r, dest, _a: (dest.mkdir(parents=True, exist_ok=True), staged_dir)[1]
    )
    config = session.config
    monkeypatch.setattr(candidate_image, "resolve_target_arch", lambda _m=None: "amd64")
    monkeypatch.setattr(candidate_image, "get_current_tree_sha", lambda _r: "b" * 40)
    entered_requests: list[str] = []

    @contextmanager
    def _managed_build(*, request: str) -> Any:
        entered_requests.append(request)
        yield SimpleNamespace(id="ticket-1")

    boundary = SimpleNamespace(managed_system_candidate_build=_managed_build, complete_operation=MagicMock())
    for bnd, msg in ((None, "boundary lacks"), (boundary, "same-daemon preflight")):
        with pytest.raises(SystemTestError, match=msg):
            candidate_image.build_and_verify_candidate_image(
                REPO_ROOT, config, boundary=bnd, client=None, d12_session=session
            )
    session.run_same_daemon_preflight(explore_fn=lambda *_a, **_kw: _matching_preflight_report(d12_ctx))
    with pytest.raises(SystemTestError, match="boundary lacks managed_system_candidate_build"):
        candidate_image.build_and_verify_candidate_image(
            REPO_ROOT, config, boundary=None, client=None, d12_session=session
        )
    assert config.report_dir is not None
    assert not (config.report_dir / SYSTEM_BUILD_INTENT_FILENAME).exists()
    docker_cmds: list[list[str]] = []

    def _failing_docker_build(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        docker_cmds.append(list(cmd))
        Path(cmd[cmd.index("--iidfile") + 1]).write_text("sha256:" + "8" * 64 + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1, "", "build failed after write")

    monkeypatch.setattr(candidate_image.subprocess, "run", _failing_docker_build)
    try:
        with pytest.raises(SystemTestError, match="candidate image build failed"):
            candidate_image.build_and_verify_candidate_image(
                REPO_ROOT, config, boundary=boundary, client=None, d12_session=session
            )
        assert entered_requests == [f"candidate-image-build:{config.candidate_tag}"]
        assert len(docker_cmds) == 1 and docker_cmds[0][-1] == str(staged_dir)
        assert session.image_id == "sha256:" + "8" * 64
    finally:
        session.close_lock()

    session2, _ = _establish(
        tmp_path / "second",
        stage_context_fn=lambda _r, dest, _a: (dest.mkdir(parents=True, exist_ok=True), staged_dir)[1],
    )
    session2.run_same_daemon_preflight(explore_fn=lambda *_a, **_kw: _matching_preflight_report(d12_ctx))
    monkeypatch.setattr(
        candidate_image.subprocess, "run", lambda cmd, **_k: subprocess.CompletedProcess(cmd, 0, "", "")
    )
    fake_client = SimpleNamespace(images=SimpleNamespace(get=lambda _t: SimpleNamespace(id="sha256:" + "7" * 64)))
    try:
        with pytest.raises(SystemTestError, match="did not emit a valid --iidfile digest"):
            candidate_image.build_and_verify_candidate_image(
                REPO_ROOT, session2.config, boundary=boundary, client=fake_client, d12_session=session2
            )
    finally:
        session2.close_lock()


def test_default_same_daemon_preflight_binds_active_sandbox_and_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, d12_ctx = _establish(tmp_path)
    config = session.config
    import test_sandbox

    monkeypatch.delattr(test_sandbox, "sandbox_active", raising=False)
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: False)
    with pytest.raises(SystemTestError, match="inner test sandbox"):
        session.run_same_daemon_preflight()

    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: True)
    saved_run = session_mod.active_resource_run()
    monkeypatch.setattr(session_mod, "active_resource_run", lambda: None)
    with pytest.raises(SystemTestError, match="active canonical resource run"):
        session.run_same_daemon_preflight()
    monkeypatch.setattr(session_mod, "active_resource_run", lambda: saved_run)

    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    zero_proj = dict.fromkeys(
        ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
         "unmanaged_build_count", "unmanaged_pull_count"), 0,
    )
    state = {"arch": "aarch64", "missing_base": False, "buildkit": False}
    base_ids = {
        POSTGRES_RELEASE_IMAGE: pkg.postgres_config_digest, PYTHON_RELEASE_IMAGE: "sha256:" + "2" * 64,
        GO_RELEASE_IMAGE: session_mod.inner.GO_CONFIGS["linux/amd64"],
    }
    probes = [1, 0, 0, 0]
    containers: dict[str, Any] = {}

    def _get_image(ref: str) -> Any:
        if state["missing_base"]:
            raise ImageNotFound("not found")
        return SimpleNamespace(attrs={
            "Id": base_ids[ref], "Os": "linux", "Architecture": "amd64",
            "RepoDigests": [ref], "Config": {"Volumes": {}},
        })

    fake_client = SimpleNamespace(
        info=lambda: {"ID": "daemon-1", "Architecture": state["arch"], "Driver": "overlay2"},
        version=lambda: {"Version": "27.0", "ApiVersion": "1.46"},
        images=SimpleNamespace(get=_get_image), containers=SimpleNamespace(get=lambda cid: containers[cid]),
    )

    def _owner_create(image: str, _cmd: Any, *, role: str = "c", **_kw: object) -> str:
        cid = f"cid-{role}-{len(containers)}"
        containers[cid] = SimpleNamespace(
            id=cid, status="running", attrs={"Image": base_ids.get(image, image), "Mounts": []},
            start=lambda: None, reload=lambda: None,
        )
        return cid

    fake_owner = SimpleNamespace(create=_owner_create, cleanup=MagicMock(), verify_baseline=MagicMock())
    orig_wrap = session_mod.wrap_create_with_bounded_exec
    monkeypatch.setattr(session_mod, "wrap_create_with_bounded_exec", lambda fn, **kw: orig_wrap(
        fn, **kw, run_cmd=lambda c, **_k: subprocess.CompletedProcess(c, probes.pop(0) if probes else 0, b"", b""),
    ))
    monkeypatch.setattr(session_mod.d12, "locate_run_boundary", lambda: SimpleNamespace(
        client=fake_client, projection=lambda: dict(zero_proj),
    ))
    monkeypatch.setattr(session_mod.d12, "frozen_identity", lambda _r, _p: dict(d12_ctx))
    monkeypatch.setattr(session_mod, "CurrentRunDockerContainers", lambda _run, _c: fake_owner)
    monkeypatch.setattr(probes_mod.time, "sleep", lambda _s: None)
    match_rep = _matching_preflight_report(d12_ctx)
    monkeypatch.setattr(session_mod, "_inventory", lambda *_a, **_kw: match_rep["server_inventory"])
    monkeypatch.setattr(session_mod, "_hashes", lambda *_a, **_kw: {})
    monkeypatch.setattr(session_mod.subprocess, "run", lambda cmd, **_kw: subprocess.CompletedProcess(
        cmd, 0, "Platforms: linux/amd64, linux/arm64\n" + ("BuildKit version: v0.20.0\n" if state["buildkit"] else ""),
        "",
    ))
    with pytest.raises(SystemTestError, match="requires native linux/amd64"):
        session.run_same_daemon_preflight()
    state["arch"], state["missing_base"] = "x86_64", True
    with pytest.raises(SystemTestError, match="is not local; no extra pull"):
        session.run_same_daemon_preflight()
    state["missing_base"] = False
    with pytest.raises(SystemTestError, match="E1 exploration refused"):
        session.run_same_daemon_preflight()
    assert session.preflight_report is not None and session.preflight_report["result"] == "refused"
    fake_owner.cleanup.assert_called()
    fake_owner.verify_baseline.assert_called_once()

    state["buildkit"] = True
    match_steps = match_rep["steps"]
    monkeypatch.setattr(session_mod.inner, "trust_facts", lambda s, _c: s.setdefault("trust", {}) or {})
    monkeypatch.setattr(session_mod.inner, "closure_facts", lambda s, _c, _p: s.setdefault("closure", {"packages": []}))
    monkeypatch.setattr(session_mod.inner, "resolve", lambda *_a, **_k: {"packages": []})
    monkeypatch.setattr(session_mod.inner.runtime, "observe", lambda *_a, **_k: dict(match_steps["libpq_runtime"]))
    monkeypatch.setattr(session_mod.inner, "candidate", lambda s, _p, _i: s.update(candidate=match_steps["candidate"]))
    rep = session.run_same_daemon_preflight(deadline=SystemDeadline(1500, 120))
    assert rep["bindings"]["run_id"] == config.run_id and rep["bindings"]["daemon_id"] == "daemon-1"
    session.validate_for_candidate_build(repo_root=REPO_ROOT, config=config)
