"""Run-wide Docker projection and retained operation evidence records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Mapping

from repomap_test_support.resource_docker_operations import (
    DERIVED_OPERATION_FIELDS,
    DockerOperationJournal,
)
from repomap_test_support.resource_docker_boundary_ownership import BoundaryView
from repomap_test_support.resource_ledger import ResourceKind


_KINDS = (ResourceKind.DOCKER_IMAGE, ResourceKind.DOCKER_VOLUME)
_UNATTRIBUTED_FIELDS = {
    ResourceKind.DOCKER_IMAGE: "new_unattributed_images",
    ResourceKind.DOCKER_VOLUME: "new_unattributed_volumes",
}
_CURRENT_RUN_FIELDS = {
    ResourceKind.DOCKER_IMAGE: "current_run_image_residue",
    ResourceKind.DOCKER_VOLUME: "current_run_volume_residue",
}
_INVENTORY_FIELDS = (
    "new_managed_external_test_base_images",
    "new_managed_test_runtime_cache_images",
    "new_unattributed_images",
    "new_unattributed_volumes",
    "current_run_ephemeral_image_residue",
    "current_run_image_residue",
    "current_run_volume_residue",
)
PROJECTION_FIELDS = (*DERIVED_OPERATION_FIELDS, *_INVENTORY_FIELDS)


ResidueErrorFactory = Callable[[str, dict[str, int]], RuntimeError]


def retain_operation_evidence(
    journal: DockerOperationJournal,
    evidence: Mapping[str, object],
    resource_run: object | None = None,
) -> Path:
    """Write the derivation beside the journal and retain both."""
    target = journal.path.with_name("docker-operation-derivation.json")
    payload = json.dumps(evidence, indent=1, sort_keys=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    # A run that recorded no operation never appends, so the journal file may
    # not exist yet. Retaining an empty journal records that observed population.
    if not journal.path.exists():
        os.close(
            os.open(
                journal.path,
                os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        )
    retain = getattr(resource_run, "retain_evidence", None)
    if callable(retain):
        retain(target, reason="diagnostic_evidence")
        retain(journal.path, reason="diagnostic_evidence")
    return target


def verify_terminal(
    boundary: BoundaryView,
    residue_error: ResidueErrorFactory,
) -> dict[str, int]:
    """Read exact terminal IDs; never remove or otherwise mutate them."""
    projection = boundary.projection()
    boundary._cross_check(projection)
    for kind in _KINDS:
        current = {item.identity: item for item in boundary.api.list_objects(kind)}
        expected = boundary.baseline.snapshots[kind]
        if any(
            current.get(identity) != item
            for identity, item in expected.items()
            if not (
                kind is ResourceKind.DOCKER_IMAGE
                and identity in boundary._removed_runtime_caches
            )
        ) or (
            kind is ResourceKind.DOCKER_IMAGE
            and any(identity in current for identity in boundary._removed_runtime_caches)
        ):
            boundary.ledger.set_fact("pre_existing_objects_mutated", True)
            raise residue_error("pre-existing Docker baseline changed", projection)
        for identity in sorted(set(current).difference(expected)):
            item = current[identity]
            fingerprint = boundary._managed_runtime_caches.get(identity)
            if (
                kind is ResourceKind.DOCKER_IMAGE
                and fingerprint is not None
                and boundary._is_runtime_cache(item, fingerprint)
            ):
                projection["new_managed_test_runtime_cache_images"] += 1
            elif (
                kind is ResourceKind.DOCKER_IMAGE
                and identity in boundary._managed_external_bases
                and boundary._is_external_base(
                    boundary._managed_external_bases[identity]
                )
            ):
                projection["new_managed_external_test_base_images"] += 1
            elif (
                kind is ResourceKind.DOCKER_IMAGE
                and boundary._ledger_owns(kind, identity)
                and boundary._is_current_run_ephemeral(item)
            ):
                projection["current_run_ephemeral_image_residue"] += 1
            elif boundary._ledger_owns(kind, identity):
                projection[_CURRENT_RUN_FIELDS[kind]] += 1
            else:
                projection[_UNATTRIBUTED_FIELDS[kind]] += 1
    boundary.ledger.set_fact("pre_existing_objects_mutated", False)
    if any(
        value
        for field, value in projection.items()
        if field
        not in {
            "managed_test_runtime_image_build_count",
            "managed_system_candidate_image_build_count",
            "managed_runtime_build_intermediate_created_count",
            "managed_runtime_build_intermediate_removed_count",
            "managed_external_base_pull_count",
            "new_managed_external_test_base_images",
            "new_managed_test_runtime_cache_images",
        }
    ):
        raise residue_error(
            "unattributed Docker residue or current-run Docker residue remains",
            projection,
        )
    return projection


__all__ = [
    "PROJECTION_FIELDS",
    "_INVENTORY_FIELDS",
    "_KINDS",
    "retain_operation_evidence",
    "verify_terminal",
]
