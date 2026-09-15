"""Strict private SCALE20 prelaunch result transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any

from repomap_kg.storage.authority import PublicationGenerations
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
    FINAL_FAMILY_CODES,
)


PRELAUNCH_RESULT_SCHEMA_VERSION = 1
MAX_PRELAUNCH_RESULT_BYTES = 64 * 1024
MAX_FAMILY_ROW_COUNT = 2**63 - 1

_FAMILY_RECORD_FIELDS = frozenset({"family_code", "row_count"})
_GENERATION_FIELDS = frozenset(PublicationGenerations.field_names())
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "category",
        "repository_identity",
        "repository_name",
        "generations",
        "execution_mode",
        "zero_state_first_publication",
        "family_counts",
        "structural_digest",
    }
)


class PrelaunchHandoffError(ValueError):
    """Bounded public-safe private handoff failure."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class FinalFamilyCountRecord:
    """One typed final-family count in the private wire sequence."""

    family_code: str
    row_count: int

    def validate(self) -> FinalFamilyCountRecord:
        if (
            not isinstance(self.family_code, str)
            or isinstance(self.row_count, bool)
            or not isinstance(self.row_count, int)
            or not 0 <= self.row_count <= MAX_FAMILY_ROW_COUNT
        ):
            raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
        return self


@dataclass(frozen=True)
class OrderedFinalFamilyCounts:
    """Immutable final-family counts in exact typed order."""

    records: tuple[FinalFamilyCountRecord, ...]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> OrderedFinalFamilyCounts:
        if (
            not isinstance(self.records, tuple)
            or len(self.records) != len(FINAL_FAMILY_CODES)
        ):
            raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
        for expected_code, record in zip(
            FINAL_FAMILY_CODES,
            self.records,
            strict=True,
        ):
            if not isinstance(record, FinalFamilyCountRecord):
                raise PrelaunchHandoffError(
                    "prelaunch_result.family_counts_invalid"
                )
            record.validate()
            if record.family_code != expected_code:
                raise PrelaunchHandoffError(
                    "prelaunch_result.family_counts_invalid"
                )
        return self

    @classmethod
    def from_mapping(
        cls,
        counts: Mapping[object, object],
    ) -> OrderedFinalFamilyCounts:
        if not isinstance(counts, Mapping) or tuple(counts) != FINAL_FAMILY_CODES:
            raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
        records: list[FinalFamilyCountRecord] = []
        for family_code in FINAL_FAMILY_CODES:
            row_count = counts[family_code]
            if isinstance(row_count, bool) or not isinstance(row_count, int):
                raise PrelaunchHandoffError(
                    "prelaunch_result.family_counts_invalid"
                )
            records.append(FinalFamilyCountRecord(family_code, row_count))
        return cls(tuple(records))

    @classmethod
    def from_payload(cls, payload: object) -> OrderedFinalFamilyCounts:
        if not isinstance(payload, list):
            raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
        records: list[FinalFamilyCountRecord] = []
        for item in payload:
            if not isinstance(item, Mapping) or frozenset(item) != _FAMILY_RECORD_FIELDS:
                raise PrelaunchHandoffError(
                    "prelaunch_result.family_counts_invalid"
                )
            records.append(
                FinalFamilyCountRecord(
                    item["family_code"],
                    item["row_count"],
                )
            )
        return cls(tuple(records))

    def to_payload(self) -> list[dict[str, object]]:
        return [
            {
                "family_code": record.family_code,
                "row_count": record.row_count,
            }
            for record in self.records
        ]

    def to_mapping(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                record.family_code: record.row_count
                for record in self.records
            }
        )


@dataclass(frozen=True)
class ProtectedPrelaunchResult:
    """Closed private expectation result accepted before child creation."""

    category: str
    repository_identity: str
    repository_name: str
    generations: PublicationGenerations
    execution_mode: str
    zero_state_first_publication: bool
    family_counts: OrderedFinalFamilyCounts
    structural_digest: str

    def validate(self) -> ProtectedPrelaunchResult:
        if self.category != "complete":
            raise PrelaunchHandoffError("prelaunch_result.category_invalid")
        if (
            not isinstance(self.repository_identity, str)
            or not isinstance(self.repository_name, str)
            or not isinstance(self.generations, PublicationGenerations)
            or not isinstance(self.execution_mode, str)
            or not isinstance(self.zero_state_first_publication, bool)
            or not isinstance(self.structural_digest, str)
        ):
            raise PrelaunchHandoffError("prelaunch_result.invalid")
        if not isinstance(self.family_counts, OrderedFinalFamilyCounts):
            raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
        self.family_counts.validate()
        try:
            self.to_expected_refresh_authority().validate()
        except (TypeError, ValueError) as error:
            raise PrelaunchHandoffError("prelaunch_result.invalid") from error
        return self

    def to_expected_refresh_authority(self) -> ExpectedRefreshAuthority:
        return ExpectedRefreshAuthority(
            repository_identity=self.repository_identity,
            repository_name=self.repository_name,
            generations=self.generations,
            execution_mode=self.execution_mode,
            zero_state_first_publication=self.zero_state_first_publication,
            expected_family_counts=self.family_counts.to_mapping(),
            expected_structural_digest=self.structural_digest,
        )

    def to_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": PRELAUNCH_RESULT_SCHEMA_VERSION,
            "category": self.category,
            "repository_identity": self.repository_identity,
            "repository_name": self.repository_name,
            "generations": {
                field: getattr(self.generations, field)
                for field in PublicationGenerations.field_names()
            },
            "execution_mode": self.execution_mode,
            "zero_state_first_publication": self.zero_state_first_publication,
            "family_counts": self.family_counts.to_payload(),
            "structural_digest": self.structural_digest,
        }


def encode_prelaunch_result(result: ProtectedPrelaunchResult) -> bytes:
    """Encode one complete result with deterministic outer key sorting."""

    if not isinstance(result, ProtectedPrelaunchResult):
        raise PrelaunchHandoffError("prelaunch_result.invalid")
    encoded = json.dumps(
        result.to_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_PRELAUNCH_RESULT_BYTES:
        raise PrelaunchHandoffError("prelaunch_result.oversized")
    return encoded


def decode_prelaunch_result(payload: bytes | str) -> ProtectedPrelaunchResult:
    """Decode and validate one closed complete private result."""

    decoded = _decode_json_object(payload)
    if frozenset(decoded) != _RESULT_FIELDS:
        raise PrelaunchHandoffError("prelaunch_result.fields_invalid")
    schema_version = decoded["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != PRELAUNCH_RESULT_SCHEMA_VERSION
    ):
        raise PrelaunchHandoffError("prelaunch_result.schema_unsupported")
    if decoded["category"] != "complete":
        raise PrelaunchHandoffError("prelaunch_result.category_invalid")
    category = decoded["category"]
    repository_identity = decoded["repository_identity"]
    repository_name = decoded["repository_name"]
    execution_mode = decoded["execution_mode"]
    zero_state = decoded["zero_state_first_publication"]
    structural_digest = decoded["structural_digest"]
    if (
        not isinstance(category, str)
        or not isinstance(repository_identity, str)
        or not isinstance(repository_name, str)
        or not isinstance(execution_mode, str)
        or not isinstance(zero_state, bool)
        or not isinstance(structural_digest, str)
    ):
        raise PrelaunchHandoffError("prelaunch_result.invalid")
    generations_payload = decoded["generations"]
    if (
        not isinstance(generations_payload, Mapping)
        or frozenset(generations_payload) != _GENERATION_FIELDS
    ):
        raise PrelaunchHandoffError("prelaunch_result.fields_invalid")
    generation_values = tuple(
        generations_payload[field]
        for field in PublicationGenerations.field_names()
    )
    if any(not isinstance(value, str) for value in generation_values):
        raise PrelaunchHandoffError("prelaunch_result.invalid")
    try:
        generations = PublicationGenerations(*generation_values)
        result = ProtectedPrelaunchResult(
            category=category,
            repository_identity=repository_identity,
            repository_name=repository_name,
            generations=generations,
            execution_mode=execution_mode,
            zero_state_first_publication=zero_state,
            family_counts=OrderedFinalFamilyCounts.from_payload(
                decoded["family_counts"]
            ),
            structural_digest=structural_digest,
        )
    except PrelaunchHandoffError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise PrelaunchHandoffError("prelaunch_result.invalid") from error
    return result.validate()


def receive_prelaunch_result(
    *,
    returncode: int,
    stdout: bytes | str,
    cancellation_check: Callable[[], None] | None = None,
) -> ProtectedPrelaunchResult:
    """Accept one settled worker result without accepting partial authority."""

    if isinstance(returncode, bool) or not isinstance(returncode, int):
        raise PrelaunchHandoffError("prelaunch_worker.invalid_state")
    _check_handoff_cancellation(cancellation_check)
    if returncode != 0:
        raise PrelaunchHandoffError("prelaunch_worker.failed")
    if not stdout or not stdout.strip():
        raise PrelaunchHandoffError("prelaunch_worker.result_missing")
    result = decode_prelaunch_result(stdout)
    _check_handoff_cancellation(cancellation_check)
    return result


def encode_ordered_family_worker_payload(payload: Mapping[str, object]) -> str:
    """Encode an internal worker payload with ordered family records."""

    if not isinstance(payload, Mapping) or "family_counts" not in payload:
        raise PrelaunchHandoffError("prelaunch_result.fields_invalid")
    family_counts = payload["family_counts"]
    if not isinstance(family_counts, Mapping):
        raise PrelaunchHandoffError("prelaunch_result.family_counts_invalid")
    counts = OrderedFinalFamilyCounts.from_mapping(family_counts)
    wire_payload = dict(payload)
    wire_payload["family_counts"] = counts.to_payload()
    encoded = json.dumps(
        wire_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > MAX_PRELAUNCH_RESULT_BYTES:
        raise PrelaunchHandoffError("prelaunch_result.oversized")
    return encoded


def decode_ordered_family_worker_payload(
    payload: bytes | str,
) -> dict[str, object]:
    """Decode an internal worker payload and restore typed mapping order."""

    decoded = _decode_json_object(payload)
    if "family_counts" not in decoded:
        raise PrelaunchHandoffError("prelaunch_result.fields_invalid")
    counts = OrderedFinalFamilyCounts.from_payload(decoded["family_counts"])
    decoded["family_counts"] = dict(counts.to_mapping())
    return decoded


def _decode_json_object(payload: bytes | str) -> dict[str, object]:
    if isinstance(payload, bytes):
        encoded = payload
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PrelaunchHandoffError("prelaunch_result.invalid_json") from error
    elif isinstance(payload, str):
        text = payload
        encoded = payload.encode("utf-8")
    else:
        raise PrelaunchHandoffError("prelaunch_result.invalid_json")
    if len(encoded) > MAX_PRELAUNCH_RESULT_BYTES:
        raise PrelaunchHandoffError("prelaunch_result.oversized")
    try:
        decoded = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except PrelaunchHandoffError:
        raise
    except json.JSONDecodeError as error:
        raise PrelaunchHandoffError("prelaunch_result.invalid_json") from error
    if not isinstance(decoded, dict):
        raise PrelaunchHandoffError("prelaunch_result.fields_invalid")
    return decoded


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            raise PrelaunchHandoffError("prelaunch_result.duplicate_key")
        decoded[key] = value
    return decoded


def _check_handoff_cancellation(
    cancellation_check: Callable[[], None] | None,
) -> None:
    if cancellation_check is None:
        return
    if not callable(cancellation_check):
        raise PrelaunchHandoffError("prelaunch_worker.invalid_state")
    try:
        cancellation_check()
    except Exception as error:
        raise PrelaunchHandoffError("prelaunch_worker.cancelled") from error
