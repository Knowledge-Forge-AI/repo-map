"""Pure observation fixtures without selected-class loading."""

from __future__ import annotations

from repomap_kg.observations.raw import RawObservation


def raw_observation(
    kind: str,
    *,
    path: str = "src/app.rb",
    name: str | None = None,
    target: str | None = None,
    metadata: dict | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{path}:{kind}:{name or 'anon'}",
        path=path,
        name=name,
        target=target,
        confidence="extracted",
        extractor="contract-test",
        extractor_version="0",
        metadata=metadata or {},
    )
