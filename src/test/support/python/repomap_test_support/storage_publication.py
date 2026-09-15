"""Receipt-bearing staged publication helpers for storage integration tests."""

from __future__ import annotations

from collections.abc import Sequence

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.storage import LoadSummary


def load_file_observations(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
    psql_command: str = "psql",
) -> LoadSummary:
    """Publish one complete public-safe fixture generation through staging."""

    return publish_observation_generation(
        psql_args,
        observations,
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        psql_command=psql_command,
    )


__all__ = ("load_file_observations",)
