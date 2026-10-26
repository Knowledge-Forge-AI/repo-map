"""Route B inner system runner proof validation, same-daemon preflight, and one-use build lock."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any

import d12_dependency_preflight as inner
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE,
    POSTGRES_RELEASE_IMAGE,
    PYTHON_RELEASE_IMAGE,
    PlatformPackages,
)
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION
from repomap_test_support import d12_core_image as d12
from repomap_test_support.d12_image_probes import _create, _hashes, _inventory, _start_server
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from tools.system.candidate_identity import (
    CTX_IDENTITY_KEYS,
    compute_session_binding_digest,
    get_current_tree_sha,
    load_and_verify_session_authority,
    resolve_target_arch,
    verify_preflight_matches_manifest as verify_preflight_matches_manifest,
    write_exclusive_0600_json as _write_exclusive_0600_json,
)
from tools.system.config import SystemTestConfig, SystemTestError
from tools.system.d12_exec import wrap_create_with_bounded_exec

SYSTEM_BUILD_INTENT_SCHEMA = "repomap-d12-system-build-intent-v1"
_ESTABLISHED_SENTINEL = object()
SYSTEM_BUILD_LOCK_FILENAME = "d12-system-build.lock"
SYSTEM_BUILD_INTENT_FILENAME = "d12-system-build-intent.json"
LABEL_D12_GRANT_ID = "io.repomap.d12.grant_id"
LABEL_D12_SOURCE_SHA256 = "io.repomap.d12.source_sha256"
LABEL_D12_RECIPE_SHA256 = "io.repomap.d12.recipe_sha256"
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_CTX_KEYS = CTX_IDENTITY_KEYS


def _default_same_daemon_preflight(
    repo_root: Path,
    *,
    platform: str = "linux/amd64",
    timeout_seconds: float = 300.0,
    expected_recipe_sha256: str = "",
    expected_source_sha256: str = "",
    expected_dockerfile_sha256: str = "",
    deadline: Any | None = None,
    report_sink: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import test_sandbox

    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget("d12 same-daemon preflight")
    elif deadline is not None and hasattr(deadline, "check_budget"):
        deadline.check_budget()
    clamp = getattr(deadline, "clamp_timeout", None)
    eff_timeout = float(clamp(timeout_seconds)) if callable(clamp) else float(timeout_seconds)
    if eff_timeout <= 0:
        raise SystemTestError("D12 same-daemon preflight requires positive timeout budget")
    if not test_sandbox.active_sandbox():
        raise SystemTestError("same-daemon D12 preflight must execute inside the inner test sandbox")
    if (run := active_resource_run()) is None:
        raise SystemTestError("same-daemon D12 preflight requires an active canonical resource run")
    boundary = d12.locate_run_boundary()
    client = boundary.client
    frozen = d12.frozen_identity(repo_root, platform)
    if (
        (expected_source_sha256 and frozen["source_sha256"] != expected_source_sha256)
        or (expected_recipe_sha256 and frozen["recipe_sha256"] != expected_recipe_sha256)
        or (expected_dockerfile_sha256 and frozen["dockerfile_sha256"] != expected_dockerfile_sha256)
    ):
        raise SystemTestError("D12 same-daemon preflight frozen identity drifted from proof")
    admission = d12.D12Admission(platform=platform, node_id="main-system-gate", **frozen)
    inspected = subprocess.run(
        ["docker", "buildx", "inspect"],
        capture_output=True, text=True, timeout=min(30.0, eff_timeout), check=False,
    )
    if inspected.returncode != 0:
        raise SystemTestError(f"D12 same-daemon preflight buildx inspect failed (exit {inspected.returncode})")
    daemon_info = client.info()
    avail = d12.platform_availability(
        platform, daemon_info.get("Architecture", ""), d12.offered_platforms(inspected.stdout)
    )
    if avail.get("execution") != "native":
        raise SystemTestError(f"D12 same-daemon preflight requires native {platform}, got {avail!r}")
    bases = d12.verify_bases(client, platform, (POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE, GO_RELEASE_IMAGE))
    owner = CurrentRunDockerContainers(run, client)
    b_create = wrap_create_with_bounded_exec(_create, deadline=deadline, default_timeout_seconds=eff_timeout)
    server_id: str | None = None
    server_inv: dict[str, Any] | None = None
    reports: dict[str, dict[str, Any]] = {}
    cleanup_obs: dict[str, Any] = {"server": "not_started", "containers": "unverified", "zero_build": None}
    try:
        server_env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": secrets.token_hex(16)}
        server_id, srv_c = _start_server(owner, client, server_env, platform, deadline=deadline, create_fn=b_create)
        if getattr(srv_c, "attrs", {}).get("Image") != bases[POSTGRES_RELEASE_IMAGE]["id"]:
            raise SystemTestError("D12 same-daemon preflight server container image digest mismatch")
        server_inv = _inventory(
            owner, client, POSTGRES_RELEASE_IMAGE, platform, "d12-inventory-server",
            deadline=deadline, create_fn=b_create,
        )
        _hashes(
            owner, client, PYTHON_RELEASE_IMAGE, ["/usr/local/bin/python3"], platform,
            "d12-hash-preflight", deadline=deadline, create_fn=b_create,
        )
        bindings = {
            "run_id": run.ledger.identity.run_id, "daemon_id": str(daemon_info.get("ID", "")),
            "sdk_image": "unobserved in the sandbox",
        }
        exp_rep = inner.explore(
            owner, client, admission=admission, bases=bases, availability=avail, inspected=inspected,
            server_inventory=server_inv, create=b_create, bindings=bindings,
            write_report=lambda name, payload: reports.setdefault(name, dict(payload)),
        )
        reports["exploration"] = dict(exp_rep)
    finally:
        try:
            if server_id is not None:
                owner.cleanup(server_id)
                cleanup_obs["server"] = "removed"
            owner.verify_baseline()
            cleanup_obs["containers"] = "baseline_verified"
            budget = boundary.projection()
            cleanup_obs["budget"] = budget
            cleanup_obs["zero_build"] = inner.require_zero_builds(budget)
        finally:
            if report_sink is not None:
                report_sink.clear()
                report_sink.update(dict(reports.get("exploration") or {}))
                report_sink.update(identity=dict(frozen), server_inventory=server_inv, cleanup=dict(cleanup_obs))
    return {
        **exp_rep,
        "bases": dict(bases),
        "identity": dict(frozen),
        "server_inventory": server_inv,
        "cleanup": dict(cleanup_obs),
    }


@dataclass
class D12SystemSession:
    repo_root: Path
    config: SystemTestConfig
    proof_path: Path
    proof: dict[str, Any]
    proof_sha256: str
    grant: dict[str, Any]
    grant_sha256: str
    expected_candidate: dict[str, Any]
    expected_candidate_sha256: str
    frozen_identity: dict[str, Any]
    frozen_identity_fn: Callable[[Path, str], dict[str, Any]] = d12.frozen_identity
    stage_context_fn: Callable[[Path, Path, d12.D12Admission], Path] = d12.stage_context
    preflight_report: dict[str, Any] | None = None
    temp_container_ids: list[str] = field(default_factory=list)
    _established_token: object = None
    preflight_sha256: str = field(default="", init=False)
    intent_sha256: str = field(default="", init=False)
    grant_id: str = field(default="", init=False)
    intent_payload: dict[str, Any] | None = field(default=None, init=False)
    image_id: str | None = field(default=None, init=False)
    staged_context_dir: Path | None = field(default=None, init=False)
    rendered_dockerfile_path: Path | None = field(default=None, init=False)
    post_build_probes: dict[str, Any] | None = field(default=None, init=False)
    post_build_assessments: dict[str, Any] | None = field(default=None, init=False)
    roundtrip_evidence: dict[str, Any] | None = field(default=None, init=False)
    _lock_fd: int | None = field(default=None, init=False)
    _build_consumed: bool = field(default=False, init=False)
    _established_run: Any = field(default=None, init=False)
    _binding_digest: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self._established_run = active_resource_run()
        self._binding_digest = self._compute_binding_digest()

    def _compute_binding_digest(self) -> str:
        return compute_session_binding_digest(
            proof=self.proof, grant=self.grant, expected_candidate=self.expected_candidate,
            frozen_identity=self.frozen_identity, proof_sha256=self.proof_sha256,
            grant_sha256=self.grant_sha256, expected_candidate_sha256=self.expected_candidate_sha256,
        )

    def _write_bounded_json(self, filename: str, payload: Mapping[str, Any], *, reserve_ok: bool = False) -> str:
        raw = (json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
        if (r_dir := self.config.report_dir) is not None:
            r_dir.mkdir(parents=True, exist_ok=True)
            target = r_dir / filename
            ceil = d12.REPORT_TOTAL_LIMIT - (0 if reserve_ok else d12.REPORT_CLEANUP_RESERVE)
            others = sum(p.stat().st_size for p in r_dir.glob("*.json") if p != target)
            if len(raw) > d12.REPORT_PART_LIMIT or others + len(raw) > ceil:
                raise SystemTestError(f"D12 system report part {filename} exceeds evidence ceiling")
            target.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def establish(
        cls, *, repo_root: Path, config: SystemTestConfig, proof_json_arg: object,
        target_arch_fn: Callable[[], str] = resolve_target_arch,
        tree_sha_fn: Callable[[Path], str] = get_current_tree_sha,
        frozen_identity_fn: Callable[[Path, str], dict[str, Any]] = d12.frozen_identity,
        stage_context_fn: Callable[[Path, Path, d12.D12Admission], Path] = d12.stage_context,
        run_git_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        grant_path: Path | None = None, expected_candidate_path: Path | None = None,
    ) -> D12SystemSession:
        p_path, proof, proof_sha, grant, grant_sha, expected_cand, cand_sha, frozen = (
            load_and_verify_session_authority(
                repo_root=repo_root, config=config, proof_json_arg=proof_json_arg,
                target_arch_fn=target_arch_fn, tree_sha_fn=tree_sha_fn,
                frozen_identity_fn=frozen_identity_fn, run_git_fn=run_git_fn,
                grant_path=grant_path, expected_candidate_path=expected_candidate_path,
            )
        )
        return cls(
            repo_root=repo_root, config=config, proof_path=p_path, proof=proof, proof_sha256=proof_sha,
            grant=grant, grant_sha256=grant_sha, expected_candidate=expected_cand,
            expected_candidate_sha256=cand_sha, frozen_identity=frozen,
            frozen_identity_fn=frozen_identity_fn, stage_context_fn=stage_context_fn,
            preflight_report=None, temp_container_ids=[], _established_token=_ESTABLISHED_SENTINEL,
        )

    def run_same_daemon_preflight(
        self, *, timeout_seconds: float = 300.0, deadline: Any | None = None,
        explore_fn: Callable[..., dict[str, Any]] = _default_same_daemon_preflight,
        libpq_version: int = D12_CANDIDATE_LIBPQ_VERSION, amd64_packages: PlatformPackages | None = None,
    ) -> dict[str, Any]:
        d12_ctx = self.proof["d12_context"]
        sink: dict[str, Any] = {}
        try:
            report = explore_fn(
                self.repo_root, platform="linux/amd64", timeout_seconds=timeout_seconds,
                expected_recipe_sha256=str(d12_ctx["recipe_sha256"]),
                expected_source_sha256=str(d12_ctx["source_sha256"]),
                expected_dockerfile_sha256=str(d12_ctx["dockerfile_sha256"]),
                deadline=deadline, report_sink=sink,
            )
        except Exception as exc:
            if sink:
                self.preflight_report = dict(sink)
                try:
                    self.preflight_sha256 = self._write_bounded_json("d12-preflight-exploration.json", sink)
                except SystemTestError:
                    pass
            raise (exc if isinstance(exc, SystemTestError) else SystemTestError(f"preflight failed: {exc}")) from exc
        self.preflight_report = dict(report)
        self.preflight_sha256 = self._write_bounded_json("d12-preflight-exploration.json", report)
        verify_preflight_matches_manifest(
            report, proof=self.proof, libpq_version=libpq_version, amd64_packages=amd64_packages
        )
        return self.preflight_report

    def validate_for_candidate_build(self, *, repo_root: Path, config: SystemTestConfig) -> d12.D12Admission:
        if self._established_token is not _ESTABLISHED_SENTINEL:
            raise SystemTestError("candidate image build requires an established D12SystemSession")
        if self._compute_binding_digest() != self._binding_digest or self.proof.get("nonce") != self.grant.get("nonce"):
            raise SystemTestError("D12 session in-memory binding digest drifted or nonce disagrees")
        if (
            self.repo_root.resolve(), self.config.run_id, self.config.candidate_tag,
            self.config.candidate_commit_sha, self.config.candidate_tree_sha,
        ) != (
            repo_root.resolve(), config.run_id, config.candidate_tag,
            config.candidate_commit_sha, config.candidate_tree_sha,
        ):
            raise SystemTestError("D12 session binding disagrees with active candidate build config")
        run = active_resource_run()
        canonical_run_id = getattr(getattr(getattr(run, "ledger", None), "identity", None), "run_id", None)
        if (
            run is None or self._established_run is None or run is not self._established_run
            or not isinstance(canonical_run_id, str) or not canonical_run_id or canonical_run_id != config.run_id
        ):
            raise SystemTestError("D12 session requires an active unchanged canonical resource run")
        if self.preflight_report is None:
            raise SystemTestError("same-daemon preflight must succeed before candidate build")
        pf_b = self.preflight_report.get("bindings")
        if not isinstance(pf_b, Mapping) or pf_b.get("run_id") != canonical_run_id:
            raise SystemTestError("D12 session preflight bindings.run_id disagrees with active canonical resource run")
        verify_preflight_matches_manifest(self.preflight_report, proof=self.proof)
        live_frozen = self.frozen_identity_fn(self.repo_root, "linux/amd64")
        d12_ctx = self.proof.get("d12_context")
        if not isinstance(d12_ctx, Mapping) or any(live_frozen.get(k) != d12_ctx.get(k) for k in _CTX_KEYS):
            raise SystemTestError("live D12 source or recipe identity drifted before candidate build")
        return d12.D12Admission(platform="linux/amd64", node_id="main-system-gate", **live_frozen)

    def prepare_candidate_build_inputs(self, *, scratch_root: Path, dockerfile_content: str) -> tuple[Path, Path]:
        admission = self.validate_for_candidate_build(repo_root=self.repo_root, config=self.config)
        df_bytes = dockerfile_content.encode("utf-8")
        if hashlib.sha256(df_bytes).hexdigest() != admission.dockerfile_sha256:
            raise SystemTestError("rendered diagnostic Dockerfile SHA-256 drifted from D12 admission proof")
        try:
            staged_dir = self.stage_context_fn(self.repo_root, scratch_root / "context", admission)
        except Exception as exc:
            raise SystemTestError(f"D12 build context staging failed: {exc}") from exc
        dockerfile_path = scratch_root / "Dockerfile"
        dockerfile_path.write_bytes(df_bytes)
        os.chmod(dockerfile_path, 0o600)
        if hashlib.sha256(dockerfile_path.read_bytes()).hexdigest() != admission.dockerfile_sha256:
            raise SystemTestError("staged diagnostic Dockerfile bytes drifted after write")
        self.staged_context_dir = staged_dir
        self.rendered_dockerfile_path = dockerfile_path
        return staged_dir, dockerfile_path

    def reserve_one_use_candidate_build(self, *, nonce_fn: Callable[[], str] | None = None) -> dict[str, Any]:
        if self._build_consumed:
            raise SystemTestError("second system candidate image build attempt refused by D12 session")
        if self.preflight_report is None or self.config.report_dir is None:
            raise SystemTestError("same-daemon preflight and report_dir are required before reserving candidate build")
        self.validate_for_candidate_build(repo_root=self.repo_root, config=self.config)
        grant_nonce, proof_nonce = self.grant.get("nonce"), self.proof.get("nonce")
        nonce = str(grant_nonce) if nonce_fn is None else nonce_fn()
        if not isinstance(nonce, str) or not _HEX32_RE.match(nonce) or nonce != grant_nonce or nonce != proof_nonce:
            raise SystemTestError(
                "D12 build intent reservation nonce must equal established grant.nonce and proof.nonce"
            )
        self.config.report_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.config.report_dir / SYSTEM_BUILD_LOCK_FILENAME
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            st = os.fstat(lock_fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
                raise OSError("build lock is not an owned regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(lock_fd)
            raise SystemTestError(f"unable to acquire exclusive D12 system build lock {lock_path}: {exc}") from exc
        self._lock_fd = lock_fd
        self.grant_id = nonce
        c, cfg = self.proof["d12_context"], self.config
        intent = {
            "schema": SYSTEM_BUILD_INTENT_SCHEMA, "intent_id": nonce, "reservation_id": nonce,
            "grant_id": nonce, "reservation_sha256": str(self.grant["reservation_sha256"]),
            "grant_sha256": self.grant_sha256, "proof_sha256": self.proof_sha256,
            "preflight_sha256": self.preflight_sha256, "workflow_ordinal": int(self.proof["workflow_ordinal"]),
            "run_id": cfg.run_id, "platform": "linux/amd64",
            "workflow_attempt": int(self.proof["workflow_attempt"]), "owner": "main-system-gate",
            "candidate_tag": cfg.candidate_tag, "candidate_sha": cfg.candidate_commit_sha,
            "candidate_tree": cfg.candidate_tree_sha, "candidate_base_parent": cfg.candidate_base_parent,
            "candidate_head_parent": cfg.candidate_head_parent,
            "d12_source_sha256": str(c["source_sha256"]), "d12_recipe_sha256": str(c["recipe_sha256"]),
            "d12_dockerfile_sha256": str(c["dockerfile_sha256"]),
        }
        self.intent_sha256 = _write_exclusive_0600_json(
            self.config.report_dir / SYSTEM_BUILD_INTENT_FILENAME, intent
        )
        self.intent_payload = intent
        self._build_consumed = True
        return intent

    def candidate_d12_labels(self) -> dict[str, str]:
        if not self.grant_id:
            raise SystemTestError("D12 build intent must be reserved before computing candidate labels")
        c = self.proof["d12_context"]
        return {
            LABEL_D12_GRANT_ID: self.grant_id,
            LABEL_D12_SOURCE_SHA256: str(c["source_sha256"]),
            LABEL_D12_RECIPE_SHA256: str(c["recipe_sha256"]),
        }

    def record_built_image_id(self, raw_image_id: str) -> str:
        cleaned = raw_image_id.strip()
        if not cleaned.startswith("sha256:") or len(cleaned) < 19:
            raise SystemTestError(f"invalid built candidate image ID: {raw_image_id!r}")
        self.image_id = cleaned
        return cleaned

    def record_temp_container_id(self, container_id: str) -> None:
        if (cid := container_id.strip()) and cid not in self.temp_container_ids:
            self.temp_container_ids.append(cid)

    def cleanup_temp_containers(self, client: Any) -> list[str]:
        errors: list[str] = []
        for cid in list(self.temp_container_ids):
            try:
                client.containers.get(cid).remove(force=True, v=True)
            except Exception as exc:
                if not any(m in str(exc).lower() for m in ("not found", "404", "no such container")):
                    errors.append(f"temp container {cid}: {exc}")
        return errors

    def close_lock(self) -> None:
        if (fd := self._lock_fd) is not None:
            for op in (lambda f: fcntl.flock(f, fcntl.LOCK_UN), os.close):
                try:
                    op(fd)
                except OSError:
                    pass
            self._lock_fd = None
