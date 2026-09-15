"""Candidate release image build and verification for the main system gate."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from dataclasses import dataclass
from repomap_kg.runtime.commands import render_server_dockerfile
from repomap_kg.runtime.release import GO_RELEASE_IMAGE
from tools.system.config import (
    IMAGE_CLASS_SYSTEM_CANDIDATE,
    LABEL_CANDIDATE_TREE,
    LABEL_IMAGE_CLASS,
    LABEL_MANAGED,
    LABEL_RELEASE_GO,
    LABEL_RELEASE_LIBPQ,
    LABEL_RELEASE_POSTGRES,
    LABEL_RELEASE_PSYCOPG,
    LABEL_RELEASE_PYTHON,
    LABEL_RUN_ID,
    SystemTestConfig,
    SystemTestError,
)


@dataclass(frozen=True)
class CandidateImageMetadata:
    image_id: str
    image_tag: str
    image_digest: str
    labels: dict[str, str]
    release_versions: dict[str, str]
    created_image_ids: tuple[str, ...] = ()


def get_current_tree_sha(repo_root: Path) -> str:
    """Materialize the exact non-ignored worktree tree without touching the real index."""
    object_result = subprocess.run(
        ("git", "rev-parse", "--git-path", "objects"),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if object_result.returncode != 0 or not object_result.stdout.strip():
        raise SystemTestError(
            "unable to locate repository object database: "
            f"{object_result.stderr.strip()}"
        )
    repository_objects = Path(object_result.stdout.strip())
    if not repository_objects.is_absolute():
        repository_objects = (repo_root / repository_objects).resolve()

    with tempfile.TemporaryDirectory(prefix="repomap-system-index-") as tmpdir:
        temporary_objects = Path(tmpdir) / "objects"
        temporary_objects.mkdir()
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(Path(tmpdir) / "index")
        env["GIT_OBJECT_DIRECTORY"] = str(temporary_objects)
        existing_alternates = env.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(
            value
            for value in (str(repository_objects), existing_alternates)
            if value
        )
        for command in (
            ("git", "read-tree", "HEAD"),
            ("git", "add", "-A", "--", "."),
            ("git", "write-tree"),
        ):
            result = subprocess.run(
                command,
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise SystemTestError(
                    f"unable to determine candidate tree SHA: {result.stderr.strip()}"
                )
        return result.stdout.strip()


def build_and_verify_candidate_image(
    repo_root: Path,
    config: SystemTestConfig,
    *,
    boundary: Any | None,
    client: Any,
    deadline: Any | None = None,
) -> CandidateImageMetadata:
    """Build the assembled candidate image and verify packaging without source mounts."""
    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget("candidate image build")

    current_tree = get_current_tree_sha(repo_root)
    if current_tree != config.candidate_tree_sha:
        raise SystemTestError(
            f"candidate tree SHA mismatch: expected {config.candidate_tree_sha}, got {current_tree}"
        )

    labels = {
        LABEL_IMAGE_CLASS: IMAGE_CLASS_SYSTEM_CANDIDATE,
        LABEL_MANAGED: "true",
        LABEL_CANDIDATE_TREE: config.candidate_tree_sha,
        LABEL_RUN_ID: config.run_id,
    }

    dockerfile_content = render_server_dockerfile()

    import platform

    machine = platform.machine().lower()
    target_arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    buildargs = {
        "TARGETOS": "linux",
        "TARGETARCH": target_arch,
    }

    build_request = f"candidate-image-build:{config.candidate_tag}"
    build_timeout = (
        deadline.clamp_timeout(900.0)
        if deadline is not None and hasattr(deadline, "clamp_timeout")
        else 900.0
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".Dockerfile", delete=False
    ) as dockerfile:
        dockerfile.write(dockerfile_content)
        dockerfile_path = Path(dockerfile.name)
    build_command = [
        "docker", "build", "--pull=false", "--rm", "--force-rm",
        "--file", str(dockerfile_path), "--tag", config.candidate_tag,
    ]
    for name, value in sorted(labels.items()):
        build_command.extend(("--label", f"{name}={value}"))
    for name, value in sorted(buildargs.items()):
        build_command.extend(("--build-arg", f"{name}={value}"))
    build_command.append(str(repo_root))
    build_context = None
    operation_ticket = None
    try:
        if boundary is not None and hasattr(
            boundary, "managed_system_candidate_build"
        ):
            build_context = boundary.managed_system_candidate_build(
                request=build_request
            )
            operation_ticket = build_context.__enter__()
        built = subprocess.run(
            build_command,
            capture_output=True,
            text=True,
            timeout=build_timeout,
            check=False,
        )
        if built.returncode != 0:
            raise SystemTestError(
                "candidate image build failed: "
                + (built.stderr.strip() or built.stdout.strip())[-2000:]
            )
        image = client.images.get(config.candidate_tag)
        if (
            boundary is not None
            and operation_ticket is not None
            and hasattr(boundary, "complete_operation")
        ):
            boundary.complete_operation(operation_ticket, image_ids=(image.id,))
    finally:
        if build_context is not None:
            build_context.__exit__(*sys.exc_info())
        dockerfile_path.unlink(missing_ok=True)

    # Intermediate images are never inferred from a global before/after delta.
    # The exact candidate ID/tag and boundary-attributed resources are the only
    # cleanup authority created by this operation.
    created_image_ids: tuple[str, ...] = ()

    image_id = image.id
    if not image_id.startswith("sha256:"):
        raise SystemTestError(f"invalid candidate image ID format: {image_id}")

    # Verify test and release labels
    image_labels = image.labels or {}
    for label_name, expected_val in (
        (LABEL_IMAGE_CLASS, IMAGE_CLASS_SYSTEM_CANDIDATE),
        (LABEL_CANDIDATE_TREE, config.candidate_tree_sha),
        (LABEL_MANAGED, "true"),
        (LABEL_RUN_ID, config.run_id),
    ):
        if image_labels.get(label_name) != expected_val:
            raise SystemTestError(f"candidate image missing or invalid label {label_name}: {image_labels.get(label_name)!r}")

    for rel_label in (
        LABEL_RELEASE_POSTGRES,
        LABEL_RELEASE_PYTHON,
        LABEL_RELEASE_GO,
        LABEL_RELEASE_PSYCOPG,
        LABEL_RELEASE_LIBPQ,
    ):
        if rel_label not in image_labels:
            raise SystemTestError(f"candidate image missing required release label {rel_label}")

    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget("candidate image self-test")

    # Self-test container: verify python package import, migrations, packaged Go helper and runtime versions
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
        "proto_res = subprocess.run([helper_cmd[0], '--protocol-version'], capture_output=True, text=True, check=True); "
        "helper_proto = proto_res.stdout.strip(); "
        "psql_res = subprocess.run(['psql', '--version'], capture_output=True, text=True, check=True); "
        "psql_out = psql_res.stdout.strip(); "
        "print(json.dumps({"
        "'python': platform.python_version(), "
        "'psycopg': psycopg.__version__, "
        "'libpq': str(pq.version()), "
        "'postgresql': psql_out, "
        "'go_helper': helper_cmd[0], "
        "'go_helper_protocol': helper_proto, "
        "}))"
    )

    container = client.containers.create(
        image_id,
        entrypoint=["python", "-c", self_test_script],
        command=[],
        network_mode="none",
        labels={LABEL_RUN_ID: config.run_id, LABEL_MANAGED: "true"},
    )
    release_versions: dict[str, str] = {}
    try:
        container.start()
        self_test_timeout = int(deadline.clamp_timeout(30.0)) if deadline is not None and hasattr(deadline, "clamp_timeout") else 30
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

        # Validate probed runtime metadata strictly against release labels
        observed_py = parsed.get("python")
        expected_py = image_labels.get(LABEL_RELEASE_PYTHON, "")
        if not observed_py or not expected_py or observed_py != expected_py:
            raise SystemTestError(
                f"candidate self-test python version mismatch: observed {observed_py!r}, expected {expected_py!r}"
            )

        observed_psycopg = parsed.get("psycopg")
        expected_psycopg = image_labels.get(LABEL_RELEASE_PSYCOPG, "")
        if not observed_psycopg or not expected_psycopg or observed_psycopg != expected_psycopg:
            raise SystemTestError(
                f"candidate self-test psycopg version mismatch: observed {observed_psycopg!r}, expected {expected_psycopg!r}"
            )

        observed_libpq = parsed.get("libpq")
        expected_libpq = image_labels.get(LABEL_RELEASE_LIBPQ, "")
        if not observed_libpq or not expected_libpq or str(observed_libpq) != str(expected_libpq):
            raise SystemTestError(
                f"candidate self-test libpq version mismatch: observed {observed_libpq!r}, expected {expected_libpq!r}"
            )

        observed_pg_raw = parsed.get("postgresql", "")
        expected_pg = image_labels.get(LABEL_RELEASE_POSTGRES, "")
        pg_match = re.fullmatch(
            r"psql \(PostgreSQL\) ([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?: .*)?",
            str(observed_pg_raw),
        )
        observed_pg = pg_match.group(1) if pg_match else ""
        if not observed_pg or observed_pg != expected_pg:
            raise SystemTestError(
                f"candidate self-test postgresql version mismatch: observed {observed_pg_raw!r}, expected {expected_pg!r}"
            )

        observed_go_helper = parsed.get("go_helper")
        if not observed_go_helper or not isinstance(observed_go_helper, str):
            raise SystemTestError("candidate self-test go helper is missing or invalid")

        observed_go_helper_protocol = parsed.get("go_helper_protocol")
        if not observed_go_helper_protocol or not str(observed_go_helper_protocol).isdigit():
            raise SystemTestError(f"candidate self-test go helper protocol version is invalid: {observed_go_helper_protocol!r}")

        with tempfile.TemporaryDirectory(prefix="repomap-go-helper-") as helper_dir:
            helper_copy = Path(helper_dir) / "helper"
            copied = subprocess.run(
                ["docker", "cp", f"{container.id}:{observed_go_helper}", str(helper_copy)],
                capture_output=True,
                text=True,
                timeout=(deadline.clamp_timeout(30.0) if deadline is not None else 30.0),
                check=False,
            )
            if copied.returncode != 0:
                raise SystemTestError("candidate Go helper extraction failed")
            go_container = client.containers.create(
                GO_RELEASE_IMAGE,
                command=["go", "version", "-m", "/probe/helper"],
                entrypoint=[],
                network_mode="none",
                volumes={helper_dir: {"bind": "/probe", "mode": "ro"}},
                labels={LABEL_RUN_ID: config.run_id, LABEL_MANAGED: "true"},
            )
            try:
                go_container.start()
                go_wait = go_container.wait(
                    timeout=(
                        int(deadline.clamp_timeout(30.0))
                        if deadline is not None
                        else 30
                    )
                )
                go_status = (
                    go_wait.get("StatusCode", 1)
                    if isinstance(go_wait, dict)
                    else 1
                )
                go_probe = go_container.logs().decode("utf-8", errors="strict")
                if go_status != 0:
                    raise SystemTestError("Go build-info probe failed")
            finally:
                try:
                    go_container.remove(force=True, v=True)
                except Exception as error:
                    raise SystemTestError(
                        f"Go build-info probe cleanup failed: {error}"
                    ) from error
        expected_go = image_labels.get(LABEL_RELEASE_GO, "")
        first_line = go_probe.splitlines()[0] if go_probe.splitlines() else ""
        go_match = re.fullmatch(r"/probe/helper: go([0-9]+\.[0-9]+(?:\.[0-9]+)?)", first_line)
        observed_go = go_match.group(1) if go_match else ""
        if not observed_go or observed_go != expected_go:
            raise SystemTestError(
                f"candidate self-test go version mismatch: observed {first_line!r}, expected {expected_go!r}"
            )

        release_versions = {
            "postgresql": str(observed_pg),
            "python": str(observed_py),
            "go": str(observed_go) if observed_go else str(expected_go),
            "psycopg": str(observed_psycopg),
            "libpq": str(observed_libpq),
            "go_helper": str(observed_go_helper),
            "go_helper_protocol": str(observed_go_helper_protocol),
        }
    finally:
        try:
            container.remove(force=True, v=True)
        except Exception as error:
            raise SystemTestError(
                f"candidate self-test container cleanup failed: {error}"
            ) from error

    repo_digests = getattr(image, "attrs", {}).get("RepoDigests", [])
    image_digest = repo_digests[0] if repo_digests else image_id

    return CandidateImageMetadata(
        image_id=image_id,
        image_tag=config.candidate_tag,
        image_digest=image_digest,
        labels=dict(image_labels),
        release_versions=release_versions,
        created_image_ids=created_image_ids,
    )
