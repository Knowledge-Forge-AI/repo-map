"""Repository-level integration for the RepoMap-owned Go parser helper."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from repomap_kg.extractors.languages.go_protocol import (
    iter_go_protocol_observations,
    resolve_go_helper_command,
)
from repomap_kg.extractors.languages.go_repository_context import (
    assembly_companion_observations,
)
from repomap_kg.observations.raw import RawObservation


class GoFileInfo(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def language(self) -> str: ...


def extract_go_repository_observations(
    root: Path,
    file_infos: Sequence[GoFileInfo],
) -> tuple[RawObservation, ...]:
    relative_paths = tuple(
        sorted({file_info.path for file_info in file_infos if file_info.language == "go"})
    )
    if not relative_paths:
        return ()
    command = resolve_go_helper_command()
    parsed = tuple(iter_go_protocol_observations(root, relative_paths, command))
    return parsed + assembly_companion_observations(file_infos, parsed)
