from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from docker import DockerClient
from docker.models.images import Image
from repomap_test_support.resource_ledger import ResourceLedger
from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary

from repomap_test_support.resource_test_image_record_types import RuntimeIdentityFields
from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_test_image_base import (
    BaseImageProvenance, ImmutableImageAuthority,
    TestImageError,
    normalize_architecture_pair,
    parse_immutable_image_authority,
)
from repomap_test_support.resource_test_image_identity import (
    canonical_runtime_fingerprint,
    canonical_runtime_json,
)

DEPLOYMENT_IMAGE_PREFIX = "repomap-runtime:"
RUNTIME_CACHE_IMAGE_PREFIX = "repomap-test-runtime:"
EPHEMERAL_IMAGE_PREFIX = "repomap-test-ephemeral:"
RUNTIME_CACHE_RETENTION = 2
LIFECYCLE_LOCK_DIRECTORY = "locks"
IMAGE_RECIPE_SCHEMA = 1
RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA = 2

_LABEL_MANAGED = "org.repomap.test.managed"
_LABEL_CLASS = "org.repomap.test.image.class"
_LABEL_SCHEMA = "org.repomap.test.image.schema"
_LABEL_FINGERPRINT = "org.repomap.test.runtime-fingerprint"
_LABEL_RUN_ID = "org.repomap.test.run-id"
_LABEL_REPOSITORY = "org.repomap.test.repository"
_REPOSITORY = "repo-map"
_LEGACY_TAG = re.compile(r"^repomap-runtime-[^:]+:latest$")
_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TRANSIENT_RESOURCE_LABEL_KEYS = frozenset({
    "org.repomap.test.resource.phase", "org.repomap.test.resource.project",
    "org.repomap.test.resource.retention", "org.repomap.test.resource.role",
    "org.repomap.test.resource.run_id",
})


@dataclass(frozen=True)
class RuntimeIdentity:
    fingerprint: str
    canonical_json: str
    fields: RuntimeIdentityFields


@dataclass(frozen=True)
class TestImageRecord:
    image_id: str
    tags: tuple[str, ...]
    labels: Mapping[str, str]
    created: str
    size: int
    container_references: tuple[str, ...]


@dataclass(frozen=True)
class TestImageInventory:
    runtime_cache: tuple[TestImageRecord, ...]
    runtime_cache_orphans: tuple[TestImageRecord, ...]
    ephemeral: tuple[TestImageRecord, ...]
    legacy_unclassified: tuple[TestImageRecord, ...]
    ownership_ambiguous: tuple[TestImageRecord, ...]


def exact_image_id(identity: object) -> str:
    identity = str(identity)
    if not _SHA256_ID.fullmatch(identity):
        raise TestImageError("Docker Engine image ID is not exact")
    return identity


def runtime_labels(fingerprint: str) -> dict[str, str]:
    return {
        _LABEL_MANAGED: "true", _LABEL_CLASS: "runtime-cache",
        _LABEL_SCHEMA: "1", _LABEL_FINGERPRINT: fingerprint,
        _LABEL_REPOSITORY: _REPOSITORY,
    }


def runtime_labels_are_exact(labels: Mapping[str, str], fingerprint: str) -> bool:
    return dict(labels) == runtime_labels(fingerprint)


def ephemeral_labels(run_id: str) -> dict[str, str]:
    return {
        _LABEL_MANAGED: "true", _LABEL_CLASS: "ephemeral",
        _LABEL_SCHEMA: "1", _LABEL_RUN_ID: run_id,
        _LABEL_REPOSITORY: _REPOSITORY,
    }


def runtime_namespace_is_exact(record: TestImageRecord) -> bool:
    return bool(record.tags) and all(tag.startswith(RUNTIME_CACHE_IMAGE_PREFIX) for tag in record.tags)


def ephemeral_namespace_is_exact(record: TestImageRecord, run_id: str) -> bool:
    prefix = f"{EPHEMERAL_IMAGE_PREFIX}{run_id}-"
    return bool(record.tags) and all(tag.startswith(prefix) for tag in record.tags)


def derive_runtime_tag(architecture_observed: str, python_version: str, fingerprint: str) -> str:
    architecture, _ = normalize_architecture_pair(architecture_observed, architecture_observed)
    architecture = re.sub(r"[^a-z0-9_.-]", "-", architecture.lower())
    version = "".join(python_version.split(".")[:2])
    return f"{RUNTIME_CACHE_IMAGE_PREFIX}py{version}-{architecture}-{fingerprint[:12]}"


def read_project_runtime_dependencies(repo_root: Path, psycopg_release_version: str) -> tuple[str, ...]:
    path = repo_root / "pyproject.toml"
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise TestImageError("project runtime dependencies are unavailable") from error
    if "dependencies" in tuple(project.get("dynamic") or ()):
        raise TestImageError("dynamic project dependencies are not authorized")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies or not all(
        isinstance(item, str) and item.strip() for item in dependencies
    ):
        raise TestImageError("project runtime dependencies are not deterministic")
    normalized = tuple(sorted(item.strip() for item in dependencies))
    if not any(f"=={psycopg_release_version}" in item for item in normalized):
        raise TestImageError("Psycopg release input does not match project dependencies")
    return normalized


def create_runtime_identity(
    *,
    dependencies: tuple[str, ...],
    base: Image,
    base_provenance: BaseImageProvenance,
    base_authority: ImmutableImageAuthority,
    base_reference: str,
    python_base_family: str,
    python_version: str,
    psycopg_release_version: str,
    recipe_schema: int,
    runtime_extras: tuple[str, ...],
) -> RuntimeIdentity:
    architecture = base_provenance.canonical_server_architecture
    repo_digests = tuple(sorted(str(item) for item in base.attrs.get("RepoDigests") or ()))
    fields: RuntimeIdentityFields = {
        "architecture": architecture,
        "base_image_id": exact_image_id(base.id),
        "base_reference": base_reference,
        "base_canonical_reference": base_authority.canonical_reference,
        "base_repo_digests": repo_digests,
        "lock_resolution_input": None,
        "project_runtime_dependencies": dependencies,
        "psycopg_release_version": psycopg_release_version,
        "python_base_family": python_base_family,
        "python_version": python_version,
        "recipe_schema": recipe_schema,
        "runtime_extras": runtime_extras,
    }
    canonical_json = canonical_runtime_json(fields)
    return RuntimeIdentity(
        fingerprint=canonical_runtime_fingerprint(fields),
        canonical_json=canonical_json,
        fields=fields,
    )


def validate_manager_configuration(
    resource_run: object, base_reference: str, python_base_family: str, recipe_schema: int
) -> tuple[ResourceLedger, ImmutableImageAuthority]:
    ledger: ResourceLedger | None = getattr(resource_run, "ledger", None)
    if ledger is None:
        raise TestImageError("managed resource ledger is required")
    base_authority = parse_immutable_image_authority(base_reference)
    configured_family = base_authority.repository
    if base_authority.optional_tag is not None:
        configured_family = f"{configured_family}:{base_authority.optional_tag}"
    if configured_family != python_base_family:
        raise TestImageError("configured runtime base does not match its exact family")
    if recipe_schema not in {IMAGE_RECIPE_SCHEMA, RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA}:
        raise TestImageError("runtime recipe schema is not repository-owned")
    return ledger, base_authority


def populate_runtime_manager_evidence(
    evidence: dict[str, object],
    *,
    outcome: str,
    selected_image_id: str,
    duplicates: Sequence[str],
    gc_removed: Sequence[str],
    gc_deferred_in_use: Sequence[str],
    intermediates: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    materialization_evidence: Mapping[str, object] | None,
    boundary: RunWideDockerBoundary | None,
) -> None:
    created, removed, terminal = intermediates
    evidence.update(
        outcome=outcome,
        selected_image_id=selected_image_id,
        duplicate_image_ids=sorted(duplicates),
        gc_removed=list(gc_removed),
        gc_deferred_in_use=list(gc_deferred_in_use),
        builder_materialization="container-commit-v1",
        runtime_build_intermediate_created_ids=list(created),
        runtime_build_intermediate_removed_ids=list(removed),
        runtime_build_intermediate_terminal_ids=list(terminal),
        runtime_build_intermediate_created_count=len(created),
        runtime_build_intermediate_removed_count=len(removed),
        runtime_build_intermediate_residue_count=len(terminal),
    )
    if outcome == "built" and materialization_evidence is not None:
        evidence["materialization"] = dict(materialization_evidence)
    if boundary is not None:
        boundary.record_manager_evidence(evidence)


def record_materialization_failure(evidence: dict[str, object], error: Exception) -> bool:
    failure = getattr(error, "materialization_evidence", None)
    evidence.update(outcome="failed", error_type=type(error).__name__, error_message=str(error))
    if isinstance(failure, Mapping):
        evidence["materialization_failure"] = dict(failure)
        return False
    if str(error) == "managed runtime image materialization failed":
        evidence["materialization_failure_status"] = "rejected_opaque"
        return True
    return False


def build_test_image_record(image: Image, container_references: Iterable[str]) -> TestImageRecord:
    image_id = exact_image_id(image.id)
    return TestImageRecord(
        image_id=image_id,
        tags=tuple(sorted(str(tag) for tag in image.tags)),
        labels=dict(image.attrs.get("Config", {}).get("Labels") or {}),
        created=str(image.attrs.get("Created") or ""),
        size=int(image.attrs.get("Size") or 0),
        container_references=tuple(sorted(container_references)),
    )


def fetch_test_image_record(client: DockerClient, api: DockerSdkApi, image_id: str) -> TestImageRecord:
    image = client.images.get(image_id)
    return build_test_image_record(image, api.image_references(exact_image_id(image.id)))


def require_runtime_record(client: DockerClient, api: DockerSdkApi, image_id: str, fingerprint: str) -> TestImageRecord:
    record = fetch_test_image_record(client, api, image_id)
    if not runtime_namespace_is_exact(record):
        if any(tag.startswith(DEPLOYMENT_IMAGE_PREFIX) for tag in record.tags):
            raise TestImageError("managed test image has a deployment tag")
        raise TestImageError("runtime cache ownership ambiguity")
    if not runtime_labels_are_exact(record.labels, fingerprint):
        raise TestImageError("runtime cache ownership ambiguity")
    return record


def require_gc_owned_runtime_record(client: DockerClient, api: DockerSdkApi, image_id: str, fingerprint: str) -> TestImageRecord:
    record = fetch_test_image_record(client, api, image_id)
    if record.tags and not runtime_namespace_is_exact(record):
        if any(tag.startswith(DEPLOYMENT_IMAGE_PREFIX) for tag in record.tags):
            raise TestImageError("managed test image has a deployment tag")
        raise TestImageError("runtime cache GC ownership ambiguity")
    if not runtime_labels_are_exact(record.labels, fingerprint):
        raise TestImageError("runtime cache GC ownership ambiguity")
    return record


def require_ephemeral_record(client: DockerClient, api: DockerSdkApi, image_id: str, run_id: str) -> TestImageRecord:
    record = fetch_test_image_record(client, api, image_id)
    labels = record.labels
    if (
        labels.get(_LABEL_MANAGED) != "true"
        or labels.get(_LABEL_CLASS) != "ephemeral"
        or labels.get(_LABEL_SCHEMA) != "1"
        or labels.get(_LABEL_REPOSITORY) != _REPOSITORY
        or labels.get(_LABEL_RUN_ID) != run_id
        or not ephemeral_namespace_is_exact(record, run_id)
    ):
        raise TestImageError("ephemeral image ownership ambiguity")
    return record


def scan_test_image_inventory(
    images: Sequence[Image],
    run_id: str,
    image_references_fn: Callable[[str], Iterable[str]],
) -> TestImageInventory:
    runtime_cache: list[TestImageRecord] = []
    runtime_cache_orphans: list[TestImageRecord] = []
    ephemeral: list[TestImageRecord] = []
    legacy: list[TestImageRecord] = []
    ambiguous: list[TestImageRecord] = []
    for image in images:
        record = build_test_image_record(image, image_references_fn(exact_image_id(image.id)))
        labels = record.labels
        if any(_LEGACY_TAG.fullmatch(tag) for tag in record.tags):
            legacy.append(record)
        if labels.get(_LABEL_MANAGED) != "true":
            if any(tag.startswith((RUNTIME_CACHE_IMAGE_PREFIX, EPHEMERAL_IMAGE_PREFIX)) for tag in record.tags):
                ambiguous.append(record)
            continue
        if labels.get(_LABEL_REPOSITORY) != _REPOSITORY or labels.get(_LABEL_SCHEMA) != "1":
            ambiguous.append(record)
            continue
        image_class = labels.get(_LABEL_CLASS)
        if image_class == "runtime-cache":
            fingerprint = str(labels.get(_LABEL_FINGERPRINT) or "")
            if runtime_namespace_is_exact(record) and runtime_labels_are_exact(labels, fingerprint):
                runtime_cache.append(record)
            elif not record.tags and runtime_labels_are_exact(labels, fingerprint):
                runtime_cache_orphans.append(record)
            else:
                ambiguous.append(record)
        elif image_class == "ephemeral" and ephemeral_namespace_is_exact(record, run_id):
            ephemeral.append(record)
        else:
            ambiguous.append(record)
    key = lambda item: (item.created, item.image_id)
    return TestImageInventory(
        runtime_cache=tuple(sorted(runtime_cache, key=key)),
        runtime_cache_orphans=tuple(sorted(runtime_cache_orphans, key=key)),
        ephemeral=tuple(sorted(ephemeral, key=key)),
        legacy_unclassified=tuple(sorted(legacy, key=key)),
        ownership_ambiguous=tuple(sorted({item.image_id: item for item in ambiguous}.values(), key=key)),
    )


def scan_legacy_inventory(
    images: Sequence[Image],
    image_references_fn: Callable[[str], Iterable[str]],
) -> tuple[TestImageRecord, ...]:
    records: list[TestImageRecord] = []
    for image in images:
        tags = tuple(sorted(str(tag) for tag in image.tags))
        if not any(_LEGACY_TAG.fullmatch(tag) for tag in tags):
            continue
        image_id = exact_image_id(image.id)
        records.append(
            TestImageRecord(
                image_id=image_id,
                tags=tags,
                labels=dict(image.attrs.get("Config", {}).get("Labels") or {}),
                created=str(image.attrs.get("Created") or ""),
                size=int(image.attrs.get("Size") or 0),
                container_references=tuple(sorted(image_references_fn(image_id))),
            )
        )
    return tuple(sorted(records, key=lambda item: (item.created, item.image_id)))


__all__ = [
    "DEPLOYMENT_IMAGE_PREFIX",
    "EPHEMERAL_IMAGE_PREFIX",
    "IMAGE_RECIPE_SCHEMA",
    "LIFECYCLE_LOCK_DIRECTORY",
    "RUNTIME_CACHE_IMAGE_PREFIX",
    "RUNTIME_CACHE_RETENTION",
    "RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA",
    "RuntimeIdentity",
    "TestImageInventory",
    "TestImageRecord",
    "build_test_image_record",
    "create_runtime_identity",
    "derive_runtime_tag",
    "ephemeral_labels",
    "ephemeral_namespace_is_exact",
    "exact_image_id",
    "fetch_test_image_record",
    "populate_runtime_manager_evidence",
    "read_project_runtime_dependencies",
    "record_materialization_failure",
    "require_ephemeral_record",
    "require_gc_owned_runtime_record",
    "require_runtime_record",
    "runtime_labels",
    "runtime_labels_are_exact",
    "runtime_namespace_is_exact",
    "scan_legacy_inventory",
    "scan_test_image_inventory",
    "validate_manager_configuration",
]
