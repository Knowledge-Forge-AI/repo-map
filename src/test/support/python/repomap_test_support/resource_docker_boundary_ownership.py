"""Typed ownership predicates for the run-wide Docker boundary."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable, Mapping, Protocol, Sequence

from repomap_test_support.resource_docker import DockerBaseline, DockerObject
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_docker_operations import DockerOperationJournal
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    ResourceLedgerError,
)
from repomap_test_support.resource_test_image_base import (
    BaseImageProvenance,
    normalize_architecture_pair,
    parse_immutable_image_authority,
    repo_digests_match_authority,
)


_MANAGER_CROSS_CHECK = {
    "runtime_build_intermediate_created_count": (
        "managed_runtime_build_intermediate_created_count"
    ),
    "runtime_build_intermediate_removed_count": (
        "managed_runtime_build_intermediate_removed_count"
    ),
    "runtime_build_intermediate_residue_count": (
        "managed_runtime_build_intermediate_residue_count"
    ),
}
_MANAGED = "org.repomap.test.managed"
_IMAGE_CLASS = "org.repomap.test.image.class"
_IMAGE_SCHEMA = "org.repomap.test.image.schema"
_FINGERPRINT = "org.repomap.test.runtime-fingerprint"
_REPOSITORY = "org.repomap.test.repository"
_RUN_ID = "org.repomap.test.run-id"


class DockerImage(Protocol):
    id: str
    tags: Sequence[str]
    attrs: Mapping[str, object]


class DockerImageCollection(Protocol):
    def get(self, identity: str) -> DockerImage: ...


class DockerClient(Protocol):
    images: DockerImageCollection

    def info(self) -> Mapping[str, object]: ...


class BoundaryView(Protocol):
    api: DockerSdkApi
    baseline: DockerBaseline
    journal: DockerOperationJournal
    ledger: ResourceLedger
    _managed_external_bases: dict[str, BaseImageProvenance]
    _managed_external_base_pull_count: int
    _managed_runtime_build_count: int
    _managed_runtime_caches: dict[str, str]
    _managed_system_candidate_build_count: int
    _manager_evidence: list[dict[str, object]]
    _removed_runtime_caches: set[str]

    def projection(self) -> dict[str, int]: ...

    def _cross_check(self, projection: dict[str, int]) -> None: ...

    def _is_external_base(self, provenance: BaseImageProvenance) -> bool: ...

    def _is_current_run_ephemeral(self, item: DockerObject) -> bool: ...

    def _is_runtime_cache(
        self, item: DockerObject, fingerprint: str | None = None
    ) -> bool: ...

    def _ledger_owns(self, kind: ResourceKind, identity: str) -> bool: ...


ResidueErrorFactory = Callable[[str, dict[str, int]], RuntimeError]


def cross_check(
    boundary: BoundaryView,
    projection: dict[str, int],
    residue_error: ResidueErrorFactory,
) -> None:
    """Fail closed when manager, journal, or Engine observers disagree."""
    if (
        projection["managed_test_runtime_image_build_count"]
        != boundary._managed_runtime_build_count
        or projection["managed_system_candidate_image_build_count"]
        != boundary._managed_system_candidate_build_count
        or projection["managed_external_base_pull_count"]
        != boundary._managed_external_base_pull_count
    ):
        raise residue_error(
            "authorized operation count disagrees with the operation journal",
            projection,
        )
    for evidence in boundary._manager_evidence:
        for manager_field, derived_field in _MANAGER_CROSS_CHECK.items():
            if manager_field not in evidence:
                raise residue_error(
                    "managed image manager evidence omits an operation count",
                    projection,
                )
            value = evidence[manager_field]
            if isinstance(value, bool):
                observed_count = int(value)
            elif isinstance(value, int):
                observed_count = value
            elif isinstance(value, str):
                observed_count = int(value)
            else:
                raise residue_error(
                    "managed image manager evidence has an invalid operation count",
                    projection,
                )
            if observed_count != projection[derived_field]:
                raise residue_error(
                    "managed image manager evidence disagrees with the "
                    "operation journal",
                    projection,
                )
    terminal = {
        identity
        for observation in boundary.journal.materializations()
        for identity in observation.intermediate_terminal_ids
    }
    if terminal.intersection(
        item.identity
        for item in boundary.api.list_objects(ResourceKind.DOCKER_IMAGE)
    ):
        raise residue_error(
            "managed runtime build intermediate images remain on the Engine",
            projection,
        )


def is_external_base(
    client: DockerClient,
    provenance: BaseImageProvenance,
) -> bool:
    """Validate immutable reference, digest, and architecture readback."""
    image_id = provenance.image_id
    try:
        image = client.images.get(image_id)
        authority = parse_immutable_image_authority(provenance.reference)
        image_architecture = str(image.attrs.get("Architecture") or "")
        server_architecture = str(client.info().get("Architecture") or "")
        canonical_image, canonical_server = normalize_architecture_pair(
            image_architecture,
            server_architecture,
        )
        raw_repo_digests = image.attrs.get("RepoDigests")
        if not isinstance(raw_repo_digests, Iterable):
            return False
        repo_digests = tuple(str(item) for item in raw_repo_digests)
        repo_digest_matches = repo_digests_match_authority(
            authority, repo_digests
        )
    except Exception:
        return False
    tags = tuple(str(tag) for tag in image.tags)
    return (
        str(image.id) == image_id
        and authority.repository == provenance.repository
        and authority.digest == provenance.digest
        and authority.canonical_reference == provenance.canonical_reference
        and repo_digest_matches
        and image_architecture == provenance.image_architecture
        and server_architecture == provenance.server_architecture
        and canonical_image == provenance.canonical_image_architecture
        and canonical_server == provenance.canonical_server_architecture
        and not any(tag.startswith("repomap-") for tag in tags)
    )


def ledger_owns(ledger: ResourceLedger, kind: ResourceKind, identity: str) -> bool:
    try:
        record = ledger.get(kind, identity)
    except ResourceLedgerError:
        return False
    return (
        record.creation_observed
        and not record.created_before_run
        and record.cleanup_required
    )


def is_runtime_cache(
    item: DockerObject,
    fingerprint: str | None = None,
) -> bool:
    labels = item.labels
    references = tuple(item.references)
    return (
        labels.get(_MANAGED) == "true"
        and labels.get(_IMAGE_CLASS) == "runtime-cache"
        and labels.get(_IMAGE_SCHEMA) == "1"
        and labels.get(_REPOSITORY) == "repo-map"
        and (fingerprint is None or labels.get(_FINGERPRINT) == fingerprint)
        and bool(references)
        and all(reference.startswith("repomap-test-runtime:") for reference in references)
    )


def is_runtime_cache_gc_owned(
    item: DockerObject | None,
    fingerprint: str,
) -> bool:
    if item is None:
        return False
    labels = item.labels
    references = tuple(item.references)
    return (
        labels.get(_MANAGED) == "true"
        and labels.get(_IMAGE_CLASS) == "runtime-cache"
        and labels.get(_IMAGE_SCHEMA) == "1"
        and labels.get(_REPOSITORY) == "repo-map"
        and labels.get(_FINGERPRINT) == fingerprint
        and (
            not references
            or all(
                reference.startswith("repomap-test-runtime:")
                for reference in references
            )
        )
    )


def is_current_run_ephemeral(ledger: ResourceLedger, item: DockerObject) -> bool:
    labels = item.labels
    prefix = f"repomap-test-ephemeral:{ledger.identity.run_id}-"
    return (
        labels.get(_MANAGED) == "true"
        and labels.get(_IMAGE_CLASS) == "ephemeral"
        and labels.get(_IMAGE_SCHEMA) == "1"
        and labels.get(_REPOSITORY) == "repo-map"
        and labels.get(_RUN_ID) == ledger.identity.run_id
        and bool(item.references)
        and all(reference.startswith(prefix) for reference in item.references)
    )


__all__ = [
    "BoundaryView",
    "DockerClient",
    "cross_check",
    "is_current_run_ephemeral",
    "is_external_base",
    "is_runtime_cache",
    "is_runtime_cache_gc_owned",
    "ledger_owns",
]
