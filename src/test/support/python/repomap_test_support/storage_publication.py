"""Receipt-bearing staged publication helpers for storage integration tests."""

from __future__ import annotations

from collections.abc import Sequence

from common_lore_index.observations.raw import RawObservation
from common_lore_index.ops.direct_publication import publish_observation_generation
from common_lore_index.storage import LoadSummary


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
