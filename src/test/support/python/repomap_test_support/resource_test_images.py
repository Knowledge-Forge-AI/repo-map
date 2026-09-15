from __future__ import annotations

import io
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import CleanupResult, FinalPresence, ResourceKind
from repomap_test_support.resource_test_image_base import (
    BaseImageProvenance, TestImageError, read_configured_base, read_exact_local_image,
)
from repomap_test_support.resource_test_image_cache import (
    CacheGcResult, TestImageCacheManager, dispose_failed_proof_runtime_cache,
)
from repomap_test_support.resource_test_image_identity import canonical_runtime_fingerprint
from repomap_test_support.resource_test_image_materialization import RuntimeImageMaterializer
from repomap_test_support.resource_test_image_records import (
    DEPLOYMENT_IMAGE_PREFIX, EPHEMERAL_IMAGE_PREFIX, IMAGE_RECIPE_SCHEMA,
    RUNTIME_CACHE_IMAGE_PREFIX, RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA,
    RuntimeIdentity, TestImageInventory, TestImageRecord,
    create_runtime_identity, derive_runtime_tag, populate_runtime_manager_evidence,
    read_project_runtime_dependencies, record_materialization_failure,
    scan_legacy_inventory, scan_test_image_inventory, validate_manager_configuration,
)


class TestImageManager(TestImageCacheManager):
    """Sole owner of RepoMap test-image creation, reuse, and exact cleanup."""

    def __init__(
        self,
        *,
        repo_root: Path,
        resource_run: Any,
        client: Any,
        base_reference: str,
        python_base_family: str,
        python_version: str,
        psycopg_release_version: str,
        runtime_extras: Sequence[str] = (),
        recipe_schema: int = IMAGE_RECIPE_SCHEMA,
        boundary: Any | None = None,
        probe: Callable[[str], None] | None = None,
    ) -> None:
        self.ledger, self.base_authority = validate_manager_configuration(
            resource_run, base_reference, python_base_family, recipe_schema
        )
        self.repo_root, self.resource_run, self.client = repo_root.resolve(), resource_run, client
        self.api, self.base_reference = DockerSdkApi(client), base_reference
        self.base_repository, self.recipe_schema = self.base_authority.repository, recipe_schema
        self.python_base_family, self.python_version = python_base_family, python_version
        self.psycopg_release_version, self.boundary = psycopg_release_version, boundary
        self.runtime_extras = tuple(sorted(runtime_extras))
        self._probe = probe or self._probe_runtime_image
        self._ephemeral_ids: list[str] = []
        self._last_identity: RuntimeIdentity | None = None
        self._base_provenance: BaseImageProvenance | None = None
        self._base_pulled = False
        self._last_materialization: Any | None = None
        self._last_materialization_evidence: Mapping[str, Any] | None = None

    @property
    def base_provenance(self) -> BaseImageProvenance:
        if self._base_provenance is None:
            raise TestImageError("configured base provenance is unavailable")
        return self._base_provenance

    @property
    def last_materialization_evidence(self) -> Mapping[str, Any] | None:
        return self._last_materialization_evidence

    def _runtime_dependencies(self) -> tuple[str, ...]:
        return read_project_runtime_dependencies(
            self.repo_root, self.psycopg_release_version
        )

    def runtime_identity(self, base: Any | None = None) -> RuntimeIdentity:
        dependencies = self._runtime_dependencies()
        base = self._local_base_image() if base is None else base
        self._last_identity = create_runtime_identity(
            dependencies=dependencies,
            base=base,
            base_provenance=self.base_provenance,
            base_authority=self.base_authority,
            base_reference=self.base_reference,
            python_base_family=self.python_base_family,
            python_version=self.python_version,
            psycopg_release_version=self.psycopg_release_version,
            recipe_schema=self.recipe_schema,
            runtime_extras=self.runtime_extras,
        )
        return self._last_identity

    def runtime_tag(self, fingerprint: str) -> str:
        observed = str(self.client.info().get("Architecture") or "")
        return derive_runtime_tag(observed, self.python_version, fingerprint)

    def inventory(self) -> TestImageInventory:
        return scan_test_image_inventory(
            self.client.images.list(all=True),
            self.ledger.identity.run_id,
            self.api.image_references,
        )

    @staticmethod
    def legacy_inventory(client: Any) -> tuple[TestImageRecord, ...]:
        return scan_legacy_inventory(
            client.images.list(all=True), DockerSdkApi(client).image_references
        )

    def ensure_runtime_image(self) -> str:
        with self._lifecycle_lock():
            base = self._ensure_configured_base_locked()
            identity = self.runtime_identity(base)
            evidence: dict[str, Any] = {
                "schema": "repomap-test-runtime-identity-v1",
                "fingerprint": identity.fingerprint,
                "canonical_json": identity.canonical_json,
            }
            try:
                selected_id = self._ensure_runtime_image_locked(identity, evidence)
            except Exception as error:
                opaque = record_materialization_failure(evidence, error)
                self._write_private_evidence(identity.fingerprint, evidence)
                if opaque:
                    raise TestImageError(
                        "structured materialization failure evidence is unavailable"
                    ) from error
                raise
            self._write_private_evidence(identity.fingerprint, evidence)
            return selected_id

    def _ensure_runtime_image_locked(
        self, identity: RuntimeIdentity, evidence: dict[str, Any]
    ) -> str:
        expected_tag = self.runtime_tag(identity.fingerprint)
        inventory = self.inventory()
        self._refuse_lookalike(inventory)
        matching = [
            item for item in inventory.runtime_cache
            if item.labels.get("org.repomap.test.runtime-fingerprint") == identity.fingerprint
        ]
        duplicates: list[str] = []
        if matching:
            selected = max(matching, key=lambda item: (item.created, item.image_id))
            outcome = "reused"
            for duplicate in matching:
                if duplicate.image_id != selected.image_id:
                    duplicates.append(duplicate.image_id)
                    self._remove_cache_if_safe(duplicate)
        else:
            selected = self._build_runtime_image(identity, expected_tag)
            outcome = "built"
        selected = self._require_runtime_record(selected.image_id, identity.fingerprint)
        self._probe(selected.image_id)
        gc_result = self._gc_runtime_cache_locked(selected.image_id, identity.fingerprint)
        intermediates = self._observed_build_intermediates(outcome)
        populate_runtime_manager_evidence(
            evidence,
            outcome=outcome,
            selected_image_id=selected.image_id,
            duplicates=duplicates,
            gc_removed=gc_result.removed,
            gc_deferred_in_use=gc_result.deferred_in_use,
            intermediates=intermediates,
            materialization_evidence=self._last_materialization_evidence,
            boundary=self.boundary,
        )
        return selected.image_id

    def build_ephemeral_image(
        self, dockerfile: str, *, ordinal: int, exact_local_base_reference: str
    ) -> str:
        if ordinal < 1:
            raise TestImageError("ephemeral image ordinal must be positive")
        self._require_exact_local_image(exact_local_base_reference)
        if not dockerfile.startswith(f"FROM {exact_local_base_reference}\n"):
            raise TestImageError(
                "ephemeral Dockerfile base is not the authorized exact local image"
            )
        run_id = self.ledger.identity.run_id
        tag = f"{EPHEMERAL_IMAGE_PREFIX}{run_id}-{ordinal}"
        image, _logs = self.client.images.build(
            fileobj=io.BytesIO(dockerfile.encode("utf-8")),
            tag=tag,
            labels=self._ephemeral_labels(run_id),
            pull=False, rm=True, forcerm=True,
        )
        image_id = self._exact_id(image.id)
        self.register_ephemeral_image(image_id)
        return image_id

    def register_ephemeral_image(self, image_id: str) -> None:
        image_id = self._exact_id(image_id)
        self._require_ephemeral_record(image_id)
        self.ledger.register(
            ResourceKind.DOCKER_IMAGE, image_id, creation_owner="TestImageManager",
            created_before_run=False, creation_observed=True, cleanup_required=True,
        )
        if image_id not in self._ephemeral_ids:
            self._ephemeral_ids.append(image_id)

    def cleanup_ephemeral_run_images(self) -> None:
        recoverable = {
            r.identity for r in self.ledger.records
            if r.kind is ResourceKind.DOCKER_IMAGE and r.creation_owner == "TestImageManager"
            and not r.created_before_run and r.cleanup_required
            and r.cleanup_result is CleanupResult.NOT_ATTEMPTED
        }
        failures: list[Exception] = []
        for image_id in tuple(sorted(set(self._ephemeral_ids) | recoverable)):
            self.ledger.mark_cleanup_attempted(ResourceKind.DOCKER_IMAGE, image_id)
            try:
                self._require_ephemeral_record(image_id)
                if self.api.image_references(image_id):
                    raise TestImageError("ephemeral image is still container-referenced")
                self.api.remove(ResourceKind.DOCKER_IMAGE, image_id)
                if self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id) is not None:
                    raise TestImageError("ephemeral image exact absence was not proved")
            except Exception as error:
                self.ledger.mark_cleanup_result(ResourceKind.DOCKER_IMAGE, image_id, CleanupResult.FAILED)
                self.ledger.mark_final_presence(ResourceKind.DOCKER_IMAGE, image_id, FinalPresence.PRESENT)
                failures.append(error)
                continue
            self.ledger.mark_cleanup_result(ResourceKind.DOCKER_IMAGE, image_id, CleanupResult.REMOVED)
            self.ledger.mark_final_presence(ResourceKind.DOCKER_IMAGE, image_id, FinalPresence.ABSENT)
            if image_id in self._ephemeral_ids:
                self._ephemeral_ids.remove(image_id)
        if failures:
            raise TestImageError(
                f"ephemeral image cleanup failed for {len(failures)} exact image ID(s); first error: {failures[0]}"
            ) from failures[0]

    def verify_boundary(self) -> Mapping[str, int]:
        if self.boundary is None:
            raise TestImageError("run-wide Docker boundary is unavailable")
        return self.boundary.verify_terminal()

    def _local_base_image(self) -> Any:
        image, provenance = read_configured_base(
            self.client, self.base_reference, allow_missing=False
        )
        assert image is not None and provenance is not None
        self._base_provenance = replace(provenance, pulled=self._base_pulled)
        return image

    def _ensure_configured_base_locked(self) -> Any:
        image, provenance = read_configured_base(
            self.client, self.base_reference, allow_missing=True
        )
        if image is None:
            reference = self.base_authority.canonical_reference
            with ExitStack() as stack:
                ticket = stack.enter_context(
                    self.boundary.managed_external_base_pull(request=reference)
                ) if self.boundary is not None else None
                self.client.images.pull(reference)
                image, provenance = read_configured_base(
                    self.client, self.base_reference, allow_missing=False
                )
                assert image is not None and provenance is not None
                if ticket is not None and self.boundary is not None:
                    self.boundary.complete_operation(
                        ticket, image_ids=(provenance.image_id,)
                    )
            self._base_pulled = True
            provenance = replace(provenance, pulled=True)
            self.ledger.register(
                ResourceKind.DOCKER_IMAGE, provenance.image_id, creation_owner="TestImageManager",
                created_before_run=False, creation_observed=True, cleanup_required=False,
            )
            if self.boundary is not None:
                self.boundary.register_managed_external_test_base(provenance)
        assert image is not None and provenance is not None
        self._base_provenance = replace(provenance, pulled=self._base_pulled)
        return image

    def _require_exact_local_image(self, reference: str) -> Any:
        image = read_exact_local_image(self.client, reference)
        self._exact_id(image.id)
        return image

    def _build_runtime_image(
        self, identity: RuntimeIdentity, tag: str
    ) -> TestImageRecord:
        dependencies = (
            *identity.fields["project_runtime_dependencies"],
            *identity.fields["runtime_extras"],
        )
        with ExitStack() as stack:
            ticket = stack.enter_context(
                self.boundary.managed_test_runtime_build(request=tag)
            ) if self.boundary is not None else None
            try:
                result = RuntimeImageMaterializer(
                    self.resource_run, self.client, repo_root=self.repo_root
                ).materialize(
                    base_image_id=self.base_provenance.image_id,
                    tag=tag,
                    labels=self._runtime_labels(identity.fingerprint),
                    dependencies=dependencies,
                    psycopg_release_version=self.psycopg_release_version,
                )
            except TestImageError as error:
                if ticket is not None:
                    self._record_failed_materialization(ticket, error)
                raise
            if ticket is not None and self.boundary is not None:
                self.boundary.record_materialization(
                    ticket,
                    final_image_id=result.image_id,
                    intermediate_created_ids=result.intermediate_created,
                    intermediate_removed_ids=result.intermediate_removed,
                )
                self.boundary.complete_operation(
                    ticket, image_ids=(result.image_id,)
                )
        self._last_materialization = result
        self._last_materialization_evidence = dict(result.evidence)
        image_id = self._exact_id(result.image_id)
        self.ledger.register(
            ResourceKind.DOCKER_IMAGE, image_id, creation_owner="TestImageManager",
            created_before_run=False, creation_observed=True, cleanup_required=False,
        )
        record = self._require_runtime_record(image_id, identity.fingerprint)
        if self.boundary is not None:
            self.boundary.register_managed_runtime_cache(image_id, identity.fingerprint)
        return record


def ensure_canonical_runtime_image(
    *, repo_root: Path, resource_run: Any, client: Any, boundary: Any
) -> str:
    """Ensure the repository's one canonical dependency-only smoke image."""
    from repomap_kg.runtime.release import (
        PSYCOPG_RELEASE_VERSION,
        PYTHON_RELEASE_IMAGE,
        PYTHON_RELEASE_VERSION,
    )

    return TestImageManager(
        repo_root=repo_root,
        resource_run=resource_run,
        client=client,
        boundary=boundary,
        base_reference=PYTHON_RELEASE_IMAGE,
        python_base_family="python:3.12-slim-bookworm",
        python_version=PYTHON_RELEASE_VERSION,
        psycopg_release_version=PSYCOPG_RELEASE_VERSION,
    ).ensure_runtime_image()


__all__ = (
    "CacheGcResult", "DEPLOYMENT_IMAGE_PREFIX", "EPHEMERAL_IMAGE_PREFIX",
    "RUNTIME_CACHE_IMAGE_PREFIX", "RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA",
    "RuntimeIdentity", "TestImageError", "TestImageInventory", "TestImageManager",
    "TestImageRecord", "canonical_runtime_fingerprint",
    "dispose_failed_proof_runtime_cache", "ensure_canonical_runtime_image",
)
