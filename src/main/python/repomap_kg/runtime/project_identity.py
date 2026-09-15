"""Stable project identity metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProjectIdentity:
    name: str
    distribution: str
    package: str
    cli: str
    license: str
    database: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


PROJECT_IDENTITY = ProjectIdentity(
    name="RepoMap",
    distribution="repomap-kg",
    package="repomap_kg",
    cli="repomap-kg",
    license="Apache-2.0",
    database="Postgres",
)
