"""Synthetic and producer-driven unit-test fixtures for hosted native D12 qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
for _rel in ("tools", "src/main/python", "src/test/support/python"):
    if (_p := str((ROOT / _rel).resolve())) not in sys.path:
        sys.path.insert(0, _p)

import d12_dependency_preflight as inner
import d12_libpq_runtime_probe
from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE, DebPackage, PlatformPackages,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support.d12_core_image_cleanup import run_candidate_cleanup

from ci.d12_hosted_evidence import (
    EXPECTED_CANDIDATE_SCHEMA, EXPECTED_SDK_DOCKERFILE_SHA256, EXPECTED_SDK_HELPER_SHA256,
    EXPECTED_SDK_IMAGE_TAG, SEALED_EVIDENCE_SCHEMA, SYSTEM_HOLD_REFUSAL_SCHEMA,
)
from ci.d12_hosted_reports import APPLICATION_BUILD_COUNT_KEYS, RESIDUE_ZERO_KEYS, VERIFIED_AMD64_BASE_METADATA

CANDIDATE_SHA, CANDIDATE_TREE, BASE_PARENT_SHA, HEAD_PARENT_SHA = "1" * 40, "2" * 40, "3" * 40, "4" * 40
SYNTHETIC_D12_SOURCE_SHA256, SYNTHETIC_D12_RECIPE_SHA256 = "a" * 64, "b" * 64
SYNTHETIC_D12_DOCKERFILE_SHA256, SYNTHETIC_SDK_RECIPE_SHA256 = "c" * 64, "d" * 64
SYNTHETIC_EXPECTED_RECORD_SHA256, SYNTHETIC_INTENT_RECEIPT_SHA256 = "e" * 64, "f" * 64
SYNTHETIC_SDK_IMAGE_ID, SYNTHETIC_RUN_ID = "sha256:" + "01" * 32, "run-99001122"


def make_expected_candidate_record() -> dict[str, Any]:
    return {"schema": EXPECTED_CANDIDATE_SCHEMA, "platform": "linux/amd64",
            "d12_context": {"source_sha256": SYNTHETIC_D12_SOURCE_SHA256, "recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256,
                            "dockerfile_sha256": SYNTHETIC_D12_DOCKERFILE_SHA256, "context_file_count": 694},
            "sdk_sandbox": {"image_tag": EXPECTED_SDK_IMAGE_TAG,
                            "sdk_dockerfile_sha256": EXPECTED_SDK_DOCKERFILE_SHA256,
                            "sdk_helper_sha256": EXPECTED_SDK_HELPER_SHA256,
                            "sdk_recipe_sha256": SYNTHETIC_SDK_RECIPE_SHA256}}


def make_frozen_identity() -> dict[str, Any]:
    return {"platform": "linux/amd64", "source_sha256": SYNTHETIC_D12_SOURCE_SHA256,
            "recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256, "dockerfile_sha256": SYNTHETIC_D12_DOCKERFILE_SHA256,
            "context_file_count": 694}


def make_pr_event_payload(
    *, repository: str = "Knowledge-Forge-AI/repo-map", base_ref: str = "main",
    head_ref: str = "staging", base_sha: str = BASE_PARENT_SHA, head_sha: str = HEAD_PARENT_SHA,
) -> dict[str, Any]:
    return {"pull_request": {
        "number": 42, "base": {"ref": base_ref, "sha": base_sha, "repo": {"full_name": repository}},
        "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": repository}}}}


def make_hosted_env(
    event_path: Path, *, run_attempt: str = "1", event_name: str = "pull_request",
    repository: str = "Knowledge-Forge-AI/repo-map", github_sha: str = CANDIDATE_SHA,
    runner_os: str = "Linux", runner_arch: str = "X64",
) -> dict[str, str]:
    return {"GITHUB_EVENT_NAME": event_name, "GITHUB_EVENT_PATH": str(event_path), "GITHUB_REPOSITORY": repository,
            "GITHUB_RUN_ID": "99001122", "GITHUB_RUN_ATTEMPT": run_attempt, "GITHUB_SHA": github_sha,
            "CANDIDATE_SHA": github_sha, "CANDIDATE_TREE": CANDIDATE_TREE, "CANDIDATE_BASE_PARENT": BASE_PARENT_SHA,
            "CANDIDATE_HEAD_PARENT": HEAD_PARENT_SHA, "RUNNER_OS": runner_os, "RUNNER_ARCH": runner_arch}


def make_fake_command_runner(
    *, head_sha: str = CANDIDATE_SHA, tree_sha: str = CANDIDATE_TREE,
    base_parent: str = BASE_PARENT_SHA, head_parent: str = HEAD_PARENT_SHA,
    daemon_arch: str = "x86_64", daemon_os: str = "linux", operating_system: str = "Ubuntu 24.04.1 LTS",
    sdk_image_id: str = SYNTHETIC_SDK_IMAGE_ID, sdk_arch: str | None = "amd64",
) -> Any:
    rev_map = {"HEAD": head_sha, "HEAD^{tree}": tree_sha, "HEAD^1": base_parent, "HEAD^2": head_parent}
    labels = {"org.repomap.test.sandbox.image": "true",
              "org.repomap.test.sandbox.recipe": SYNTHETIC_SDK_RECIPE_SHA256}

    def _run(args: list[str], *_pos: Any, **_kw: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "rev-parse"] and len(args) == 3 and (t := args[2]) in rev_map:
            return subprocess.CompletedProcess(args, 0, f"{rev_map[t]}\n", "")
        if args[:2] == ["docker", "info"]:
            info = {"OSType": daemon_os, "Architecture": daemon_arch,
                    "OperatingSystem": operating_system, "DriverStatus": [["Backing Filesystem", "extfs"]]}
            return subprocess.CompletedProcess(args, 0, json.dumps(info), "")
        if args[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(args, 0, "built\n", "")
        if args[:3] == ["docker", "image", "inspect"]:
            doc: dict[str, Any] = {"Id": sdk_image_id, "Config": {"Labels": labels}}
            if sdk_arch is not None:
                doc["Architecture"] = sdk_arch
            return subprocess.CompletedProcess(args, 0, json.dumps(doc), "")
        return subprocess.CompletedProcess(args, 1, "", f"unexpected command: {args}")

    return _run


class _FakeImage:
    def __init__(self, image_id: str, digest_ref: str) -> None:
        self.id = image_id
        self.attrs = {"Id": image_id, "Os": "linux", "Architecture": "amd64",
                      "RepoDigests": [digest_ref], "Config": {"Volumes": None}}


class _FakeContainer:
    def start(self) -> None:
        pass


class _FakeDockerClient:
    def __init__(self) -> None:
        self._map = {
            ref: _FakeImage(VERIFIED_AMD64_BASE_METADATA[k]["config"], ref)
            for ref, k in ((POSTGRES_RELEASE_IMAGE, "postgres"), (PYTHON_RELEASE_IMAGE, "python"),
                           (GO_RELEASE_IMAGE, "go"))
        }
        self.images = self

    def get(self, reference: str) -> _FakeImage:
        if reference not in self._map:
            raise type("ImageNotFound", (Exception,), {})(reference)
        return self._map[reference]

    def info(self) -> dict[str, Any]:
        return {"Architecture": "x86_64", "Driver": "overlay2"}

    def version(self) -> dict[str, Any]:
        return {"Version": "29.4.0", "ApiVersion": "1.51"}


class _FakeContainerOwner:
    def cleanup(self, _identity: str) -> None:
        pass

    def verify_baseline(self) -> None:
        pass


def make_zero_projection() -> dict[str, int]:
    keys = (*APPLICATION_BUILD_COUNT_KEYS, *RESIDUE_ZERO_KEYS,
            "managed_test_runtime_image_build_count", "managed_runtime_build_intermediate_created_count",
            "managed_runtime_build_intermediate_removed_count", "managed_external_base_pull_count",
            "new_managed_external_test_base_images", "new_managed_test_runtime_cache_images")
    return {**dict.fromkeys(keys, 0), "managed_test_runtime_image_build_count": 1}


def make_positive_amd64_closure(ver: str = "18.6-1.pgdg13+2") -> dict[str, Any]:
    py_meta = VERIFIED_AMD64_BASE_METADATA["python"]
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    libc, real = "/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/x86_64-linux-gnu/libc.so.6"
    ok, names = f"\tlibc.so.6 => {libc} (0x2)\n", list(entry.baseline_imports)
    elves = {f"{payload.DYNLOAD}/{n}.cpython-312-x86_64-linux-gnu.so": {
        "sha256": hashlib.sha256(n.encode()).hexdigest(), "size": 1, "elf": [2, 1, 62], "ldd": ok, "ldd_exit": 0}
        for n in names}
    for idx in range(4):
        elves[f"/usr/local/bin/py{idx}"] = {"sha256": hashlib.sha256(f"py{idx}".encode()).hexdigest(), "size": 1,
                                            "elf": [2, 1, 62], "ldd": ok, "ldd_exit": 0}
    elves[entry.path] = {"sha256": entry.sha256, "size": entry.size, "elf": [2, 1, 62], "ldd_exit": 0,
                         "ldd": ok + "\tlibtk8.6.so => not found\n\tlibtcl8.6.so => not found\n"}
    base: dict[str, Any] = {
        "machine": "x86_64", "entries": 1721, "digest": "0" * 64, "elves": elves, "targets": {libc: [real, "a" * 64]},
        "dynload": sorted([p.rsplit("/", 1)[1], "file"] for p in elves if p.startswith(payload.DYNLOAD + "/")),
        "dynload_real": payload.DYNLOAD, "imports": names, "failed": {"_tkinter": {"exit": 1, "error": "ImportError"}},
    }
    before = {p: ["file", e["sha256"], e["size"], 33188] for p, e in elves.items()}
    after = {**base, "entries": 1720, "elves": {p: e for p, e in elves.items() if p != entry.path}, "failed": {},
             "dynload": [r for r in base["dynload"] if not entry.path.endswith(r[0])]}
    ret = {**payload.verify_retained(before, {p: v for p, v in before.items() if p != entry.path}, after, entry,
                                     {libc: "libc6"}), "entries": 1720}
    prog_sha = hashlib.sha256(Path(payload.__file__).read_bytes()).hexdigest()
    return {
        "contract": {"program_sha256": prog_sha, "python_config": py_meta["config"], "native": "native",
                     "exclusion_applies": True, "exit": 0, "result": "trimmed", "reasons": []},
        "baseline": base, "exclusion": payload.classify(base, entry), "retained": ret,
        "baseline_unresolved": payload.unresolved(elves), "baseline_failed": ["_tkinter"], "elf_count": 81,
        "dependencies": {libc: {"real": real, "sha256": "a" * 64, "package": "libc6", "version": ver,
                                "architecture": "amd64"}},
        "unresolved": [], "packages": [("libpq5", ver, "amd64")], "lib_dynload": names, "imports": names,
    }


def write_inner_reports(
    report_dir: Path, *, positive: bool = False, source_sha256: str = SYNTHETIC_D12_SOURCE_SHA256,
) -> Path:
    """Emit canonical freeze.json, exploration.json, and cleanup.json using the real producer functions."""
    inner_dir = report_dir / "d12-core-image/linux-amd64"
    inner_dir.mkdir(parents=True, exist_ok=True)
    client, owner = _FakeDockerClient(), _FakeContainerOwner()
    admission = d12.D12Admission(
        platform="linux/amd64", node_id=d12.NODE_ID, source_sha256=source_sha256,
        recipe_sha256=SYNTHETIC_D12_RECIPE_SHA256, dockerfile_sha256=SYNTHETIC_D12_DOCKERFILE_SHA256,
        context_file_count=694)
    inspected = subprocess.CompletedProcess(
        ["docker", "buildx", "inspect"], 0,
        "Driver: docker-container\nStatus: running\nBuildKit version: v0.17.0\nPlatforms: linux/amd64*\n", "")
    availability = d12.platform_availability(
        "linux/amd64", client.info()["Architecture"], d12.offered_platforms(inspected.stdout))
    bases = d12.verify_bases(client, "linux/amd64", (POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE, GO_RELEASE_IMAGE))
    budget = make_zero_projection()
    labels = {"org.repomap.d12.candidate": "true", "org.repomap.d12.platform": "linux/amd64",
              "org.repomap.d12.source_sha256": source_sha256,
              "org.repomap.d12.recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256,
              "org.repomap.test.resource.run_id": SYNTHETIC_RUN_ID}

    def _writer(name: str, payload: Any) -> Path:
        out = inner_dir / f"{name}.json"
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return out

    _writer("freeze", {"admission": vars(admission), "availability": availability, "bases": bases,
                       "tag": f"repomap-d12-core-candidate:{SYNTHETIC_RUN_ID}-amd64", "labels": labels,
                       "budget": budget})
    ver, lib_path, lib_sha = "18.6-1.pgdg13+2", "/usr/lib/x86_64-linux-gnu/libpq.so.5.18", "7" * 64
    pgdg_src = "/etc/apt/sources.list.d/pgdg.sources"
    pgdg_key = "/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg"
    pkg_pq = {"name": "libpq5", "version": ver, "architecture": "amd64", "sha256": "4" * 64}
    pkg_dev = {"name": "libpq-dev", "version": ver, "architecture": "amd64", "sha256": "6" * 64}
    server_inventory = {"packages": [["libpq5", ver, "amd64"]],
                        "files": [{"role": "libpq", "owner": "libpq5", "resolved": lib_path, "sha256": lib_sha}]}
    orig_trust, orig_closure = inner.trust_facts, inner.closure_facts
    orig_resolve, orig_observe = inner.resolve, inner.runtime.observe

    def _fake_trust(steps: dict[str, Any], container: Any) -> dict[str, bytes]:
        _ = container
        steps["trust"] = {"sources": {pgdg_src: {"sha256": "8" * 64, "signed_by": [pgdg_key]}},
                          "keyrings": {pgdg_key: "9" * 64}, "fingerprints": {"primary": ["A" * 40], "subkeys": []},
                          "pgdg_source": pgdg_src, "pgdg_keyring": pgdg_key}
        return {pgdg_src: b"deb", pgdg_key: b"key"}

    def _fake_closure(steps: dict[str, Any], container: Any, platform: str) -> dict[str, Any]:
        _ = (container, platform)
        if not positive:
            steps["closure"] = {"unresolved": ["libmissing.so.1"], "baseline_failed": [], "elf_count": 42,
                                "retained": {"preserved": False, "unresolved": []}, "imports": ["_ssl", "math"],
                                "packages": [("libpq5", ver, "amd64")]}
            raise inner.PreflightRefusal("unconfigured Python payload exclusion baseline for amd64")
        steps["closure"] = make_positive_amd64_closure(ver)
        return steps["closure"]

    def _fake_resolve(
        container: Any, platform: str, request: Sequence[str], *,
        trust: Mapping[str, bytes] | None = None, missing_only: bool = False,
    ) -> dict[str, Any]:
        _ = (container, platform, request, trust)
        return {"native": "amd64", "preexisting_rows": 140 if missing_only else 120,
                "packages": [pkg_pq] if missing_only else [pkg_pq, pkg_dev], "trusted_targets": []}

    def _fake_observe(
        container: Any, steps: Mapping[str, Any], server_inventory: Mapping[str, Any],
        platform: str, bindings: Mapping[str, object],
    ) -> dict[str, Any]:
        _ = container
        exp_in, hashes = d12_libpq_runtime_probe.binding(steps, server_inventory, platform, str(bindings["run_id"]))
        return d12_libpq_runtime_probe.record(
            exp_in, hashes, api=180006, machine="x86_64",
            selected=[[pkg_pq["name"], pkg_pq["version"], pkg_pq["architecture"], pkg_pq["sha256"]]],
            digests=("b" * 64, "c" * 64))

    primary: BaseException | None = None
    inner.trust_facts, inner.closure_facts = _fake_trust, _fake_closure
    inner.resolve, inner.runtime.observe = _fake_resolve, _fake_observe
    try:
        inner.explore(
            owner, client, admission, bases=bases, availability=availability, inspected=inspected,
            server_inventory=server_inventory, create=lambda *_a, **_kw: ("cid-1", _FakeContainer()),
            bindings={"run_id": SYNTHETIC_RUN_ID, "sdk_image": "unobserved in the sandbox"}, write_report=_writer)
    except BaseException as exc:
        primary = exc
    finally:
        inner.trust_facts, inner.closure_facts = orig_trust, orig_closure
        inner.resolve, inner.runtime.observe = orig_resolve, orig_observe

        def _custody(cleanup: dict[str, object]) -> None:
            cleanup.update({"candidate_image_id": None, "server": "removed", "containers": "baseline_verified",
                            "budget": budget, "zero_build": inner.require_zero_builds(budget)})

        run_candidate_cleanup(primary, _custody, _writer)
    return inner_dir


def make_partial_refused_exploration() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        p = write_inner_reports(Path(tmp), positive=False) / "exploration.json"
        return dict(json.loads(p.read_text(encoding="utf-8")))


def make_positive_exploration() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        p = write_inner_reports(Path(tmp), positive=True) / "exploration.json"
        return dict(json.loads(p.read_text(encoding="utf-8")))


def make_sealed_evidence(*, positive: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        inner_dir = write_inner_reports(Path(tmp), positive=positive)
        freeze = json.loads((inner_dir / "freeze.json").read_text(encoding="utf-8"))
        exploration = json.loads((inner_dir / "exploration.json").read_text(encoding="utf-8"))
        cleanup = json.loads((inner_dir / "cleanup.json").read_text(encoding="utf-8"))
    repo = "Knowledge-Forge-AI/repo-map"
    return {
        "schema": SEALED_EVIDENCE_SCHEMA, "platform": "linux/amd64",
        "result": "passed" if positive else "refused", "qualified": bool(positive),
        "runner_exit_code": 0 if positive else 1,
        "pr_binding": {
            "event_name": "pull_request", "run_id": "99001122", "run_attempt": 1,
            "repository": repo, "base_repo": repo, "head_repo": repo, "base_ref": "main", "head_ref": "staging",
            "candidate_sha": CANDIDATE_SHA, "github_sha": CANDIDATE_SHA, "head_commit_sha": CANDIDATE_SHA,
            "candidate_tree": CANDIDATE_TREE, "candidate_base_parent": BASE_PARENT_SHA,
            "event_base_sha": BASE_PARENT_SHA, "candidate_head_parent": HEAD_PARENT_SHA,
            "event_head_sha": HEAD_PARENT_SHA,
        },
        "identity_binding": {
            "expected_candidate_sha256": SYNTHETIC_EXPECTED_RECORD_SHA256,
            "d12_context": {
                "source_sha256": SYNTHETIC_D12_SOURCE_SHA256, "recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256,
                "dockerfile_sha256": SYNTHETIC_D12_DOCKERFILE_SHA256, "context_file_count": 694,
                "matches_expected": True,
            },
            "sdk_sandbox": {
                "image_tag": EXPECTED_SDK_IMAGE_TAG, "sdk_dockerfile_sha256": EXPECTED_SDK_DOCKERFILE_SHA256,
                "sdk_helper_sha256": EXPECTED_SDK_HELPER_SHA256, "sdk_recipe_sha256": SYNTHETIC_SDK_RECIPE_SHA256,
                "matches_expected": True,
            },
        },
        "native_environment": {"runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux",
                               "host_arch": "x86_64", "docker_daemon_arch": "x86_64", "emulated": False},
        "sdk_materialization": {
            "image_tag": EXPECTED_SDK_IMAGE_TAG, "sdk_image_id": SYNTHETIC_SDK_IMAGE_ID, "sdk_architecture": "amd64",
            "sdk_recipe_sha256": SYNTHETIC_SDK_RECIPE_SHA256, "sdk_build_attempts": 1,
            "intent_recorded_before_build": True, "intent_receipt_sha256": SYNTHETIC_INTENT_RECEIPT_SHA256,
            "sdk_cache_cold_built": True, "whole_job_image_parity_claimed": False,
            "added_sdk_images": [SYNTHETIC_SDK_IMAGE_ID], "removed_sdk_images": [],
            "entry_baseline": {"containers": [], "images": [], "volumes": [], "networks": ["bridge"]},
            "post_sdk_baseline": {"containers": [], "images": [SYNTHETIC_SDK_IMAGE_ID],
                                  "volumes": [], "networks": ["bridge"]},
            "post_sdk_cleanup": {
                "containers_added": [], "containers_removed": [], "images_added": [], "images_removed": [],
                "volumes_added": [], "volumes_removed": [], "networks_added": [], "networks_removed": [],
                "clean_against_post_sdk_baseline": True,
            },
        },
        "application_builds": {
            "application_builds": 0, "application_candidate_builds": 0,
            "managed_system_candidate_image_build_count": 0, "product_or_build_profile_build_count": 0,
            "unmanaged_build_count": 0, "unmanaged_pull_count": 0,
        },
        "inner_reports": {"freeze": copy.deepcopy(freeze), "exploration": copy.deepcopy(exploration),
                          "cleanup": copy.deepcopy(cleanup)},
        "report_provenance": {
            k: {"status": "valid", "redacted": False, "redacted_modified": False, "bytes": 100, "raw_sha256": c * 64}
            for k, c in (("freeze", "a"), ("exploration", "b"), ("cleanup", "c"))
        },
        "validation_violations": [], "seal_errors": [],
    }


def make_valid_amd64_packages() -> PlatformPackages:
    ver = "18.6-1.pgdg13+2"
    return PlatformPackages(
        postgres_config_digest="sha256:" + ("a" * 64),
        pgdg_source=("/etc/apt/sources.list.d/pgdg.sources", "b" * 64),
        pgdg_keyring=("/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg", "c" * 64),
        key_fingerprints=("D" * 40,), libpq_path="/usr/lib/x86_64-linux-gnu/libpq.so.5.18",
        libpq_sha256="e" * 64, libpq5_version=ver,
        builder=(DebPackage("libpq5", ver, "amd64", "1" * 64), DebPackage("libpq-dev", ver, "amd64", "2" * 64)),
        closure=(DebPackage("libpq5", ver, "amd64", "1" * 64),), lib_dynload=payload.ARM64_BASELINE_IMPORTS,
    )


def make_system_hold_refusal_report() -> dict[str, Any]:
    return {
        "schema": SYSTEM_HOLD_REFUSAL_SCHEMA, "gate_kind": "main-system", "target_arch": "amd64",
        "result": "refused_release_prerequisites_unresolved", "qualified": False, "sdk_builds_started": 0,
        "application_candidate_builds_started": 0, "managed_system_candidate_image_build_count": 0,
        "candidate_sha": CANDIDATE_SHA, "candidate_tree": CANDIDATE_TREE, "candidate_base_parent": BASE_PARENT_SHA,
        "candidate_head_parent": HEAD_PARENT_SHA, "d12_source_sha256": SYNTHETIC_D12_SOURCE_SHA256,
        "d12_recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256, "d12_dockerfile_sha256": SYNTHETIC_D12_DOCKERFILE_SHA256,
        "reasons": ["System candidate build refused before Docker build: PSYCOPG_LIBPQ_VERSION=None is unresolved."],
    }


def write_expected_candidate_file(path: Path) -> str:
    doc = json.dumps(make_expected_candidate_record(), indent=2, sort_keys=True) + "\n"
    path.write_text(doc, encoding="utf-8")
    return hashlib.sha256(doc.encode("utf-8")).hexdigest()
