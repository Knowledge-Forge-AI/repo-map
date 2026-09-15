"""Narrow current-run Docker container creation for ordinary smoke tests."""

from __future__ import annotations

from typing import Any, Sequence

from repomap_test_support.resource_docker import (
    DockerBaseline,
    DockerOwnershipError,
    DockerResourceOwner,
    ownership_labels,
)
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_ledger import CleanupResult, FinalPresence


class CurrentRunDockerError(RuntimeError):
    """A current-run container could not be proved or restored exactly."""


class CurrentRunDockerCleanupError(CurrentRunDockerError):
    """Exact current-run cleanup could not be proved complete."""


class CurrentRunDockerBaselineError(CurrentRunDockerError):
    """The pre-existing Docker baseline changed during the run."""


class CurrentRunDockerContainers:
    """Create only exact, labelled containers owned by one live resource run."""

    def __init__(self, resource_run: Any, client: Any) -> None:
        if resource_run is None or getattr(resource_run, "ledger", None) is None:
            raise CurrentRunDockerError("a managed resource run is required")
        self.ledger = resource_run.ledger
        self.identity = self.ledger.identity
        self.api = DockerSdkApi(client)
        self.baseline = DockerBaseline.capture(
            self.api,
            kinds=(ResourceKind.DOCKER_CONTAINER,),
        )
        self.owner = DockerResourceOwner(
            self.identity,
            self.ledger,
            self.api,
            self.baseline,
        )

    def create(
        self,
        image_reference: str,
        command: Sequence[str] | None,
        *,
        role: str,
        **create_options: Any,
    ) -> str:
        """Create, read back, and ledger the exact returned container ID."""

        supplied_labels = dict(create_options.pop("labels", {}) or {})
        central_labels = ownership_labels(
            self.identity,
            role=role,
            retained=False,
        )
        if supplied_labels.keys() & central_labels.keys():
            raise CurrentRunDockerError("central Docker ownership labels are reserved")
        labels = {**supplied_labels, **central_labels}
        created_identity: str | None = None
        try:
            if command is None:
                container = self.api.client.containers.create(
                    image_reference,
                    labels=labels,
                    **create_options,
                )
            else:
                container = self.api.client.containers.create(
                    image_reference,
                    list(command),
                    labels=labels,
                    **create_options,
                )
            created_identity = str(container.id)
            if not created_identity:
                raise CurrentRunDockerError("Docker create returned no container ID")
            observed = self.api.inspect(ResourceKind.DOCKER_CONTAINER, created_identity)
            if observed is None or observed.identity != created_identity:
                raise CurrentRunDockerError(
                    "exact returned container ID failed Engine readback"
                )
            self.owner.register_created(
                ResourceKind.DOCKER_CONTAINER,
                created_identity,
                role=role,
            )
            self.require_no_volume_mounts(created_identity)
            return created_identity
        except Exception as error:
            if created_identity is None:
                raise
            if self.baseline.contains(ResourceKind.DOCKER_CONTAINER, created_identity):
                raise CurrentRunDockerError(
                    "container registration failed: baseline collision; direct removal refused"
                ) from error
            if isinstance(error, DockerOwnershipError):
                raise CurrentRunDockerError(
                    f"container registration failed: ownership refusal; direct removal refused: {error}"
                ) from error
            if isinstance(error, CurrentRunDockerCleanupError):
                raise CurrentRunDockerError(
                    f"container creation failed: cleanup restriction; direct removal refused: {error}"
                ) from error
            try:
                self.api.remove(ResourceKind.DOCKER_CONTAINER, created_identity)
                if self.api.inspect(ResourceKind.DOCKER_CONTAINER, created_identity) is not None:
                    raise CurrentRunDockerError(
                        "registration rollback did not prove exact container absence"
                    )
            except Exception as rollback_error:
                raise CurrentRunDockerCleanupError(
                    "container registration failed and exact rollback failed"
                ) from rollback_error
            raise CurrentRunDockerError(
                "container registration failed; exact returned ID was rolled back"
            ) from error

    def cleanup(self, identity: str) -> None:
        """Remove one exact ledger-authorized current-run container."""

        try:
            self.require_no_volume_mounts(identity)
            self.owner.cleanup(ResourceKind.DOCKER_CONTAINER, identity)
        except DockerOwnershipError as error:
            raise CurrentRunDockerCleanupError(str(error)) from error

    def register_observed(self, identity: str, *, role: str) -> None:
        """Ledger an exact CLI-returned ID against the pre-creation baseline."""
        try:
            self.owner.register_created(
                ResourceKind.DOCKER_CONTAINER,
                identity,
                role=role,
            )
        except Exception as error:
            raise CurrentRunDockerError(
                f"container registration failed: {error}"
            ) from error

        try:
            self.require_no_volume_mounts(identity)
        except Exception as error:
            try:
                self.ledger.mark_final_presence(
                    ResourceKind.DOCKER_CONTAINER,
                    identity,
                    FinalPresence.PRESENT,
                )
            except Exception:
                pass
            raise CurrentRunDockerCleanupError(
                f"container registration failed: refused due to volume mounts: {error}"
            ) from error

    def observe_removed(self, identity: str) -> None:
        """Close ledger ownership after an exact command removed the container."""
        record = self.ledger.get(ResourceKind.DOCKER_CONTAINER, identity)
        if not record.creation_observed or record.created_before_run:
            raise CurrentRunDockerCleanupError("ledger does not own removed container")
        if self.api.inspect(ResourceKind.DOCKER_CONTAINER, identity) is not None:
            raise CurrentRunDockerCleanupError("exact container remains after command")
        self.ledger.mark_cleanup_attempted(ResourceKind.DOCKER_CONTAINER, identity)
        self.ledger.mark_cleanup_result(
            ResourceKind.DOCKER_CONTAINER,
            identity,
            CleanupResult.REMOVED,
        )
        self.ledger.mark_final_presence(
            ResourceKind.DOCKER_CONTAINER,
            identity,
            FinalPresence.ABSENT,
        )

    def require_no_volume_mounts(self, identity: str) -> None:
        """Refuse cleanup if creation produced any Docker volume mount."""
        container = self.api.client.containers.get(identity)
        mounts = container.attrs.get("Mounts") or []
        if any(str(mount.get("Type", "")).lower() == "volume" for mount in mounts):
            raise CurrentRunDockerCleanupError(
                "container has an anonymous or unowned Docker volume mount"
            )

    def verify_baseline(self) -> None:
        """Prove the pre-existing container baseline is unchanged."""

        try:
            self.owner.verify_preexisting_unchanged()
        except DockerOwnershipError as error:
            raise CurrentRunDockerBaselineError(str(error)) from error
