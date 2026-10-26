"""Candidate release image build and verification for the main system gate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, Any

from repomap_kg.runtime.commands import render_server_dockerfile
from repomap_kg.runtime.release import (
    DYNAMIC_PACKAGE_MANIFEST, GO_RELEASE_IMAGE, PRODUCT_MINIMUM_LIBPQ_VERSION,
    PSYCOPG_LIBPQ_VERSION, PlatformPackages, validate_package_manifest,
)
from repomap_kg.runtime.release_manifest import (
    D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST,
)
from tools.system.candidate_identity import (
    get_current_tree_sha as get_current_tree_sha,
    resolve_target_arch as resolve_target_arch,
)
from tools.system.config import (
    IMAGE_CLASS_SYSTEM_CANDIDATE, LABEL_CANDIDATE_TREE, LABEL_IMAGE_CLASS, LABEL_MANAGED,
    LABEL_RELEASE_GO, LABEL_RELEASE_LIBPQ, LABEL_RELEASE_POSTGRES, LABEL_RELEASE_PSYCOPG,
    LABEL_RELEASE_PYTHON, LABEL_RUN_ID, SystemTestConfig, SystemTestError,
)

if TYPE_CHECKING:
    from tools.system.d12_system_session import D12SystemSession


@dataclass(frozen=True)
class CandidateImageMetadata:
    image_id: str
    image_tag: str
    image_digest: str
    labels: dict[str, str]
    release_versions: dict[str, str]
    created_image_ids: tuple[str, ...] = ()


def require_release_prerequisites_resolved(
    target_arch: str = "amd64", *, libpq_version: object = ..., package_manifest: object = ...,
) -> tuple[int, PlatformPackages]:
    ver: object = PSYCOPG_LIBPQ_VERSION if libpq_version is ... else libpq_version
    manifest: object = DYNAMIC_PACKAGE_MANIFEST if package_manifest is ... else package_manifest
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < PRODUCT_MINIMUM_LIBPQ_VERSION:
        raise SystemTestError(
            f"System candidate build refused before Docker build: PSYCOPG_LIBPQ_VERSION={ver!r} is unresolved."
        )
    if not isinstance(manifest, Mapping) or target_arch not in manifest:
        raise SystemTestError(
            f"System candidate build refused before Docker build: DYNAMIC_PACKAGE_MANIFEST lacks {target_arch!r}."
        )
    entry = manifest[target_arch]
    if not isinstance(entry, PlatformPackages):
        raise SystemTestError("System candidate build refused before Docker build: invalid manifest entry.")
    try:
        validate_package_manifest({target_arch: entry}, ver)
    except ValueError as error:
        raise SystemTestError(f"System candidate build refused before Docker build: {error}") from error
    return ver, entry


def build_and_verify_candidate_image(
    repo_root: Path,
    config: SystemTestConfig,
    *,
    boundary: Any | None,
    client: Any,
    deadline: Any | None = None,
    d12_session: D12SystemSession | None = None,
) -> CandidateImageMetadata:
    """Build the assembled candidate image and verify packaging without source mounts."""
    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget("candidate image build")

    if config.execution_mode == "hosted_qualification" and d12_session is None:
        raise SystemTestError("hosted qualification candidate image build requires an active D12SystemSession")

    target_arch = resolve_target_arch()
    labels = {
        LABEL_IMAGE_CLASS: IMAGE_CLASS_SYSTEM_CANDIDATE,
        LABEL_MANAGED: "true",
        LABEL_CANDIDATE_TREE: config.candidate_tree_sha,
        LABEL_RUN_ID: config.run_id,
    }
    stage_tmp: Path | None = None
    if d12_session is not None:
        from tools.system.d12_system_session import D12SystemSession

        if not isinstance(d12_session, D12SystemSession):
            raise SystemTestError("candidate image build requires an established D12SystemSession instance")
        if boundary is None or not callable(getattr(boundary, "managed_system_candidate_build", None)):
            raise SystemTestError("Route B candidate build boundary lacks managed_system_candidate_build")
        if target_arch != "amd64":
            raise SystemTestError(
                f"Route B D12 candidate build only admits target_arch='amd64', got {target_arch!r}"
            )
        require_release_prerequisites_resolved(
            target_arch, libpq_version=D12_CANDIDATE_LIBPQ_VERSION,
            package_manifest=D12_CANDIDATE_PACKAGE_MANIFEST,
        )
        admission = d12_session.validate_for_candidate_build(repo_root=repo_root, config=config)
        current_tree = get_current_tree_sha(repo_root)
        if current_tree != config.candidate_tree_sha:
            raise SystemTestError(
                f"candidate tree SHA mismatch: expected {config.candidate_tree_sha}, got {current_tree}"
            )
        dockerfile_content = render_server_dockerfile(
            manifest=D12_CANDIDATE_PACKAGE_MANIFEST,
            libpq_version=D12_CANDIDATE_LIBPQ_VERSION,
        )
        if hashlib.sha256(dockerfile_content.encode("utf-8")).hexdigest() != admission.dockerfile_sha256:
            raise SystemTestError("rendered diagnostic Dockerfile SHA-256 drifted from D12 admission proof")
        stage_tmp = Path(tempfile.mkdtemp(prefix="repomap-d12-context-"))
        try:
            staged_context_dir, dockerfile_path = d12_session.prepare_candidate_build_inputs(
                scratch_root=stage_tmp, dockerfile_content=dockerfile_content
            )
            d12_session.reserve_one_use_candidate_build()
        except Exception:
            shutil.rmtree(stage_tmp, ignore_errors=True)
            raise
        labels.update(d12_session.candidate_d12_labels())
        iidfile_path = stage_tmp / "candidate.iid"
        build_context_arg = str(staged_context_dir)
    else:
        require_release_prerequisites_resolved(target_arch)
        current_tree = get_current_tree_sha(repo_root)
        if current_tree != config.candidate_tree_sha:
            raise SystemTestError(
                f"candidate tree SHA mismatch: expected {config.candidate_tree_sha}, got {current_tree}"
            )
        dockerfile_content = render_server_dockerfile()
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".Dockerfile", delete=False) as dockerfile:
            dockerfile.write(dockerfile_content)
            dockerfile_path = Path(dockerfile.name)
        iidfile_path = dockerfile_path.with_suffix(".iid")
        build_context_arg = str(repo_root)

    buildargs = {"TARGETOS": "linux", "TARGETARCH": target_arch}
    build_request = f"candidate-image-build:{config.candidate_tag}"
    build_timeout = (
        deadline.clamp_timeout(900.0)
        if deadline is not None and hasattr(deadline, "clamp_timeout")
        else 900.0
    )
    build_command = [
        "docker", "build", "--pull=false", "--rm", "--force-rm",
        "--iidfile", str(iidfile_path), "--file", str(dockerfile_path), "--tag", config.candidate_tag,
    ]
    if d12_session is not None:
        build_command.extend(("--platform", "linux/amd64"))
    for name, value in sorted(labels.items()):
        build_command.extend(("--label", f"{name}={value}"))
    for name, value in sorted(buildargs.items()):
        build_command.extend(("--build-arg", f"{name}={value}"))
    build_command.append(build_context_arg)
    build_context = None
    operation_ticket = None
    try:
        if d12_session is not None or (
            boundary is not None and callable(getattr(boundary, "managed_system_candidate_build", None))
        ):
            assert boundary is not None
            build_context = boundary.managed_system_candidate_build(request=build_request)
            operation_ticket = build_context.__enter__()
        try:
            built = subprocess.run(
                build_command, capture_output=True, text=True, timeout=build_timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise SystemTestError(f"candidate image build timed out after {build_timeout}s") from exc
        if built.returncode != 0:
            raise SystemTestError(
                "candidate image build failed: " + (built.stderr.strip() or built.stdout.strip())[-2000:]
            )
        image = client.images.get(config.candidate_tag)
        if d12_session is not None:
            raw_iid = (
                iidfile_path.read_text(encoding="utf-8", errors="replace").strip()
                if iidfile_path.is_file()
                else ""
            )
            if not raw_iid.startswith("sha256:"):
                raise SystemTestError(f"candidate image build did not emit a valid --iidfile digest: {raw_iid!r}")
            d12_session.record_built_image_id(raw_iid)
            if not isinstance(getattr(image, "id", None), str) or raw_iid != image.id:
                raise SystemTestError(
                    f"candidate image tag ID {getattr(image, 'id', None)!r} disagrees with iidfile {raw_iid}"
                )
        if boundary is not None and operation_ticket is not None and hasattr(boundary, "complete_operation"):
            boundary.complete_operation(operation_ticket, image_ids=(image.id,))
    finally:
        if d12_session is not None and iidfile_path.is_file():
            try:
                raw_iid = iidfile_path.read_text(encoding="utf-8", errors="replace").strip()
                if raw_iid.startswith("sha256:"):
                    d12_session.record_built_image_id(raw_iid)
            except Exception:
                pass
        if build_context is not None:
            build_context.__exit__(*sys.exc_info())
        dockerfile_path.unlink(missing_ok=True)
        iidfile_path.unlink(missing_ok=True)
        if stage_tmp is not None:
            shutil.rmtree(stage_tmp, ignore_errors=True)

    image_id = image.id
    if not image_id.startswith("sha256:"):
        raise SystemTestError(f"invalid candidate image ID format: {image_id}")
    created_image_ids: tuple[str, ...] = (image_id,) if d12_session is not None else ()

    image_labels = image.labels or {}
    expected_label_checks = [
        (LABEL_IMAGE_CLASS, IMAGE_CLASS_SYSTEM_CANDIDATE),
        (LABEL_CANDIDATE_TREE, config.candidate_tree_sha),
        (LABEL_MANAGED, "true"),
        (LABEL_RUN_ID, config.run_id),
    ]
    if d12_session is not None:
        expected_label_checks.extend(sorted(d12_session.candidate_d12_labels().items()))
    for label_name, expected_val in expected_label_checks:
        if image_labels.get(label_name) != expected_val:
            raise SystemTestError(
                f"candidate image missing or invalid label {label_name}: {image_labels.get(label_name)!r}"
            )

    for rel_label in (
        LABEL_RELEASE_POSTGRES, LABEL_RELEASE_PYTHON, LABEL_RELEASE_GO,
        LABEL_RELEASE_PSYCOPG, LABEL_RELEASE_LIBPQ,
    ):
        if rel_label not in image_labels:
            raise SystemTestError(f"candidate image missing required release label {rel_label}")

    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget("candidate image self-test")

    self_test_script = (
        "import json, os, platform, subprocess, sys, psycopg, repomap_kg; "
        "from psycopg import pq; "
        "from repomap_kg.storage import discover_migrations; "
        "from repomap_kg.coordinator._control_schema import discover_control_migrations; "
        "from repomap_kg.extractors.languages.go_helper import resolve_go_helper_command; "
        "assert discover_migrations(), 'missing graph migrations'; "
        "assert discover_control_migrations(), 'missing control migrations'; "
        "helper_cmd = resolve_go_helper_command(); "
        "assert helper_cmd and os.access(helper_cmd[0], os.X_OK), 'go helper missing or not executable'; "
        "proto_res = subprocess.run("
        "[helper_cmd[0], '--protocol-version'], capture_output=True, text=True, check=True); "
        "helper_proto = proto_res.stdout.strip(); "
        "psql_res = subprocess.run(['psql', '--version'], capture_output=True, text=True, check=True); "
        "psql_out = psql_res.stdout.strip(); "
        "print(json.dumps({"
        "'python': platform.python_version(), 'psycopg': psycopg.__version__, "
        "'libpq': str(pq.version()), 'postgresql': psql_out, "
        "'go_helper': helper_cmd[0], 'go_helper_protocol': helper_proto, "
        "}))"
    )

    container = client.containers.create(
        image_id, entrypoint=["python", "-c", self_test_script], command=[],
        network_mode="none", labels={LABEL_RUN_ID: config.run_id, LABEL_MANAGED: "true"},
    )
    if d12_session is not None and isinstance(getattr(container, "id", None), str):
        d12_session.record_temp_container_id(container.id)
    release_versions: dict[str, str] = {}
    try:
        container.start()
        self_test_timeout = (
            int(deadline.clamp_timeout(30.0))
            if deadline is not None and hasattr(deadline, "clamp_timeout")
            else 30
        )
        res = container.wait(timeout=self_test_timeout)
        status_code = res.get("StatusCode", 1) if isinstance(res, dict) else getattr(res, "status_code", 1)
        logs = container.logs().decode("utf-8", errors="replace").strip()
        if status_code != 0:
            raise SystemTestError(f"candidate image self-test container failed (exit {status_code}): {logs}")

        lines = [line for line in logs.splitlines() if line.strip()]
        if not lines:
            raise SystemTestError("candidate image self-test emitted no output")
        try:
            parsed = json.loads(lines[-1])
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemTestError(f"candidate image self-test emitted invalid JSON: {lines[-1]!r}") from error
        if not isinstance(parsed, dict):
            raise SystemTestError(f"candidate image self-test JSON is not an object: {parsed!r}")

        observed_py, expected_py = parsed.get("python"), image_labels.get(LABEL_RELEASE_PYTHON, "")
        if not observed_py or not expected_py or observed_py != expected_py:
            raise SystemTestError(
                f"candidate self-test python version mismatch: observed {observed_py!r}, expected {expected_py!r}"
            )
        observed_psycopg, expected_psycopg = parsed.get("psycopg"), image_labels.get(LABEL_RELEASE_PSYCOPG, "")
        if not observed_psycopg or not expected_psycopg or observed_psycopg != expected_psycopg:
            raise SystemTestError(
                "candidate self-test psycopg version mismatch: "
                f"observed {observed_psycopg!r}, expected {expected_psycopg!r}"
            )
        observed_libpq, expected_libpq = parsed.get("libpq"), image_labels.get(LABEL_RELEASE_LIBPQ, "")
        if not observed_libpq or not expected_libpq or str(observed_libpq) != str(expected_libpq):
            raise SystemTestError(
                f"candidate self-test libpq version mismatch: observed {observed_libpq!r}, expected {expected_libpq!r}"
            )
        observed_pg_raw, expected_pg = parsed.get("postgresql", ""), image_labels.get(LABEL_RELEASE_POSTGRES, "")
        pg_match = re.fullmatch(r"psql \(PostgreSQL\) ([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?: .*)?", str(observed_pg_raw))
        observed_pg = pg_match.group(1) if pg_match else ""
        if not observed_pg or observed_pg != expected_pg:
            raise SystemTestError(
                "candidate self-test postgresql version mismatch: "
                f"observed {observed_pg_raw!r}, expected {expected_pg!r}"
            )
        observed_go_helper = parsed.get("go_helper")
        if not observed_go_helper or not isinstance(observed_go_helper, str):
            raise SystemTestError("candidate self-test go helper is missing or invalid")
        observed_go_helper_protocol = parsed.get("go_helper_protocol")
        if not observed_go_helper_protocol or not str(observed_go_helper_protocol).isdigit():
            raise SystemTestError(
                f"candidate self-test go helper protocol version is invalid: {observed_go_helper_protocol!r}"
            )

        with tempfile.TemporaryDirectory(prefix="repomap-go-helper-") as helper_dir:
            helper_copy = Path(helper_dir) / "helper"
            copied = subprocess.run(
                ["docker", "cp", f"{container.id}:{observed_go_helper}", str(helper_copy)],
                capture_output=True, text=True,
                timeout=(deadline.clamp_timeout(30.0) if deadline is not None else 30.0), check=False,
            )
            if copied.returncode != 0:
                raise SystemTestError("candidate Go helper extraction failed")
            go_container = client.containers.create(
                GO_RELEASE_IMAGE, command=["go", "version", "-m", "/probe/helper"], entrypoint=[],
                network_mode="none", volumes={helper_dir: {"bind": "/probe", "mode": "ro"}},
                labels={LABEL_RUN_ID: config.run_id, LABEL_MANAGED: "true"},
            )
            if d12_session is not None and isinstance(getattr(go_container, "id", None), str):
                d12_session.record_temp_container_id(go_container.id)
            try:
                go_container.start()
                go_wait = go_container.wait(
                    timeout=(int(deadline.clamp_timeout(30.0)) if deadline is not None else 30)
                )
                go_status = go_wait.get("StatusCode", 1) if isinstance(go_wait, dict) else 1
                go_probe = go_container.logs().decode("utf-8", errors="strict")
                if go_status != 0:
                    raise SystemTestError("Go build-info probe failed")
            finally:
                try:
                    go_container.remove(force=True, v=True)
                except Exception as error:
                    raise SystemTestError(f"Go build-info probe cleanup failed: {error}") from error
        expected_go = image_labels.get(LABEL_RELEASE_GO, "")
        first_line = go_probe.splitlines()[0] if go_probe.splitlines() else ""
        go_match = re.fullmatch(r"/probe/helper: go([0-9]+\.[0-9]+(?:\.[0-9]+)?)", first_line)
        observed_go = go_match.group(1) if go_match else ""
        if not observed_go or observed_go != expected_go:
            raise SystemTestError(
                f"candidate self-test go version mismatch: observed {first_line!r}, expected {expected_go!r}"
            )
        release_versions = {
            "postgresql": str(observed_pg), "python": str(observed_py),
            "go": str(observed_go) if observed_go else str(expected_go),
            "psycopg": str(observed_psycopg), "libpq": str(observed_libpq),
            "go_helper": str(observed_go_helper), "go_helper_protocol": str(observed_go_helper_protocol),
        }
    finally:
        try:
            container.remove(force=True, v=True)
        except Exception as error:
            raise SystemTestError(f"candidate self-test container cleanup failed: {error}") from error

    repo_digests = getattr(image, "attrs", {}).get("RepoDigests", [])
    image_digest = repo_digests[0] if repo_digests else image_id
    return CandidateImageMetadata(
        image_id=image_id, image_tag=config.candidate_tag, image_digest=image_digest,
        labels=dict(image_labels), release_versions=release_versions, created_image_ids=created_image_ids,
    )
