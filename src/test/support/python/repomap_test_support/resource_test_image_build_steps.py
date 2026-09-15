"""Single-image container lifecycle and interrupted recovery steps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_test_image_base import TestImageError
from repomap_test_support.resource_test_image_cleanup import (
    MaterializationCleanupError,
)
from repomap_test_support.resource_test_image_commands import (
    MATERIALIZATION_NETWORK_MODE,
    exact_image_id,
    require_builtin_bridge,
    validate_network_authority,
)
from repomap_test_support.resource_test_image_build_context import (
    _MaterializationValidationError,
    _read_materialization_claim,
    _resolve_manifest_path,
    build_materialization_claim,
    container_failure_evidence,
    materialization_container_name,
    materialization_container_owner,
    observe_execution_conformance,
    remove_claimed_container,
    validate_claim_identity,
    validate_cleanup_target,
    validate_execution_conformance,
    write_materialization_claim,
)
from repomap_test_support.resource_test_image_types import MaterializationClaim

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container
    from repomap_test_support.resource_run import TestResourceRun


class MaterializationContainerOwner:
    """Persist exact label-free container authority across process loss."""

    _validate_cleanup_target = staticmethod(validate_cleanup_target)
    _owner = staticmethod(materialization_container_owner)
    _exact_id = staticmethod(exact_image_id)

    def __init__(
        self,
        resource_run: TestResourceRun,
        client: DockerClient,
        *,
        repo_root: Path | None = None,
        network_mode: str = MATERIALIZATION_NETWORK_MODE,
    ) -> None:
        self.client = client
        self.api = DockerSdkApi(client)
        self.ledger = resource_run.ledger
        self.identity = self.ledger.identity
        configured = getattr(resource_run, "materialization_manifest_path", None)
        self.manifest_path = _resolve_manifest_path(configured, repo_root)
        if network_mode not in {"none", "bridge"}:
            raise TestImageError("materialization network mode is not repository-owned")
        self.network_mode = network_mode

    def create(self, image_id: str, command: Sequence[str]) -> str:
        network_id = (
            self._require_builtin_bridge() if self.network_mode == "bridge" else None
        )
        recover_interrupted_runtime_materialization(
            self.client, manifest_path=self.manifest_path
        )
        name = self._name()
        try:
            self.client.containers.get(name)
        except Exception as error:
            if error.__class__.__name__ != "NotFound":
                raise
        else:
            raise TestImageError("materialization container name is already present")
        claim = self._claim(
            name=name, image_id=image_id, container_id=None, network_id=network_id
        )
        self._write_claim(claim)
        try:
            container = self.client.containers.create(
                image_id,
                list(command),
                name=name,
                labels={},
                entrypoint=["python"],
                network_mode=self.network_mode,
            )
            container_id = str(container.id)
            if not container_id:
                raise TestImageError("Docker create returned no container ID")
            claim = self._claim(
                name=name,
                image_id=image_id,
                container_id=container_id,
                network_id=network_id,
            )
            self._validate_execution_conformance(container, claim)
            self.ledger.register(
                ResourceKind.DOCKER_CONTAINER,
                container_id,
                creation_owner=self._owner(name),
                created_before_run=False,
                creation_observed=True,
                cleanup_required=True,
            )
            self._write_claim(claim)
            return container_id
        except Exception:
            if self.manifest_path.exists():
                try:
                    self.client.containers.get(name)
                except Exception as lookup_error:
                    if lookup_error.__class__.__name__ == "NotFound":
                        self.manifest_path.unlink()
            raise

    def cleanup(self, container_id: str) -> Mapping[str, object]:
        claim: MaterializationClaim = _read_materialization_claim(self.manifest_path)
        self._validate_claim_identity(claim, container_id)
        if claim["container_id"] != container_id:
            raise MaterializationCleanupError(
                "identity_or_state_validation_refused:manifest_container_id",
                {
                    **self._failure_evidence(container_id),
                    "validation_category": "materialization manifest container ID differs",
                    "validation_predicate": "manifest_container_id",
                },
            )
        try:
            record = self.ledger.get(ResourceKind.DOCKER_CONTAINER, container_id)
        except Exception as error:
            raise MaterializationCleanupError(
                "identity_or_state_validation_refused:ledger_ownership",
                {
                    **self._failure_evidence(container_id),
                    "validation_category": "materialization ledger ownership differs",
                    "validation_predicate": "ledger_ownership",
                },
            ) from error
        if (
            record.creation_owner != self._owner(str(claim["name"]))
            or not record.creation_observed
            or not record.cleanup_required
        ):
            raise MaterializationCleanupError(
                "identity_or_state_validation_refused:ledger_ownership",
                {
                    **self._failure_evidence(container_id),
                    "validation_category": "materialization ledger ownership differs",
                    "validation_predicate": "ledger_ownership",
                },
            )
        self.ledger.mark_cleanup_attempted(ResourceKind.DOCKER_CONTAINER, container_id)
        try:
            container = self.client.containers.get(container_id)
            self._validate_cleanup_target(container, claim)
            evidence = self._remove_claimed_container(container, claim)
        except MaterializationCleanupError as error:
            self._mark_failed(container_id, error.cleanup_evidence)
            raise
        except Exception as error:
            evidence = self._failure_evidence(container_id)
            self._mark_failed(container_id, evidence)
            if isinstance(error, _MaterializationValidationError):
                evidence["validation_category"] = str(error)
                evidence["validation_predicate"] = error.validation_predicate
            else:
                evidence["validation_category"] = (
                    str(error) if isinstance(error, TestImageError)
                    else "materialization container readback failed"
                )
                evidence["validation_predicate"] = "container_readback"
            predicate = str(evidence["validation_predicate"])
            raise MaterializationCleanupError(
                f"identity_or_state_validation_refused:{predicate}", evidence
            ) from error
        self.ledger.mark_cleanup_result(
            ResourceKind.DOCKER_CONTAINER, container_id, CleanupResult.REMOVED
        )
        self.ledger.mark_final_presence(
            ResourceKind.DOCKER_CONTAINER, container_id, FinalPresence.ABSENT
        )
        self.manifest_path.unlink()
        return evidence

    def _validate_claim_identity(
        self, claim: Mapping[str, object], container_id: str
    ) -> None:
        validate_claim_identity(
            claim,
            self.identity,
            self.ledger,
            container_id,
            self._failure_evidence(container_id),
        )

    def _remove_claimed_container(
        self, container: Container, claim: MaterializationClaim
    ) -> dict[str, object]:
        return remove_claimed_container(self.api, self.client, container, claim)

    def _mark_failed(self, container_id: str, evidence: Mapping[str, object]) -> None:
        self.ledger.mark_cleanup_result(
            ResourceKind.DOCKER_CONTAINER, container_id, CleanupResult.FAILED
        )
        self.ledger.mark_final_presence(
            ResourceKind.DOCKER_CONTAINER,
            container_id,
            FinalPresence.ABSENT
            if evidence.get("exact_container_exists_afterward") is False
            else FinalPresence.PRESENT,
        )

    def _failure_evidence(self, container_id: str) -> dict[str, object]:
        return container_failure_evidence(self.client, container_id)

    def _claim(
        self,
        *,
        name: str,
        image_id: str,
        container_id: str | None,
        network_id: str | None,
    ) -> MaterializationClaim:
        return build_materialization_claim(
            identity=self.identity,
            ledger=self.ledger,
            name=name,
            image_id=image_id,
            container_id=container_id,
            network_mode=self.network_mode,
            network_id=network_id,
        )

    def _write_claim(self, claim: MaterializationClaim) -> None:
        write_materialization_claim(self.manifest_path, claim)

    def _name(self) -> str:
        return materialization_container_name(self.identity)

    def _observe_execution_conformance(
        self, container: Container, claim: MaterializationClaim
    ) -> dict[str, str | None]:
        return observe_execution_conformance(self.client, container, claim)

    def _validate_execution_conformance(
        self, container: Container, claim: MaterializationClaim
    ) -> None:
        validate_execution_conformance(self.client, container, claim)

    def _validate_network_authority(
        self,
        attrs: Mapping[str, object],
        host_config: Mapping[str, object],
        claim: MaterializationClaim,
    ) -> None:
        validate_network_authority(self.client, attrs, host_config, claim)

    def _require_builtin_bridge(self) -> str:
        return require_builtin_bridge(self.client)


def recover_interrupted_runtime_materialization(
    client: DockerClient,
    *,
    manifest_path: Path | None = None,
    repo_root: Path | None = None,
) -> str | None:
    """Recover only an exact container authorized by a private claim and ledger."""
    path = _resolve_manifest_path(manifest_path, repo_root)
    if not path.exists() and not path.is_symlink():
        return None
    claim: MaterializationClaim = _read_materialization_claim(path)
    claimed_container_id = claim["container_id"]
    reference = claimed_container_id or claim["name"]
    try:
        container = client.containers.get(reference)
    except Exception as error:
        if error.__class__.__name__ != "NotFound":
            raise
        if claimed_container_id is None:
            path.unlink()
            return None
        raise TestImageError("claimed materialization container is absent") from error
    if claimed_container_id is None:
        raise TestImageError(
            "materialization recovery lacks exact container authority"
        )
    owner = object.__new__(MaterializationContainerOwner)
    owner.client = client
    owner.api = DockerSdkApi(client)
    container_id = str(container.id)
    owner._validate_cleanup_target(container, claim)
    try:
        recovered_identity = RunIdentity(
            claim["project"], claim["phase"], claim["run_id"]
        )
        recovered_ledger = ResourceLedger.open(
            Path(str(claim["ledger_path"])), recovered_identity
        )
    except (OSError, ResourceLedgerError) as error:
        raise TestImageError(
            "materialization recovery ledger authority differs"
        ) from error
    try:
        record = recovered_ledger.get(ResourceKind.DOCKER_CONTAINER, container_id)
    except Exception as error:
        raise TestImageError(
            "materialization recovery ledger authority differs"
        ) from error
    expected_owner = MaterializationContainerOwner._owner(str(claim["name"]))
    if (
        record.creation_owner != expected_owner
        or not record.creation_observed
        or not record.cleanup_required
    ):
        raise TestImageError("materialization recovery ledger authority differs")
    recovered_ledger.mark_cleanup_attempted(
        ResourceKind.DOCKER_CONTAINER, container_id
    )
    try:
        owner._remove_claimed_container(container, claim)
    except MaterializationCleanupError as error:
        recovered_ledger.mark_cleanup_result(
            ResourceKind.DOCKER_CONTAINER, container_id, CleanupResult.FAILED
        )
        recovered_ledger.mark_final_presence(
            ResourceKind.DOCKER_CONTAINER,
            container_id,
            FinalPresence.ABSENT
            if error.cleanup_evidence.get("exact_container_exists_afterward") is False
            else FinalPresence.PRESENT,
        )
        raise
    except Exception:
        recovered_ledger.mark_cleanup_result(
            ResourceKind.DOCKER_CONTAINER, container_id, CleanupResult.FAILED
        )
        recovered_ledger.mark_final_presence(
            ResourceKind.DOCKER_CONTAINER, container_id, FinalPresence.PRESENT
        )
        raise
    recovered_ledger.mark_cleanup_result(
        ResourceKind.DOCKER_CONTAINER, container_id, CleanupResult.REMOVED
    )
    recovered_ledger.mark_final_presence(
        ResourceKind.DOCKER_CONTAINER, container_id, FinalPresence.ABSENT
    )
    path.unlink()
    return container_id


__all__ = [
    "MaterializationContainerOwner",
    "recover_interrupted_runtime_materialization",
]
