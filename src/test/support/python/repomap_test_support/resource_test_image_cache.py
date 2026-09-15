from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from docker import DockerClient
from docker.models.images import Image
from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
from repomap_test_support.resource_docker_mediation import OperationTicket
from repomap_test_support.resource_ledger import ResourceLedger
from repomap_test_support.resource_run import TestResourceRun

from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_test_image_base import (
    TestImageError,
    repository_scratch_directory,
    require_private_scratch_directory,
)
from repomap_test_support.resource_test_image_materialization import (
    IntermediateCleanupResult, RuntimeMaterializationResult,
    RuntimeBuildIntermediateCleaner,
)
from repomap_test_support.resource_test_image_records import (
    DEPLOYMENT_IMAGE_PREFIX,
    LIFECYCLE_LOCK_DIRECTORY,
    RUNTIME_CACHE_IMAGE_PREFIX,
    RUNTIME_CACHE_RETENTION,
    TestImageInventory,
    TestImageRecord,
    _FINGERPRINT,
    _TRANSIENT_RESOURCE_LABEL_KEYS,
    build_test_image_record,
    ephemeral_labels,
    ephemeral_namespace_is_exact,
    exact_image_id,
    require_ephemeral_record,
    require_gc_owned_runtime_record,
    require_runtime_record,
    runtime_labels,
    runtime_labels_are_exact,
    runtime_namespace_is_exact,
)


@dataclass(frozen=True)
class CacheGcResult:
    removed: tuple[str, ...]
    deferred_in_use: tuple[str, ...]


def derive_lifecycle_lock_directory(repo_root: Path) -> Path:
    scratch = repository_scratch_directory(repo_root)
    return require_private_scratch_directory(scratch / LIFECYCLE_LOCK_DIRECTORY)


def derive_lifecycle_lock_path(repo_root: Path) -> Path:
    return derive_lifecycle_lock_directory(repo_root) / f"repomap-test-images-{os.getuid()}.lock"


@contextmanager
def lifecycle_lock(repo_root: Path):
    import fcntl

    lock_path = derive_lifecycle_lock_path(repo_root)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise TestImageError("test-image lifecycle lock ownership is unsafe")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def write_private_runtime_evidence(
    resource_run: object, fingerprint: str, payload: Mapping[str, object]
) -> None:
    layout = getattr(resource_run, "layout", None)
    retain = getattr(resource_run, "retain_evidence", None)
    if layout is None or not callable(retain):
        return
    path = Path(layout.run_root) / f"test-runtime-{fingerprint}.evidence.json"
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        read_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        read_descriptor = os.open(path, read_flags)
        try:
            metadata = os.fstat(read_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise TestImageError("private runtime identity evidence is unsafe")
            existing = json.loads(os.read(read_descriptor, 1_000_000))
        finally:
            os.close(read_descriptor)
        if existing.get("canonical_json") != payload.get("canonical_json"):
            raise TestImageError("private runtime identity evidence conflicts")
        retain(path, reason="diagnostic_evidence")
        return
    try:
        os.write(descriptor, content.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    retain(path, reason="diagnostic_evidence")


def dispose_failed_proof_runtime_cache(
    *,
    client: DockerClient,
    image_id: str,
    tag: str,
    fingerprint: str,
    parent_image_id: str,
    transient_labels: Mapping[str, str],
) -> str:
    """Remove one exact failed proof cache and no lookalike."""
    image_id = exact_image_id(image_id)
    parent_image_id = exact_image_id(parent_image_id)
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise TestImageError("failed proof fingerprint is not exact")
    if set(transient_labels) != _TRANSIENT_RESOURCE_LABEL_KEYS:
        raise TestImageError("failed proof transient label set differs")
    image = client.images.get(image_id)
    if exact_image_id(image.id) != image_id:
        raise TestImageError("failed proof image ID differs")
    tags = tuple(sorted(str(item) for item in image.tags))
    if tags != (tag,) or not tag.startswith(RUNTIME_CACHE_IMAGE_PREFIX):
        raise TestImageError("failed proof tag authority differs")
    attrs = image.attrs
    repo_digests = tuple(sorted(str(item) for item in attrs.get("RepoDigests") or ()))
    allowed_digest = f"repomap-test-runtime@{image_id}"
    if repo_digests not in {(), (allowed_digest,)}:
        raise TestImageError("failed proof RepoDigests differ")
    if str(attrs.get("Parent") or "") != parent_image_id:
        raise TestImageError("failed proof parent differs")
    expected_labels = {**runtime_labels(fingerprint), **dict(transient_labels)}
    if dict((attrs.get("Config") or {}).get("Labels") or {}) != expected_labels:
        raise TestImageError("failed proof label identity differs")
    api = DockerSdkApi(client)
    if api.image_references(image_id):
        raise TestImageError("failed proof image is container-referenced")
    client.images.remove(image_id, force=False, noprune=True)
    if api.inspect(ResourceKind.DOCKER_IMAGE, image_id) is not None:
        raise TestImageError("failed proof exact absence was not proved")
    return image_id


class TestImageCacheManager:
    """Cache and lifecycle operations for test images."""

    repo_root: Path
    resource_run: TestResourceRun
    ledger: ResourceLedger
    client: DockerClient
    api: DockerSdkApi
    boundary: RunWideDockerBoundary | None
    psycopg_release_version: str
    runtime_extras: tuple[str, ...]
    _last_materialization: RuntimeMaterializationResult | None
    _last_materialization_evidence: Mapping[str, object] | None

    def inventory(self) -> TestImageInventory:
        raise NotImplementedError

    def _runtime_dependencies(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _lifecycle_lock(self):
        return lifecycle_lock(self.repo_root)

    def _lifecycle_lock_path(self) -> Path:
        return derive_lifecycle_lock_path(self.repo_root)

    def _lifecycle_lock_directory(self) -> Path:
        return derive_lifecycle_lock_directory(self.repo_root)

    def _write_private_evidence(
        self, fingerprint: str, payload: Mapping[str, object]
    ) -> None:
        write_private_runtime_evidence(self.resource_run, fingerprint, payload)

    def _refuse_lookalike(self, inventory: TestImageInventory) -> None:
        for record in inventory.ownership_ambiguous:
            if any(tag.startswith(DEPLOYMENT_IMAGE_PREFIX) for tag in record.tags):
                raise TestImageError("managed test image has a deployment tag")
            raise TestImageError("runtime cache ownership ambiguity")
        for record in inventory.runtime_cache:
            if any(tag.startswith(DEPLOYMENT_IMAGE_PREFIX) for tag in record.tags):
                raise TestImageError("managed test image has a deployment tag")

    def _require_runtime_record(
        self, image_id: str, fingerprint: str
    ) -> TestImageRecord:
        return require_runtime_record(self.client, self.api, image_id, fingerprint)

    def _require_gc_owned_runtime_record(
        self, image_id: str, fingerprint: str
    ) -> TestImageRecord:
        return require_gc_owned_runtime_record(
            self.client, self.api, image_id, fingerprint
        )

    def _require_ephemeral_record(self, image_id: str) -> TestImageRecord:
        return require_ephemeral_record(
            self.client, self.api, image_id, self.ledger.identity.run_id
        )

    def _remove_cache_if_safe(self, record: TestImageRecord) -> bool:
        return self._remove_cache(record) if not record.container_references else False

    def _remove_cache(self, record: TestImageRecord) -> bool:
        fingerprint = str(record.labels.get("org.repomap.test.runtime-fingerprint") or "")
        current = self._require_gc_owned_runtime_record(record.image_id, fingerprint)
        if current.container_references or self.api.image_references(record.image_id):
            return False
        if self.boundary is not None:
            self.boundary.authorize_managed_runtime_cache_removal(record.image_id)
        self.api.remove(ResourceKind.DOCKER_IMAGE, record.image_id)
        if self.api.inspect(ResourceKind.DOCKER_IMAGE, record.image_id) is not None:
            raise TestImageError("runtime cache GC exact absence was not proved")
        if self.boundary is not None:
            self.boundary.record_managed_runtime_cache_removal(record.image_id)
        return True

    def gc_runtime_cache(
        self,
        protected_image_id: str,
        protected_fingerprint: str,
    ) -> CacheGcResult:
        with self._lifecycle_lock():
            return self._gc_runtime_cache_locked(
                protected_image_id, protected_fingerprint
            )

    def _gc_runtime_cache_locked(
        self,
        protected_image_id: str,
        protected_fingerprint: str,
    ) -> CacheGcResult:
        inventory = self.inventory()
        current = self._require_runtime_record(protected_image_id, protected_fingerprint)
        records = list(inventory.runtime_cache) + list(inventory.runtime_cache_orphans)
        if current.image_id not in {item.image_id for item in inventory.runtime_cache}:
            raise TestImageError("protected runtime cache image is not managed")
        deferred = set(
            item.image_id
            for item in records
            if item.image_id != protected_image_id and item.container_references
        )
        removable = sorted(
            (
                item
                for item in records
                if item.image_id != protected_image_id and not item.container_references
            ),
            key=lambda item: (item.created, item.image_id),
        )
        removed: list[str] = []
        while len(records) - len(removed) > RUNTIME_CACHE_RETENTION and removable:
            candidate = removable.pop(0)
            if self._remove_cache(candidate):
                removed.append(candidate.image_id)
            else:
                deferred.add(candidate.image_id)
        return CacheGcResult(tuple(removed), tuple(sorted(deferred)))

    def _observed_build_intermediates(
        self, outcome: str
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        result = self._last_materialization if outcome == "built" else None
        if result is None:
            return (), (), ()
        created = tuple(sorted(result.intermediate_created))
        removed = tuple(sorted(result.intermediate_removed))
        return created, removed, tuple(x for x in created if x not in set(removed))

    def _record_failed_materialization(self, ticket: OperationTicket, error: Exception) -> None:
        assert self.boundary is not None
        evidence = getattr(error, "materialization_evidence", None)
        created: tuple[str, ...] = ()
        removed: tuple[str, ...] = ()
        final_image_id = ""
        if isinstance(evidence, Mapping):
            created = tuple(evidence.get("intermediate_created_ids") or ())
            removed = tuple(evidence.get("intermediate_removed_ids") or ())
            final_image_id = str(evidence.get("final_image_id") or "")
        self.boundary.record_materialization(
            ticket,
            final_image_id=final_image_id,
            intermediate_created_ids=created,
            intermediate_removed_ids=removed,
        )

    def cleanup_retained_runtime_build_intermediates(
        self,
        *,
        final_image_id: str,
        fingerprint: str,
        candidate_ids: Sequence[str],
    ) -> IntermediateCleanupResult:
        """Remove only an exact validated legacy-builder chain for this runtime."""
        with self._lifecycle_lock():
            self._require_runtime_record(final_image_id, fingerprint)
            dependencies = (*self._runtime_dependencies(), *self.runtime_extras)
            install = "python -m pip install --no-cache-dir " + " ".join(dependencies)
            probe = (
                "python -c import psycopg, typing_extensions; "
                f"assert psycopg.__version__ == {self.psycopg_release_version!r}"
            )
            created_by = [install, probe]
            label_states: list[Mapping[str, str]] = [{}, {}]
            cumulative: dict[str, str] = {}
            sorted_labels = sorted(runtime_labels(fingerprint).items())
            for key, value in sorted_labels[:-1]:
                cumulative[key] = value
                created_by.append(f"/bin/sh -c #(nop)  LABEL {key}={value}")
                label_states.append(dict(cumulative))
            return RuntimeBuildIntermediateCleaner(self.client).cleanup(
                final_image_id=final_image_id,
                candidate_ids=candidate_ids,
                expected_created_by=created_by,
                expected_labels=label_states,
            )

    def _probe_runtime_image(self, image_id: str) -> None:
        owner = CurrentRunDockerContainers(self.resource_run, self.client)
        container_id = owner.create(
            image_id,
            [
                "-c",
                (
                    "import psycopg, typing_extensions; "
                    f"assert psycopg.__version__ == {self.psycopg_release_version!r}"
                ),
            ],
            role="test-runtime-cache-probe",
            entrypoint=["python"],
            network_mode="none",
        )
        error: Exception | None = None
        try:
            container = self.client.containers.get(container_id)
            container.start()
            result = container.wait(timeout=120)
            if int(result.get("StatusCode", 2)) != 0:
                raise TestImageError("runtime dependency probe failed")
        except Exception as caught:
            error = caught
        finally:
            owner.cleanup(container_id)
        if error is not None:
            raise TestImageError("runtime dependency probe failed") from error

    def _record(self, image: Image) -> TestImageRecord:
        return build_test_image_record(image, self.api.image_references(exact_image_id(image.id)))

    _runtime_namespace_is_exact = staticmethod(runtime_namespace_is_exact)

    def _ephemeral_namespace_is_exact(self, record: TestImageRecord) -> bool:
        return ephemeral_namespace_is_exact(record, self.ledger.identity.run_id)

    _runtime_labels = staticmethod(runtime_labels)

    @classmethod
    def _runtime_labels_are_exact(
        cls, labels: Mapping[str, str], fingerprint: str
    ) -> bool:
        return runtime_labels_are_exact(labels, fingerprint)

    _ephemeral_labels = staticmethod(ephemeral_labels)
    _exact_id = staticmethod(exact_image_id)


__all__ = [
    "CacheGcResult",
    "TestImageCacheManager",
    "derive_lifecycle_lock_directory",
    "derive_lifecycle_lock_path",
    "dispose_failed_proof_runtime_cache",
    "lifecycle_lock",
    "write_private_runtime_evidence",
]
