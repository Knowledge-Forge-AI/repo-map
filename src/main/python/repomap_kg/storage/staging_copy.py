"""Strict Psycopg 3 COPY transport for SCALE staging rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import math
import re
from types import MappingProxyType
from typing import Any, get_args, get_origin, get_type_hints

from psycopg import sql
from psycopg.types.json import Jsonb

from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
    StageFamilyDescriptor,
)
from repomap_kg.storage.staging_family_rows import StageFamily


__all__ = (
    "CopyContractError",
    "CopyTransferResult",
    "STAGING_COPY_TABLES",
    "StagingCopyTable",
    "copy_stage_rows",
    "copy_statement",
)

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,62}\Z")
_STAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_COLUMN_TYPES = frozenset({"boolean", "integer", "json", "text"})


def _safe_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value) is not None


class CopyContractError(ValueError):
    """A staging row cannot be transferred through the closed COPY contract."""


@dataclass(frozen=True)
class CopyTransferResult:
    """Bounded evidence returned after a caller-owned COPY operation."""

    family: str
    row_count: int


@dataclass(frozen=True)
class StagingCopyTable:
    """Descriptor-derived typed-column specification for one stage family."""

    family: StageFamily
    table_name: str
    ordinal_column: str
    column_types: Mapping[str, str]
    descriptor: StageFamilyDescriptor | None = None

    def __post_init__(self) -> None:
        if self.family not in STAGING_FAMILY_DESCRIPTORS:
            raise CopyContractError("unknown staging COPY family")
        expected = STAGING_FAMILY_DESCRIPTORS[self.family]
        if self.table_name != expected.stage_table:
            raise CopyContractError("invalid staging COPY table")
        if self.descriptor is not None and self.descriptor is not expected:
            raise CopyContractError("invalid staging COPY descriptor")
        columns = tuple(self.column_types)
        if columns != expected.copy_columns or len(set(columns)) != len(columns):
            raise CopyContractError("invalid staging COPY columns")
        if "stage_id" not in columns or self.ordinal_column != expected.technical_ordinal:
            raise CopyContractError("staging COPY ownership columns are missing")
        if any(
            not _safe_identifier(column)
            or self.column_types[column] not in _COLUMN_TYPES
            for column in columns
        ):
            raise CopyContractError("invalid staging COPY column type")

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the immutable insertion order used by COPY."""

        return tuple(self.column_types)

    def adapt_row(
        self,
        row: Mapping[str, object],
        *,
        expected_stage_id: str,
    ) -> tuple[object, ...]:
        """Validate and adapt one mapping to the closed Psycopg row order."""

        _require_stage_id(expected_stage_id)
        if not isinstance(row, Mapping):
            raise CopyContractError("staging COPY row is not a mapping")
        try:
            keys = set(row)
        except TypeError as error:
            raise CopyContractError("staging COPY row columns are invalid") from error
        if keys != set(self.columns) or any(not isinstance(key, str) for key in keys):
            raise CopyContractError("staging COPY row columns are invalid")
        if row["stage_id"] != expected_stage_id:
            raise CopyContractError("staging COPY stage ownership mismatch")

        adapted: list[object] = []
        for column in self.columns:
            value = row[column]
            adapted.append(_adapt_value(self.column_types[column], value))
        ordinal = row[self.ordinal_column]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise CopyContractError("staging COPY ordinal is invalid")
        return tuple(adapted)


def copy_statement(table: StagingCopyTable) -> sql.Composed:
    """Build a COPY statement from a repository-owned table specification."""

    if not _is_catalog_table(table):
        raise CopyContractError("staging COPY table is invalid")
    return sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table.table_name),
        sql.SQL(", ").join(sql.Identifier(column) for column in table.columns),
    )


def copy_stage_rows(
    connection: Any,
    table: StagingCopyTable,
    rows: Iterable[Mapping[str, object]],
    *,
    expected_stage_id: str,
) -> CopyTransferResult:
    """Stream rows through Psycopg COPY without committing or rolling back."""

    if not _is_catalog_table(table):
        raise CopyContractError("staging COPY table is invalid")
    _require_stage_id(expected_stage_id)
    row_count = 0
    with connection.cursor() as cursor:
        with cursor.copy(copy_statement(table)) as copy:
            for row in rows:
                copy.write_row(
                    table.adapt_row(row, expected_stage_id=expected_stage_id)
                )
                row_count += 1
    return CopyTransferResult(table.family, row_count)


def _copy_column_type(annotation: object) -> str:
    non_null = tuple(item for item in get_args(annotation) if item is not type(None))
    if non_null and len(non_null) != len(get_args(annotation)):
        if len(non_null) != 1:
            raise CopyContractError("staging COPY row annotation is invalid")
        annotation = non_null[0]
    if annotation is str:
        return "text"
    if annotation is int:
        return "integer"
    if annotation is bool:
        return "boolean"
    if get_origin(annotation) is Mapping:
        return "json"
    raise CopyContractError("staging COPY row annotation is invalid")


def _table_spec(descriptor: StageFamilyDescriptor) -> StagingCopyTable:
    annotations = get_type_hints(descriptor.row_type)
    column_types = MappingProxyType(
        {
            column: _copy_column_type(annotations[column])
            for column in descriptor.copy_columns
        }
    )
    return StagingCopyTable(
        family=descriptor.family,
        table_name=descriptor.stage_table,
        ordinal_column=descriptor.technical_ordinal,
        column_types=column_types,
        descriptor=descriptor,
    )


STAGING_COPY_TABLES: Mapping[StageFamily, StagingCopyTable] = MappingProxyType(
    {
        family: _table_spec(descriptor)
        for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items()
    }
)


def _is_catalog_table(table: object) -> bool:
    return isinstance(table, StagingCopyTable) and any(
        candidate is table for candidate in STAGING_COPY_TABLES.values()
    )


def _require_stage_id(value: object) -> None:
    if not isinstance(value, str) or _STAGE_ID_PATTERN.fullmatch(value) is None:
        raise CopyContractError("staging COPY stage identifier is invalid")


def _adapt_value(column_type: str, value: object) -> object:
    if column_type == "text":
        if value is not None and not isinstance(value, str):
            raise CopyContractError("staging COPY text value is invalid")
        return value
    if column_type == "integer":
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise CopyContractError("staging COPY integer value is invalid")
        return value
    if column_type == "boolean":
        if not isinstance(value, bool):
            raise CopyContractError("staging COPY boolean value is invalid")
        return value
    if column_type == "json":
        _validate_json_value(value)
        return Jsonb(value)
    raise CopyContractError("staging COPY column type is invalid")


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CopyContractError("staging COPY JSON value is invalid")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CopyContractError("staging COPY JSON value is invalid")
        for item in value.values():
            _validate_json_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item)
        return
    try:
        json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CopyContractError("staging COPY JSON value is invalid") from error
    raise CopyContractError("staging COPY JSON value is invalid")
