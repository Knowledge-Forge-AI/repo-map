"""Stable project identity metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from repomap_kg import DISTRIBUTION_NAME, IMPORT_PACKAGE, PREFERRED_CLI


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
    distribution=DISTRIBUTION_NAME,
    package=IMPORT_PACKAGE,
    cli=PREFERRED_CLI,
    license="AGPL-3.0-or-later",
    database="Postgres",
)
