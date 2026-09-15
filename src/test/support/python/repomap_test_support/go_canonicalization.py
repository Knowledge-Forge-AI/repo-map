"""Public-safe observation builders for Go canonicalization tests."""

from collections.abc import Mapping
from typing import Any

from repomap_kg.observations.raw import RawObservation


def observation(
    kind: str,
    path: str,
    *,
    name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    start_line: int = 1,
    source_suffix: str | None = None,
    source_id: str | None = None,
) -> RawObservation:
    suffix = source_suffix or f"{kind}:{start_line}:{name or 'unnamed'}"
    return RawObservation(
        kind=kind,
        source_id=source_id or f"{path}#{suffix}",
        path=path,
        confidence="extracted",
        extractor="go9-boundary-fixture",
        extractor_version="0.1.0",
        start_line=start_line,
        end_line=start_line,
        name=name,
        metadata=dict(metadata or {}),
    )


def file_observation(path: str) -> RawObservation:
    return observation(
        "file",
        path,
        name=path,
        metadata={"language": "go", "role": "source", "generated": False},
    )


def package_observation(
    path: str,
    package_name: str,
    *,
    vendor: bool = False,
) -> RawObservation:
    return observation(
        "go.package",
        path,
        name=package_name,
        metadata={
            "package_name": package_name,
            "external_test_package": False,
            "test_file": False,
            "generated": False,
            "vendor": vendor,
        },
    )


def accounting(result: Any) -> Mapping[str, int]:
    record = next(
        item for item in result.diagnostics if item.category == "go_canonical_accounting"
    )
    assert isinstance(record.value, Mapping)
    return record.value
