"""Raw observation JSONL schema and helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


SCHEMA_VERSION = 1
VALID_CONFIDENCES = frozenset({"extracted", "heuristic", "manual", "unknown"})


class ObservationValidationError(ValueError):
    """Raised when a raw observation does not match the schema."""


@dataclass(frozen=True)
class RawObservation:
    kind: str
    source_id: str
    path: str
    confidence: str
    extractor: str
    extractor_version: str
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None
    target: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = {
            "kind": self.kind,
            "source_id": self.source_id,
            "path": self.path,
            "confidence": self.confidence,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
        }
        for field_name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ObservationValidationError(f"{field_name} is required")
        if self.schema_version != SCHEMA_VERSION:
            raise ObservationValidationError(
                f"schema_version must be {SCHEMA_VERSION}"
            )
        if self.confidence not in VALID_CONFIDENCES:
            values = ", ".join(sorted(VALID_CONFIDENCES))
            raise ObservationValidationError(
                f"confidence must be one of: {values}"
            )
        if not isinstance(self.metadata, Mapping):
            raise ObservationValidationError("metadata must be an object")
        self._validate_line_range()

    def _validate_line_range(self) -> None:
        if self.start_line is None and self.end_line is None:
            return
        if self.start_line is None or self.end_line is None:
            raise ObservationValidationError(
                "line range must include start_line and end_line"
            )
        if not isinstance(self.start_line, int):
            raise ObservationValidationError("start_line must be an integer")
        if not isinstance(self.end_line, int):
            raise ObservationValidationError("end_line must be an integer")
        if self.start_line < 1 or self.end_line < 1:
            raise ObservationValidationError("line range must use positive lines")
        if self.end_line < self.start_line:
            raise ObservationValidationError(
                "line range end_line must not be before start_line"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_id": self.source_id,
            "path": self.path,
            "confidence": self.confidence,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "metadata": dict(self.metadata),
        }
        optional = {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "name": self.name,
            "target": self.target,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value
        return payload

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True) + "\n"

    @classmethod
    def from_json_line(
        cls, json_line: str, *, line_number: int | None = None
    ) -> RawObservation:
        try:
            payload = json.loads(json_line)
        except json.JSONDecodeError as error:
            prefix = f"line {line_number}: " if line_number is not None else ""
            raise ObservationValidationError(
                f"{prefix}invalid JSON: {error.msg}"
            ) from error
        try:
            return cls.from_dict(payload)
        except ObservationValidationError as error:
            prefix = f"line {line_number}: " if line_number is not None else ""
            raise ObservationValidationError(f"{prefix}{error}") from error

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RawObservation:
        if not isinstance(payload, Mapping):
            raise ObservationValidationError("observation must be an object")
        fields = {
            "kind": require(payload, "kind"),
            "source_id": require(payload, "source_id"),
            "path": require(payload, "path"),
            "confidence": require(payload, "confidence"),
            "extractor": require(payload, "extractor"),
            "extractor_version": require(payload, "extractor_version"),
            "schema_version": payload.get("schema_version", SCHEMA_VERSION),
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
            "name": payload.get("name"),
            "target": payload.get("target"),
            "metadata": payload.get("metadata", {}),
        }
        return cls(**fields)


def require(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload:
        raise ObservationValidationError(f"{key} is required")
    return payload[key]


def read_observations_jsonl(path_or_file: Path | str | TextIO) -> list[RawObservation]:
    if isinstance(path_or_file, (str, Path)):
        with Path(path_or_file).open(encoding="utf-8") as handle:
            return _read_observations_lines(handle)
    return _read_observations_lines(path_or_file)


def _read_observations_lines(handle: TextIO) -> list[RawObservation]:
    observations = []
    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        observations.append(RawObservation.from_json_line(line, line_number=line_number))
    return observations


def write_observations_jsonl(
    observations: Iterable[RawObservation], path_or_file: Path | str | TextIO
) -> None:
    if isinstance(path_or_file, (str, Path)):
        with Path(path_or_file).open("w", encoding="utf-8") as handle:
            _write_observations_lines(observations, handle)
        return
    _write_observations_lines(observations, path_or_file)


def _write_observations_lines(
    observations: Iterable[RawObservation], handle: TextIO
) -> None:
    for observation in observations:
        handle.write(observation.to_json_line())
