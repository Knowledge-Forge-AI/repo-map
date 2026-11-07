"""Invocation-owned schema receipts for the disposable JSONB experiment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from retrieval_jsonb_contracts import DISPOSABLE_SCHEMA
from retrieval_semantic_representation import RepresentationValidationError


@dataclass(frozen=True, slots=True)
class JsonbSchemaCatalogState:
    """The bounded catalog readback used before every invocation-owned DDL."""

    schema_exists: bool
    schema_oid: int | None
    schema_owner: str | None

    def validate(self) -> JsonbSchemaCatalogState:
        if type(self.schema_exists) is not bool:
            raise ValueError("schema_exists must be boolean")
        if self.schema_oid is not None and (type(self.schema_oid) is not int or self.schema_oid <= 0):
            raise ValueError("schema_oid must be a positive integer when present")
        if self.schema_owner is not None and (type(self.schema_owner) is not str or not self.schema_owner):
            raise ValueError("schema_owner must be non-empty text when present")
        if self.schema_exists and (self.schema_oid is None or self.schema_owner is None):
            raise ValueError("an existing schema must have an OID and owner")
        if not self.schema_exists and (self.schema_oid is not None or self.schema_owner is not None):
            raise ValueError("an absent schema cannot have an OID or owner")
        return self


@dataclass(frozen=True, slots=True)
class JsonbSchemaOwnershipReceipt:
    """Proof that this invocation created the exact disposable namespace."""

    schema_name: str
    schema_oid: int
    schema_owner: str

    def validate(self) -> JsonbSchemaOwnershipReceipt:
        if self.schema_name != DISPOSABLE_SCHEMA:
            raise ValueError("schema receipt names an unapproved namespace")
        if type(self.schema_oid) is not int or self.schema_oid <= 0:
            raise ValueError("schema receipt OID must be positive")
        if type(self.schema_owner) is not str or not self.schema_owner:
            raise ValueError("schema receipt owner must be non-empty text")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_name": self.schema_name,
            "schema_oid": self.schema_oid,
            "schema_owner": self.schema_owner,
        }


def build_schema_catalog_sql() -> str:
    """Read only the fixed namespace identity, returning one JSON object."""
    return (
        "SELECT json_build_object("
        "'schema_exists', EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
        f"WHERE nspname = '{DISPOSABLE_SCHEMA}'), "
        "'schema_oid', (SELECT oid::bigint FROM pg_catalog.pg_namespace "
        f"WHERE nspname = '{DISPOSABLE_SCHEMA}' LIMIT 1), "
        "'schema_owner', (SELECT pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace "
        f"WHERE nspname = '{DISPOSABLE_SCHEMA}' LIMIT 1)"
        ")::text;"
    )


def build_schema_creation_receipt_sql() -> str:
    """Create and receipt the namespace in one transaction using plain CREATE SCHEMA."""
    return (
        "BEGIN;\n"
        "CREATE TEMP TABLE pg_temp.repomap_w5_jsonb_schema_receipt (payload jsonb) "
        "ON COMMIT PRESERVE ROWS;\n"
        f"CREATE SCHEMA {DISPOSABLE_SCHEMA};\n"
        "INSERT INTO pg_temp.repomap_w5_jsonb_schema_receipt(payload) "
        "SELECT json_build_object("
        "'schema_exists', true, "
        "'schema_oid', ns.oid::bigint, "
        "'schema_owner', pg_get_userbyid(ns.nspowner)"
        ")::jsonb FROM pg_catalog.pg_namespace ns "
        f"WHERE ns.nspname = '{DISPOSABLE_SCHEMA}';\n"
        "COMMIT;\n"
        "SELECT payload::text FROM pg_temp.repomap_w5_jsonb_schema_receipt LIMIT 1;"
    )


def build_schema_creation_sql() -> str:
    """Create only the fixed namespace transactionally; callers receipt it next."""
    return f"BEGIN;\nCREATE SCHEMA {DISPOSABLE_SCHEMA};\nCOMMIT;"


def read_schema_catalog_state(payload: Mapping[str, Any]) -> JsonbSchemaCatalogState:
    """Validate the narrow namespace readback without accepting extra identity."""
    allowed = {"schema_exists", "schema_oid", "schema_owner"}
    if not set(payload).issubset(allowed):
        raise RepresentationValidationError("schema_catalog_invalid", "schema catalog returned an unapproved field")
    schema_exists = payload.get("schema_exists")
    if type(schema_exists) is not bool:
        raise RepresentationValidationError("schema_catalog_invalid", "schema_exists must be boolean")
    assert isinstance(schema_exists, bool)
    state = JsonbSchemaCatalogState(
        schema_exists,
        payload.get("schema_oid"),
        payload.get("schema_owner"),
    )
    try:
        return state.validate()
    except ValueError as exc:
        raise RepresentationValidationError("schema_catalog_invalid", str(exc)) from exc


def capture_schema_ownership(payload: Mapping[str, Any]) -> JsonbSchemaOwnershipReceipt:
    """Convert a post-CREATE catalog readback into an owned receipt."""
    state = read_schema_catalog_state(payload)
    if not state.schema_exists or state.schema_oid is None or state.schema_owner is None:
        raise RepresentationValidationError("schema_receipt_invalid", "CREATE SCHEMA did not return an owned namespace")
    try:
        return JsonbSchemaOwnershipReceipt(DISPOSABLE_SCHEMA, state.schema_oid, state.schema_owner).validate()
    except ValueError as exc:
        raise RepresentationValidationError("schema_receipt_invalid", str(exc)) from exc


def inspect_and_refuse_preexisting_schema(
    json_executor: Callable[[str], Mapping[str, Any]],
) -> JsonbSchemaCatalogState:
    """Refuse an occupied name before any schema, table, or index DDL."""
    state = read_schema_catalog_state(json_executor(build_schema_catalog_sql()))
    if state.schema_exists:
        raise RepresentationValidationError(
            "schema_preexisting",
            f"disposable namespace {DISPOSABLE_SCHEMA!r} already exists; adoption is forbidden",
        )
    return state


def create_schema_ownership_receipt(
    json_executor: Callable[[str], Mapping[str, Any]],
    *,
    ddl_executor: Callable[[str], None] | None = None,
) -> JsonbSchemaOwnershipReceipt:
    """Run plain CREATE and capture the OID/owner immediately after it succeeds."""
    if ddl_executor is None:
        return capture_schema_ownership(json_executor(build_schema_creation_receipt_sql()))
    ddl_executor(build_schema_creation_sql())
    return capture_schema_ownership(json_executor(build_schema_catalog_sql()))


def require_schema_ownership(
    receipt: JsonbSchemaOwnershipReceipt,
    json_executor: Callable[[str], Mapping[str, Any]],
) -> JsonbSchemaCatalogState:
    """Require the current namespace to match the invocation's creation receipt."""
    receipt.validate()
    state = read_schema_catalog_state(json_executor(build_schema_catalog_sql()))
    if (
        not state.schema_exists
        or state.schema_oid != receipt.schema_oid
        or state.schema_owner != receipt.schema_owner
    ):
        raise RepresentationValidationError(
            "schema_ownership_mismatch",
            "disposable namespace no longer matches this invocation's creation receipt",
        )
    return state


__all__ = [
    "JsonbSchemaCatalogState",
    "JsonbSchemaOwnershipReceipt",
    "build_schema_catalog_sql",
    "build_schema_creation_sql",
    "build_schema_creation_receipt_sql",
    "capture_schema_ownership",
    "create_schema_ownership_receipt",
    "inspect_and_refuse_preexisting_schema",
    "read_schema_catalog_state",
    "require_schema_ownership",
]
