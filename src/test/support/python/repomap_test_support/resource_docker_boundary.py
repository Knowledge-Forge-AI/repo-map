"""Run-wide exact Docker image and volume residue boundary.

Operation counts are never literals here. The eight operation fields are
derived from the run-scoped :class:`DockerOperationJournal` population, and
the seven inventory fields are counted over exact terminal Engine IDs. A zero
therefore always names an observed empty population rather than an assertion.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from repomap_test_support.resource_docker import DockerBaseline
from repomap_test_support.resource_docker_boundary_ownership import (
    cross_check,
    is_current_run_ephemeral,
    is_external_base,
    is_runtime_cache,
    is_runtime_cache_gc_owned,
    ledger_owns,
)
from repomap_test_support.resource_docker_boundary_records import (
    PROJECTION_FIELDS,
    _INVENTORY_FIELDS,
    _KINDS,
    retain_operation_evidence,
    verify_terminal,
)
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_docker_mediation import (
    CanonicalDockerAuthority,
    OperationTicket,
)
from repomap_test_support.resource_docker_operations import (
    DERIVED_OPERATION_FIELDS,
    DockerAuthorityClass,
    DockerOperationKind,
)
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedgerError,
)
from repomap_test_support.resource_test_image_base import BaseImageProvenance


class RunWideDockerResidueError(RuntimeError):
    """Terminal image/volume state cannot be accepted or mutated."""

    def __init__(self, message: str, projection: dict[str, int]) -> None:
        self.projection = dict(projection)
        super().__init__(message)


class RunWideDockerBoundary:
    """Protect entry state and fail closed on every exact new terminal ID."""

    def __init__(
        self,
        resource_run: Any,
        client: Any,
        *,
        authority: CanonicalDockerAuthority | None = None,
    ) -> None:
        ledger = getattr(resource_run, "ledger", None)
        if ledger is None:
            # No ledger means no run-scoped journal, so no population exists to
            # count. An empty projection states that rather than claiming zero.
            raise RunWideDockerResidueError("managed resource ledger is required", {})
        self.ledger = ledger
        if authority is None:
            # Inventing an authority here would let the boundary report
            # ``unmanaged_*`` zeros over a population nothing ever watched.
            raise RunWideDockerResidueError(
                "an installed canonical Docker authority is required", {}
            )
        self.authority = authority
        self.journal = self.authority.journal
        self.client = client
        self.api = DockerSdkApi(client)
        self.baseline = DockerBaseline.capture(self.api, kinds=_KINDS)
        self._managed_runtime_caches: dict[str, str] = {}
        self._managed_runtime_build_count = 0
        self._managed_system_candidate_build_count = 0
        self._managed_external_base_pull_count = 0
        self._managed_external_bases: dict[str, BaseImageProvenance] = {}
        self._authorized_runtime_cache_removals: set[str] = set()
        self._removed_runtime_caches: set[str] = set()
        self._manager_evidence: list[dict[str, object]] = []

    def projection(self) -> dict[str, int]:
        """Derive the operation fields; inventory fields await enumeration."""
        if not self.authority.installed:
            raise RunWideDockerResidueError(
                "canonical Docker authority is not installed, so no unmanaged "
                "population was observed",
                {},
            )
        derived = self.journal.derive_counters()
        if set(derived) != set(DERIVED_OPERATION_FIELDS):
            raise RunWideDockerResidueError(
                "derived Docker operation fields are incomplete", {}
            )
        return {**derived, **{field: 0 for field in _INVENTORY_FIELDS}}

    def operation_evidence(self) -> dict[str, Any]:
        """Full derivation evidence that survives cleanup and later failure."""
        return self.journal.derivation_evidence()

    def retain_operation_evidence(self, resource_run: Any = None) -> Path:
        """Write the derivation beside the journal and retain both."""
        return retain_operation_evidence(
            self.journal,
            self.operation_evidence(),
            resource_run,
        )

    @contextmanager
    def managed_test_runtime_build(self, *, request: str) -> Iterator[OperationTicket]:
        """Authorize the one managed runtime image build this run may perform."""
        if self._managed_runtime_build_count >= 1:
            raise RunWideDockerResidueError(
                "managed test runtime image build count exceeds one",
                self.projection(),
            )
        self._managed_runtime_build_count += 1
        with self.authority.authorize(
            kind=DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD,
            authority=DockerAuthorityClass.MANAGED_TEST_RUNTIME,
            owner="TestImageManager",
            mechanism="managed-runtime-materialization",
            request=request,
        ) as ticket:
            yield ticket

    @contextmanager
    def managed_system_candidate_build(self, *, request: str) -> Iterator[OperationTicket]:
        """Authorize the one managed system candidate image build this run may perform."""
        if self._managed_system_candidate_build_count >= 1:
            raise RunWideDockerResidueError(
                "managed system candidate image build count exceeds one",
                self.projection(),
            )
        self._managed_system_candidate_build_count += 1
        with self.authority.authorize(
            kind=DockerOperationKind.DOCKER_BUILD,
            authority=DockerAuthorityClass.MANAGED_SYSTEM_CANDIDATE,
            owner="SystemCandidateImageBuilder",
            mechanism="docker-candidate-build",
            request=request,
        ) as ticket:
            yield ticket

    @contextmanager
    def managed_external_base_pull(self, *, request: str) -> Iterator[OperationTicket]:
        """Authorize the one managed exact-digest external base pull."""
        if self._managed_external_base_pull_count >= 1:
            raise RunWideDockerResidueError(
                "managed external base pull count exceeds one",
                self.projection(),
            )
        self._managed_external_base_pull_count += 1
        with self.authority.authorize(
            kind=DockerOperationKind.DOCKER_PULL,
            authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
            owner="TestImageManager",
            mechanism="docker-sdk-high",
            request=request,
        ) as ticket:
            yield ticket

    def complete_operation(
        self,
        ticket: OperationTicket,
        *,
        image_ids: tuple[str, ...] = (),
        cleanup_disposition: str | None = None,
    ) -> None:
        self.authority.complete(
            ticket, image_ids=image_ids, cleanup_disposition=cleanup_disposition
        )

    def record_materialization(
        self,
        ticket: OperationTicket,
        *,
        final_image_id: str,
        intermediate_created_ids: tuple[str, ...],
        intermediate_removed_ids: tuple[str, ...],
    ) -> None:
        self.journal.record_materialization(
            event_id=ticket.event_id,
            final_image_id=final_image_id,
            intermediate_created_ids=intermediate_created_ids,
            intermediate_removed_ids=intermediate_removed_ids,
        )

    def record_manager_evidence(self, evidence: Mapping[str, Any]) -> None:
        """Accept the manager's own counts so they can be cross-checked."""
        self._manager_evidence.append(dict(evidence))

    def register_managed_runtime_cache(
        self, image_id: str, fingerprint: str
    ) -> None:
        if image_id in self.baseline.snapshots[ResourceKind.DOCKER_IMAGE]:
            raise RunWideDockerResidueError(
                "pre-existing image cannot become a current-run managed cache",
                self.projection(),
            )
        item = self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id)
        if item is None or not self._is_runtime_cache(item, fingerprint):
            raise RunWideDockerResidueError(
                "managed runtime cache readback failed",
                self.projection(),
            )
        try:
            record = self.ledger.get(ResourceKind.DOCKER_IMAGE, image_id)
        except ResourceLedgerError as error:
            raise RunWideDockerResidueError(
                "managed runtime cache ledger record is absent",
                self.projection(),
            ) from error
        if not (
            record.creation_owner == "TestImageManager"
            and record.creation_observed
            and not record.created_before_run
            and not record.cleanup_required
        ):
            raise RunWideDockerResidueError(
                "managed runtime cache ledger record is invalid",
                self.projection(),
            )
        self._managed_runtime_caches[image_id] = fingerprint

    def register_managed_external_test_base(
        self, provenance: BaseImageProvenance
    ) -> None:
        image_id = provenance.image_id
        if image_id in self.baseline.snapshots[ResourceKind.DOCKER_IMAGE]:
            raise RunWideDockerResidueError(
                "pre-existing image cannot become a current-run managed external base",
                self.projection(),
            )
        try:
            record = self.ledger.get(ResourceKind.DOCKER_IMAGE, image_id)
        except ResourceLedgerError as error:
            raise RunWideDockerResidueError(
                "managed external base ledger record is absent",
                self.projection(),
            ) from error
        if not (
            record.creation_owner == "TestImageManager"
            and record.creation_observed
            and not record.created_before_run
            and not record.cleanup_required
            and self._managed_external_base_pull_count == 1
            and provenance.pulled
            and self._is_external_base(provenance)
        ):
            raise RunWideDockerResidueError(
                "managed external base readback failed",
                self.projection(),
            )
        self._managed_external_bases[image_id] = provenance

    def authorize_managed_runtime_cache_removal(self, image_id: str) -> None:
        expected = self.baseline.snapshots[ResourceKind.DOCKER_IMAGE].get(image_id)
        current = self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id)
        if expected is not None:
            if not self._is_runtime_cache(expected):
                raise RunWideDockerResidueError(
                    "runtime cache GC did not target an exact managed baseline image",
                    self.projection(),
                )
            if current != expected:
                raise RunWideDockerResidueError(
                    "runtime cache GC target changed after run admission",
                    self.projection(),
                )
        else:
            fingerprint = self._managed_runtime_caches.get(image_id)
            if fingerprint is None or not self._is_runtime_cache_gc_owned(
                current, fingerprint
            ):
                raise RunWideDockerResidueError(
                    "runtime cache GC did not target an exact manager-created image",
                    self.projection(),
                )
        self._authorized_runtime_cache_removals.add(image_id)

    def record_managed_runtime_cache_removal(self, image_id: str) -> None:
        if image_id not in self._authorized_runtime_cache_removals:
            raise RunWideDockerResidueError(
                "runtime cache GC removal lacked pre-delete authorization",
                self.projection(),
            )
        if any(
            item.identity == image_id
            for item in self.api.list_objects(ResourceKind.DOCKER_IMAGE)
        ):
            raise RunWideDockerResidueError(
                "runtime cache GC exact absence was not proved",
                self.projection(),
            )
        self._authorized_runtime_cache_removals.remove(image_id)
        self._managed_runtime_caches.pop(image_id, None)
        self._removed_runtime_caches.add(image_id)

    def verify_terminal(self) -> dict[str, int]:
        """Read exact terminal IDs; never remove or otherwise mutate them."""
        return verify_terminal(self, RunWideDockerResidueError)

    def _cross_check(self, projection: dict[str, int]) -> None:
        """Fail closed when two independent observers disagree."""
        cross_check(self, projection, RunWideDockerResidueError)

    def _is_external_base(self, provenance: BaseImageProvenance) -> bool:
        return is_external_base(self.client, provenance)

    def close(self, resource_run: Any = None) -> None:
        """Retain evidence first, then release process-wide mediation."""
        try:
            self.retain_operation_evidence(resource_run)
        finally:
            self.close_client()

    def close_client(self) -> None:
        self.authority.uninstall()
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def _ledger_owns(self, kind: ResourceKind, identity: str) -> bool:
        return ledger_owns(self.ledger, kind, identity)

    @staticmethod
    def _is_runtime_cache(item: Any, fingerprint: str | None = None) -> bool:
        return is_runtime_cache(item, fingerprint)

    @staticmethod
    def _is_runtime_cache_gc_owned(item: Any, fingerprint: str) -> bool:
        return is_runtime_cache_gc_owned(item, fingerprint)

    def _is_current_run_ephemeral(self, item: Any) -> bool:
        return is_current_run_ephemeral(self.ledger, item)


__all__ = [
    "PROJECTION_FIELDS",
    "RunWideDockerBoundary",
    "RunWideDockerResidueError",
]
