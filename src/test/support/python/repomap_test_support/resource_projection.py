"""Identifier-free public count projection for private resource records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from repomap_test_support.resource_validation import HygieneValidationError, exact_bool


COUNT_FIELDS = {
    "process": ("phase_processes_created", "phase_processes_remaining"),
    "unix_socket": ("phase_sockets_created", "phase_sockets_remaining"),
    "tcp_port": ("phase_ports_created", "phase_ports_remaining"),
    "postgres_cluster": (
        "phase_postgres_clusters_created",
        "phase_postgres_clusters_remaining",
    ),
    "docker_container": ("phase_containers_created", "phase_containers_remaining"),
    "docker_image": ("phase_images_created", "phase_images_remaining"),
    "docker_tag": ("phase_tags_created", "phase_tags_remaining"),
    "docker_network": ("phase_networks_created", "phase_networks_remaining"),
    "docker_volume": ("phase_volumes_created", "phase_volumes_remaining"),
    "buildx_builder": ("phase_builders_created", "phase_builders_remaining"),
    "buildkit_state_volume": (
        "phase_buildkit_state_volumes_created",
        "phase_buildkit_state_volumes_remaining",
    ),
    "build_history_record": (
        "phase_build_history_created",
        "phase_build_history_remaining",
    ),
}
MUTATION_FACTS = {"pre_existing_objects_mutated", "foreign_scratch_runs_mutated"}


class ResourceProjectionError(RuntimeError):
    """Private authority cannot be represented by the closed public schema."""


def resource_count_projection(
    records: Iterable[Any],
    facts: Mapping[str, bool],
) -> dict[str, int | bool | str]:
    if set(facts) - MUTATION_FACTS:
        raise ResourceProjectionError("unknown public mutation fact")
    try:
        projected_facts = {name: exact_bool(value, name) for name, value in facts.items()}
    except HygieneValidationError as error:
        raise ResourceProjectionError("invalid public mutation fact") from error
    projection: dict[str, int | bool | str] = {
        field: 0 for fields in COUNT_FIELDS.values() for field in fields
    }
    for record in records:
        fields = COUNT_FIELDS.get(record.kind.value)
        try:
            created_before_run = exact_bool(
                record.created_before_run, "created_before_run"
            )
            creation_observed = exact_bool(
                record.creation_observed, "creation_observed"
            )
            retained = exact_bool(record.retained, "retained")
        except (AttributeError, HygieneValidationError) as error:
            raise ResourceProjectionError("invalid public resource record") from error
        if fields is None or created_before_run or not creation_observed:
            continue
        created_field, remaining_field = fields
        projection[created_field] = int(projection[created_field]) + 1
        if not retained and record.final_presence.value != "absent":
            projection[remaining_field] = int(projection[remaining_field]) + 1
    projection["pre_existing_objects_mutated"] = projected_facts.get(
        "pre_existing_objects_mutated", "unobserved"
    )
    projection["foreign_scratch_runs_mutated"] = projected_facts.get(
        "foreign_scratch_runs_mutated", "unobserved"
    )
    return projection


__all__ = ["COUNT_FIELDS", "ResourceProjectionError", "resource_count_projection"]
