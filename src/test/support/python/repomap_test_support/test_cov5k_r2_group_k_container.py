"""Safe Docker container lifecycle mediation for Group K rehearsal executors."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import subprocess
from typing import Any
import uuid

import docker
from repomap_test_support.postgres_container import TEST_POSTGRES_IMAGE
from repomap_test_support.resource_docker import DockerObject, ownership_labels
from repomap_test_support.resource_docker_current import (
    CurrentRunDockerCleanupError,
    CurrentRunDockerContainers,
)
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run


def _group_k_container_create_command(
    *,
    container_name: str,
    run_detached: bool,
    password: str,
    ownership_labels: dict[str, str],
) -> list[str]:
    """Create one local-only Postgres container without Docker volumes."""
    command = ["docker", "run" if run_detached else "create"]
    if run_detached:
        command.append("-d")
    command.extend(["--pull=never", "--name", container_name])
    for key, value in sorted(ownership_labels.items()):
        command.extend(["--label", f"{key}={value}"])
    command.extend([
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "--tmpfs",
        "/var/lib/postgresql/data",
        TEST_POSTGRES_IMAGE,
    ])
    return command


def _run_checked_setup(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=False,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        err = completed.stderr or ""
        category = (
            "image_unavailable"
            if "pull access denied" in err or "repository does not exist" in err
            else "setup_failed"
        )
        raise RuntimeError(
            f"Group K disposable setup failed ({category}, exit {completed.returncode})"
        )
    return completed


def _discover_container(
    container_owner: CurrentRunDockerContainers,
    *,
    name: str,
    container_id: str | None,
) -> DockerObject | None:
    """Read-only discovery of a container by ID or exact name without mutating state."""
    if container_id:
        discovered = container_owner.api.inspect(
            ResourceKind.DOCKER_CONTAINER,
            container_id,
        )
        if discovered is not None:
            return discovered
    return container_owner.api.inspect(ResourceKind.DOCKER_CONTAINER, name)


def _record_unresolved_cleanup(
    case_root: Path,
    *,
    name: str,
    observed_id: str | None,
    reason: str,
) -> None:
    """Record an unowned or baseline-colliding container that cannot be removed."""
    record = {
        "container_name": name,
        "observed_id": observed_id,
        "reason": reason,
    }
    content = json.dumps(record)
    case_root.joinpath("unresolved_cleanup.json").write_text(
        content,
        encoding="utf-8",
    )
    try:
        case_root.parent.joinpath(f"{case_root.name}_unresolved_cleanup.json").write_text(
            content,
            encoding="utf-8",
        )
    except Exception:
        pass


def _handle_partial_setup_failure(
    *,
    container_owner: CurrentRunDockerContainers,
    container_name: str,
    container_id: str | None,
    expected_labels: dict[str, str],
    role: str,
    case_root: Path,
    primary_error: Exception,
) -> None:
    """Safely inspect, validate, and clean up any partially created owned container."""
    try:
        discovered = _discover_container(
            container_owner,
            name=container_name,
            container_id=container_id,
        )
    except Exception as disc_err:
        _record_unresolved_cleanup(
            case_root,
            name=container_name,
            observed_id=container_id,
            reason=f"discovery_uncertainty: {disc_err}",
        )
        primary_error.__context__ = disc_err
        return

    if discovered is None:
        return

    discovered_id = str(getattr(discovered, "identity", None) or getattr(discovered, "id", "") or container_id or "")
    if container_owner.baseline.contains(ResourceKind.DOCKER_CONTAINER, discovered_id):
        _record_unresolved_cleanup(
            case_root,
            name=container_name,
            observed_id=discovered_id,
            reason="pre_existing_baseline_collision",
        )
        primary_error.__context__ = CurrentRunDockerCleanupError(
            "setup collided with pre-existing baseline container; container preserved"
        )
        return

    discovered_labels = dict(getattr(discovered, "labels", None) or {})
    if any(discovered_labels.get(k) != v for k, v in expected_labels.items()):
        _record_unresolved_cleanup(
            case_root,
            name=container_name,
            observed_id=discovered_id,
            reason="foreign_or_mismatched_ownership_labels",
        )
        primary_error.__context__ = CurrentRunDockerCleanupError(
            "setup collided with foreign or unowned container; container preserved"
        )
        return

    # Validated ownership: belongs to this attempt and run. Perform bounded cleanup.
    try:
        container_owner.register_observed(discovered_id, role=role)
        container_owner.cleanup(discovered_id)
    except Exception as cleanup_err:
        _record_unresolved_cleanup(
            case_root,
            name=container_name,
            observed_id=discovered_id,
            reason=f"cleanup_failed: {cleanup_err}",
        )
        primary_error.__context__ = cleanup_err


def execute_group_k_docker(
    *,
    entry: Any,
    case_root: Path,
    container_name: str,
    shape: tuple[str, ...],
    command: list[str],
    environment: dict[str, str],
    runner: Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess[str]] | None = None,
) -> tuple[tuple[str, ...], subprocess.CompletedProcess[str]]:
    """Execute one Docker-backed Group K axis with verified ownership and bounded cleanup."""
    resource_run = active_resource_run()
    if resource_run is None:
        raise RuntimeError("Group K Docker route requires a managed run")

    docker_client = docker.from_env()
    container_owner = None
    container_id = None
    registered = False
    role = f"group-k-{entry.condition_id.lower()}"
    run_detached = entry.condition_id in {"K09", "K12"}
    primary_failure: Exception | None = None

    try:
        container_owner = CurrentRunDockerContainers(resource_run, docker_client)
        expected_labels = ownership_labels(
            resource_run.ledger.identity,
            role=role,
            retained=False,
        )
        setup_cmd = _group_k_container_create_command(
            container_name=container_name,
            run_detached=run_detached,
            password=uuid.uuid4().hex,
            ownership_labels=expected_labels,
        )

        setup_result = None
        setup_error: Exception | None = None
        try:
            setup_result = _run_checked_setup(setup_cmd, cwd=case_root)
        except Exception as err:
            setup_error = err

        if setup_error is None and setup_result is not None:
            raw_id = setup_result.stdout.strip()
            if not raw_id or any(c in raw_id for c in " \t\r\n") or len(raw_id) < 8:
                setup_error = RuntimeError("malformed container ID in setup output")
            else:
                container_id = raw_id

        if setup_error is not None:
            primary_failure = setup_error
            _handle_partial_setup_failure(
                container_owner=container_owner,
                container_name=container_name,
                container_id=container_id,
                expected_labels=expected_labels,
                role=role,
                case_root=case_root,
                primary_error=setup_error,
            )
            raise setup_error

        assert container_id is not None
        container_owner.register_observed(container_id, role=role)
        registered = True

        command[-1] = container_id
        observed_argv = tuple(
            shape[-1] if item == container_id else item
            for item in (Path(command[0]).name, *command[1:])
        )
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            if runner is not None:
                completed = runner(command, case_root, environment)
            else:
                completed = subprocess.run(
                    command,
                    cwd=case_root,
                    env=environment,
                    shell=False,
                    timeout=10,
                    check=False,
                    capture_output=True,
                    text=True,
                )
        except Exception as err:
            primary_failure = err
            raise

        assert completed is not None
        return observed_argv, completed

    finally:
        cleanup_error: Exception | None = None
        if container_owner is not None and container_id is not None and registered:
            try:
                if (
                    entry.condition_id == "K10"
                    and container_owner.api.inspect(
                        ResourceKind.DOCKER_CONTAINER,
                        container_id,
                    ) is None
                ):
                    container_owner.observe_removed(container_id)
                else:
                    container_owner.cleanup(container_id)
                container_owner.verify_baseline()
            except Exception as err:
                cleanup_error = err

        if docker_client is not None:
            try:
                docker_client.close()
            except Exception as err:
                if cleanup_error is None:
                    cleanup_error = err
                else:
                    cleanup_error.__context__ = err

        if cleanup_error is not None:
            if primary_failure is not None and primary_failure is not cleanup_error:
                cleanup_error.__context__ = None
                primary_failure.__context__ = cleanup_error
            else:
                raise cleanup_error
