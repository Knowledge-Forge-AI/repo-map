"""Build context, manifest persistence, and validation for image materialization."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from repomap_test_support.resource_ledger import ResourceKind, ResourceLedger, RunIdentity
from repomap_test_support.resource_ledger_io import write_private_json
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_test_image_base import (
    TestImageError,
    repository_scratch_directory,
)
from repomap_test_support.resource_test_image_cleanup import (
    MaterializationCleanupError,
    container_state,
    docker_failure_evidence,
    is_terminal_container_state,
)
from repomap_test_support.resource_test_image_commands import (
    _MATERIALIZATION_OWNER_PREFIX,
    _MaterializationValidationError,
    exact_image_id,
    validate_network_authority,
)
from repomap_test_support.resource_test_image_materialization_claim import (
    MATERIALIZATION_MANIFEST_SCHEMA as _MATERIALIZATION_MANIFEST_SCHEMA,
    MATERIALIZATION_ROLE as _MATERIALIZATION_ROLE,
    read_materialization_claim as _read_raw_materialization_claim,
)
from repomap_test_support.resource_test_image_types import (
    MaterializationClaim,
    materialization_claim,
)

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container


def materialization_manifest_path(repo_root: Path) -> Path:
    scratch = repository_scratch_directory(repo_root)
    return scratch / f"repomap-runtime-materialization-{os.getuid()}.json"


def _resolve_manifest_path(configured: Path | str | None, repo_root: Path | None) -> Path:
    if configured:
        return Path(configured)
    if repo_root is None:
        raise TestImageError("materialization manifest requires a project root")
    return materialization_manifest_path(repo_root)


def _read_materialization_claim(path: Path) -> MaterializationClaim:
    return materialization_claim(_read_raw_materialization_claim(path))


def materialization_container_name(identity: RunIdentity) -> str:
    seed = "\0".join(
        (
            identity.project,
            identity.phase,
            identity.run_id,
            _MATERIALIZATION_ROLE,
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"repomap-test-materialization-{digest}"


def materialization_container_owner(name: str) -> str:
    return f"{_MATERIALIZATION_OWNER_PREFIX}{_MATERIALIZATION_ROLE}:{name}"


def build_materialization_claim(
    *,
    identity: RunIdentity,
    ledger: ResourceLedger,
    name: str,
    image_id: str,
    container_id: str | None,
    network_mode: str,
    network_id: str | None,
) -> MaterializationClaim:
    return {
        "schema": _MATERIALIZATION_MANIFEST_SCHEMA,
        "project": identity.project,
        "phase": identity.phase,
        "run_id": identity.run_id,
        "role": _MATERIALIZATION_ROLE,
        "name": name,
        "base_image_id": exact_image_id(image_id),
        "container_id": container_id,
        "network_mode": network_mode,
        "network_id": network_id,
        "ledger_path": str(Path(ledger.path).resolve()),
    }


def write_materialization_claim(
    manifest_path: Path, claim: MaterializationClaim
) -> None:
    if (
        manifest_path.exists()
        and manifest_path.stat(follow_symlinks=False).st_uid != os.getuid()
    ):
        raise TestImageError("materialization manifest owner differs")
    write_private_json(manifest_path, dict(claim))


def validate_cleanup_target(
    container: Container, claim: Mapping[str, object]
) -> None:
    expected_id = claim.get("container_id")
    if expected_id is None or str(container.id) != expected_id:
        raise _MaterializationValidationError(
            "materialization container ID differs", "container_id"
        )


def validate_claim_identity(
    claim: Mapping[str, object],
    identity: RunIdentity,
    ledger: ResourceLedger,
    container_id: str,
    failure_evidence: Mapping[str, object],
) -> None:
    expected_identity = {
        "project": identity.project,
        "phase": identity.phase,
        "run_id": identity.run_id,
        "ledger_path": str(Path(ledger.path).resolve()),
    }
    for field, expected in expected_identity.items():
        if claim[field] == expected:
            continue
        predicate = f"manifest_{field}"
        raise MaterializationCleanupError(
            f"identity_or_state_validation_refused:{predicate}",
            {
                **failure_evidence,
                "validation_category": (
                    f"materialization manifest {field} differs from current ledger"
                ),
                "validation_predicate": predicate,
            },
        )


def validate_execution_conformance(
    client: DockerClient, container: Container, claim: MaterializationClaim
) -> None:
    container.reload()
    attrs = container.attrs
    expected_id = claim.get("container_id")
    if expected_id is not None and str(container.id) != expected_id:
        raise _MaterializationValidationError(
            "materialization container ID differs", "container_id"
        )
    if str(attrs.get("Name") or "") != f"/{claim['name']}":
        raise _MaterializationValidationError(
            "materialization container name differs", "container_name"
        )
    if str(attrs.get("Image") or "") != claim["base_image_id"]:
        raise _MaterializationValidationError(
            "materialization container image differs", "base_image"
        )
    if dict((attrs.get("Config") or {}).get("Labels") or {}):
        raise _MaterializationValidationError(
            "materialization container must be label-free", "labels"
        )
    if list(attrs.get("Mounts") or ()):
        raise _MaterializationValidationError(
            "materialization container has mounts", "mounts"
        )
    host_config = attrs.get("HostConfig") or {}
    validate_network_authority(client, attrs, host_config, claim)
    restart = host_config.get("RestartPolicy") or {}
    if str(restart.get("Name") or "no") != "no" or int(
        restart.get("MaximumRetryCount") or 0
    ) != 0:
        raise _MaterializationValidationError(
            "materialization container restart policy differs", "restart_policy"
        )
    if bool(host_config.get("AutoRemove", False)):
        raise _MaterializationValidationError(
            "materialization container auto-remove policy differs", "auto_remove"
        )


def observe_execution_conformance(
    client: DockerClient, container: Container, claim: MaterializationClaim
) -> dict[str, str | None]:
    try:
        validate_execution_conformance(client, container, claim)
    except _MaterializationValidationError as error:
        return {"status": "drifted", "predicate": error.validation_predicate}
    except Exception:
        return {"status": "unavailable", "predicate": "container_readback"}
    return {"status": "passed", "predicate": None}


def container_failure_evidence(
    client: DockerClient, container_id: str
) -> dict[str, object]:
    try:
        container = client.containers.get(container_id)
        container.reload()
    except Exception as error:
        if error.__class__.__name__ == "NotFound":
            return {
                "exact_container_exists_afterward": False,
                "post_failure_state": None,
            }
        return {
            "exact_container_exists_afterward": None,
            "post_failure_state": None,
        }
    return {
        "exact_container_exists_afterward": True,
        "post_failure_state": container_state(container.attrs),
    }


def remove_claimed_container(
    api: DockerSdkApi,
    client: DockerClient,
    container: Container,
    claim: MaterializationClaim,
) -> dict[str, object]:
    validate_cleanup_target(container, claim)
    conformance = observe_execution_conformance(client, container, claim)
    try:
        pre_remove_state = container_state(container.attrs)
    except Exception:
        pre_remove_state = None
    stop_attempted = pre_remove_state is None or not is_terminal_container_state(
        pre_remove_state
    )
    stop_result = "not_needed"
    stop_failure: dict[str, object] | None = None
    if stop_attempted:
        try:
            container.stop(timeout=10)
        except Exception as error:
            stop_result = "error"
            stop_failure = docker_failure_evidence(error)
        else:
            stop_result = "stopped"
    try:
        container.reload()
        terminal_state = container_state(container.attrs)
    except Exception:
        terminal_state = None
    terminal_confirmed = terminal_state is not None and is_terminal_container_state(
        terminal_state
    )
    if stop_attempted and stop_result == "stopped" and not terminal_confirmed:
        stop_result = "nonterminal"
    validate_cleanup_target(container, claim)
    container_id = str(claim["container_id"])
    lifecycle_evidence: dict[str, object] = {
        "pre_remove_state": pre_remove_state,
        "terminal_state": terminal_state,
        "terminal_state_confirmed": terminal_confirmed,
        "stop_attempted": stop_attempted,
        "stop_result": stop_result,
        "execution_conformance": conformance,
    }
    if stop_failure is not None:
        lifecycle_evidence["stop_failure"] = stop_failure
    try:
        api.remove(ResourceKind.DOCKER_CONTAINER, container_id)
    except Exception as error:
        failure = {
            **lifecycle_evidence,
            "force": True,
            **docker_failure_evidence(error),
            **container_failure_evidence(client, container_id),
        }
        if failure["exact_container_exists_afterward"] is False:
            return {**failure, "remove_result": "rejected_but_absent"}
        raise MaterializationCleanupError("remove_api_rejected", failure) from error
    try:
        remaining = api.inspect(ResourceKind.DOCKER_CONTAINER, container_id)
    except Exception as error:
        raise MaterializationCleanupError(
            "remove_absence_unproved",
            {
                **lifecycle_evidence,
                "force": True,
                **docker_failure_evidence(error),
                "exact_container_exists_afterward": None,
                "post_failure_state": None,
            },
        ) from error
    if remaining is not None:
        raise MaterializationCleanupError(
            "remove_returned_container_present",
            {
                **lifecycle_evidence,
                "force": True,
                **container_failure_evidence(client, container_id),
            },
        )
    return {
        **lifecycle_evidence,
        "force": True,
        "remove_result": "exact_absence_proved",
    }


__all__ = [
    "_MaterializationValidationError",
    "_read_materialization_claim",
    "_resolve_manifest_path",
    "build_materialization_claim",
    "container_failure_evidence",
    "materialization_container_name",
    "materialization_container_owner",
    "materialization_manifest_path",
    "observe_execution_conformance",
    "remove_claimed_container",
    "validate_claim_identity",
    "validate_cleanup_target",
    "validate_execution_conformance",
    "write_materialization_claim",
]
