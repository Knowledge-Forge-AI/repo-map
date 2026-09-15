"""Shared support for canonical contract integration tests."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from repomap_kg.observations.raw import RawObservation


FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "canonicalization"
DISCOVERY_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "discovery"


def observations_by_kind(
    observations: tuple[RawObservation, ...],
) -> dict[str, list[RawObservation]]:
    grouped: dict[str, list[RawObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.kind, []).append(observation)
    return grouped


def odf_package(parts: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, payload in parts.items():
            package.writestr(name, payload)
    return buffer.getvalue()
