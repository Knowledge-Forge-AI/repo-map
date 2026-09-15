"""Repository-level Go context observations that do not parse source text."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Protocol, Sequence

from repomap_kg.observations.raw import RawObservation


EXTRACTOR = "repo-go-context"
EXTRACTOR_VERSION = "0.1.0"


class GoFileInfo(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def language(self) -> str: ...


def assembly_companion_observations(
    file_infos: Sequence[GoFileInfo],
    parsed_observations: Sequence[RawObservation],
) -> tuple[RawObservation, ...]:
    packages_by_directory: defaultdict[str, set[str]] = defaultdict(set)
    for observation in parsed_observations:
        if observation.kind != "go.package" or observation.metadata.get("test_file"):
            continue
        directory = str(PurePosixPath(observation.path).parent)
        packages_by_directory[directory].add(observation.name or "")

    observations: list[RawObservation] = []
    assembly_paths = sorted(
        file_info.path
        for file_info in file_infos
        if PurePosixPath(file_info.path).suffix.lower() == ".s"
    )
    for assembly_path in assembly_paths:
        directory = str(PurePosixPath(assembly_path).parent)
        package_names = sorted(packages_by_directory.get(directory, ()))
        for ordinal, package_name in enumerate(package_names):
            if not package_name:
                continue
            observations.append(
                RawObservation(
                    kind="go.assembly_companion",
                    source_id=(
                        f"{assembly_path}#go-assembly-companion:{ordinal}"
                    ),
                    path=assembly_path,
                    confidence="extracted",
                    extractor=EXTRACTOR,
                    extractor_version=EXTRACTOR_VERSION,
                    name=assembly_path,
                    metadata={
                        "package_name": package_name,
                        "resolution": "syntactic",
                        "assembly_parsed": False,
                        "static_only": True,
                        "code_executed": False,
                    },
                )
            )
    return tuple(observations)
