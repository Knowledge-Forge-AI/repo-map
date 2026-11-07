"""Typed query, catalog, and cleanup contracts for W5 HNSW."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Protocol

from common_lore_index.storage.semantic_candidates import (
    CandidateQuery,
    MAX_IMPORT_ROWS,
    checked_identity,
)
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_ann_scope import match_candidate_publication

from retrieval_semantic_ann_models import (
    HnswEvaluationError,
    HnswSourceScope,
    JsonArray,
    JsonObject,
    JsonValue,
)
from retrieval_semantic_ann_sql import (
    DEFAULT_EF_SEARCH,
    DEFAULT_ITERATIVE_SCAN,
    DEFAULT_OWNER_IDENTITY,
    HNSW_DIMENSIONS,
    HnswIndexSpec,
    build_hnsw_index_catalog_sql,
    build_hnsw_index_drop_sql,
)


class FixedObjectExecutor(Protocol):
    """Trusted fixture callback for one generated JSON-object statement."""

    def __call__(self, sql: str, *, label: str) -> JsonObject: ...


class FixedArrayExecutor(Protocol):
    """Trusted fixture callback for one generated EXPLAIN JSON-array statement."""

    def __call__(self, sql: str, *, label: str) -> JsonArray: ...


class ExactBaselineExecutor(Protocol):
    """Trusted exact comparator callback with explicit public source scope."""

    def __call__(
        self, sql: str, *, source_scope: HnswSourceScope, label: str
    ) -> JsonObject: ...


class IndexCatalogReader(Protocol):
    """Read one generated catalog statement through the fixture's owner role."""

    def __call__(self, sql: str, *, label: str) -> HnswIndexCatalogState: ...


class FixedDdlExecutor(Protocol):
    """Execute only generated invocation-owned cleanup DDL."""

    def __call__(self, sql: str, *, label: str) -> None: ...


@dataclass(frozen=True, slots=True)
class HnswKnobs:
    """The initial predeclared settings; callers cannot vary them silently."""

    ef_search: int = DEFAULT_EF_SEARCH
    iterative_scan: str = DEFAULT_ITERATIVE_SCAN

    def validate(self) -> HnswKnobs:
        if type(self.ef_search) is not int or self.ef_search != DEFAULT_EF_SEARCH:
            raise HnswEvaluationError("unapproved_hnsw_knobs", "only predeclared settings are admitted")
        if type(self.iterative_scan) is not str or self.iterative_scan != DEFAULT_ITERATIVE_SCAN:
            raise HnswEvaluationError("unapproved_hnsw_knobs", "only predeclared settings are admitted")
        return self


@dataclass(frozen=True, slots=True)
class HnswEvaluationQuery:
    """A selected exact candidate query narrowed to fixed 384-D HNSW."""

    candidate_query: CandidateQuery
    publication_pin: VerifiedPublicationPin
    attempt_identity: str
    owner_identity: str = DEFAULT_OWNER_IDENTITY
    ann_scan_limit: int = MAX_IMPORT_ROWS
    knobs: HnswKnobs = HnswKnobs()

    def validate(self) -> HnswEvaluationQuery:
        if not isinstance(self.publication_pin, VerifiedPublicationPin):
            raise HnswEvaluationError("unverified_publication_pin", "VerifiedPublicationPin is required")
        if self.publication_pin.backend != "postgresql":
            raise HnswEvaluationError("hnsw_postgresql_required", "HNSW requires a PostgreSQL publication")
        try:
            dimensions = self.candidate_query.profile.dimensions
            vector_length = len(self.candidate_query.vector)
        except (AttributeError, TypeError) as exc:
            raise HnswEvaluationError("invalid_candidate_query", "candidate query validation failed") from exc
        if dimensions != HNSW_DIMENSIONS:
            raise HnswEvaluationError("hnsw_dimensions", "HNSW evaluation requires 384 dimensions")
        if vector_length != HNSW_DIMENSIONS:
            raise HnswEvaluationError("hnsw_vector_dimensions", "query vector must have 384 values")
        try:
            self.candidate_query.validate()
        except (TypeError, ValueError) as exc:
            raise HnswEvaluationError("invalid_candidate_query", "candidate query validation failed") from exc
        if self.candidate_query.selected is not True:
            raise HnswEvaluationError("hnsw_selection_required", "HNSW evaluation requires explicit selection")
        try:
            checked_identity(self.attempt_identity)
        except ValueError as exc:
            raise HnswEvaluationError("invalid_hnsw_attempt", "HNSW attempt identity is invalid") from exc
        self._public_source_scope()
        match_candidate_publication(self.candidate_query.publication, self.publication_pin)
        try:
            checked_identity(self.owner_identity)
        except ValueError as exc:
            raise HnswEvaluationError("invalid_hnsw_owner", "HNSW owner identity is invalid") from exc
        if type(self.ann_scan_limit) is not int or not (
            self.candidate_query.limit <= self.ann_scan_limit <= MAX_IMPORT_ROWS
        ):
            raise HnswEvaluationError("hnsw_scan_limit", "scan limit must cover result and stay within 500")
        self.knobs.validate()
        return self

    @property
    def index_spec(self) -> HnswIndexSpec:
        self.validate()
        return HnswIndexSpec.from_query(
            self.candidate_query,
            source_scope=self._public_source_scope(),
            attempt_identity=self.attempt_identity,
            owner_identity=self.owner_identity,
        )

    @property
    def public_source_scope(self) -> HnswSourceScope:
        self.validate()
        return self._public_source_scope()

    def _public_source_scope(self) -> HnswSourceScope:
        binding_id = self.candidate_query.source_binding_id
        if binding_id is None:
            raise HnswEvaluationError("hnsw_source_binding_required", "HNSW requires one selected source binding")
        pin = self.publication_pin
        if binding_id in pin.denied_bindings:
            reason = pin.denied_bindings[binding_id]
            if type(reason) is not str or not reason or not reason.replace("_", "").isalnum():
                reason = "source_scope_refused"
            raise HnswEvaluationError(reason, "source binding is not public-authorized")
        if binding_id not in pin.admitted_public_bindings:
            raise HnswEvaluationError("unknown_source_binding", "source binding is not public-authorized")
        try:
            snapshots = pin.snapshot_by_binding()
        except Exception as exc:
            raise HnswEvaluationError("invalid_snapshot_vector", "publication snapshot vector unavailable") from exc
        selected = snapshots.get(binding_id)
        if selected is None or type(selected) is not tuple or len(selected) != 2:
            raise HnswEvaluationError("source_snapshot_unavailable", "selected source lacks a pinned snapshot")
        revision, snapshot_id = selected
        if type(revision) is not int or isinstance(revision, bool) or revision < 1:
            raise HnswEvaluationError("invalid_snapshot_vector", "source revision is invalid")
        if type(snapshot_id) is not str or not snapshot_id:
            raise HnswEvaluationError("invalid_snapshot_vector", "source snapshot is invalid")
        try:
            checked_identity(snapshot_id)
        except ValueError as exc:
            raise HnswEvaluationError("invalid_snapshot_vector", "source snapshot identity is invalid") from exc
        return ((binding_id, snapshot_id),)

    @property
    def snapshot_by_binding(self) -> dict[str, str]:
        return dict(self.public_source_scope)


@dataclass(frozen=True, slots=True)
class HnswIndexCatalogState:
    """Whitelisted catalog fields used to prove ownership and index shape."""

    present: bool
    index_oid: int | None = None
    table_oid: int | None = None
    index_attribute_count: int | None = None
    index_key_count: int | None = None
    index_schema: str | None = None
    index_name: str | None = None
    table_schema: str | None = None
    table_name: str | None = None
    access_method: str | None = None
    is_valid: bool | None = None
    is_ready: bool | None = None
    index_owner: str | None = None
    current_user: str | None = None
    opclass_schema: str | None = None
    opclass_name: str | None = None
    expression: str | None = None
    predicate: str | None = None
    reloptions: tuple[str, ...] | None = None

    @classmethod
    def from_json(cls, payload: Mapping[str, JsonValue]) -> HnswIndexCatalogState:
        allowed = {
            "present", "index_oid", "table_oid", "index_attribute_count", "index_key_count",
            "index_schema", "index_name", "table_schema", "table_name", "access_method",
            "is_valid", "is_ready", "index_owner", "current_user", "opclass_schema",
            "opclass_name", "expression", "predicate", "reloptions",
        }
        if not set(payload).issubset(allowed):
            raise HnswEvaluationError("invalid_index_catalog", "catalog contains an unapproved field")
        present = payload.get("present")
        if type(present) is not bool:
            raise HnswEvaluationError("invalid_index_catalog", "catalog presence is not boolean")

        def optional_text(field: str) -> str | None:
            value = payload.get(field)
            if value is not None and type(value) is not str:
                raise HnswEvaluationError("invalid_index_catalog", f"catalog {field} is not text")
            return value

        def optional_bool(field: str) -> bool | None:
            value = payload.get(field)
            if value is not None and type(value) is not bool:
                raise HnswEvaluationError("invalid_index_catalog", f"catalog {field} is not boolean")
            return value

        def optional_positive_int(field: str) -> int | None:
            value = payload.get(field)
            if value is not None and (type(value) is not int or value <= 0):
                raise HnswEvaluationError("invalid_index_catalog", f"catalog {field} is not positive")
            return value

        raw_options = payload.get("reloptions")
        if raw_options is not None and not isinstance(raw_options, list):
            raise HnswEvaluationError("invalid_index_catalog", "catalog reloptions are not text")
        options: tuple[str, ...] | None = None
        if raw_options is not None:
            option_values: list[str] = []
            for option in raw_options:
                if type(option) is not str:
                    raise HnswEvaluationError("invalid_index_catalog", "catalog reloptions are not text")
                option_values.append(option)
            options = tuple(option_values)

        return cls(
            present, optional_positive_int("index_oid"), optional_positive_int("table_oid"),
            optional_positive_int("index_attribute_count"), optional_positive_int("index_key_count"),
            optional_text("index_schema"), optional_text("index_name"),
            optional_text("table_schema"), optional_text("table_name"),
            optional_text("access_method"), optional_bool("is_valid"),
            optional_bool("is_ready"), optional_text("index_owner"),
            optional_text("current_user"), optional_text("opclass_schema"),
            optional_text("opclass_name"), optional_text("expression"),
            optional_text("predicate"), options,
        )


def _normalized_sql(value: str | None) -> str:
    text = "".join((value or "").lower().replace('"', "").split())
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        wraps_all = True
        for index, char in enumerate(text):
            depth += char == "("
            depth -= char == ")"
            if depth == 0 and index != len(text) - 1:
                wraps_all = False
                break
        if not wraps_all:
            break
        text = text[1:-1]
    return text


def verify_hnsw_index_catalog(state: HnswIndexCatalogState, spec: HnswIndexSpec) -> str | None:
    """Return a refusal code unless the exact current owned index is present."""
    spec.validate()
    if state.present is not True:
        return "hnsw_index_absent"
    if state.index_oid is None or state.table_oid is None:
        return "hnsw_index_oid_missing"
    if state.index_attribute_count != 1 or state.index_key_count != 1:
        return "hnsw_index_key_shape_mismatch"
    if state.reloptions != ():
        return "hnsw_index_reloptions_mismatch"
    if (state.index_schema, state.index_name, state.table_schema, state.table_name) != (
        "repomap_enrichment", spec.name, "repomap_enrichment", "embeddings"
    ):
        return "hnsw_index_identity_mismatch"
    if (state.access_method, state.opclass_schema, state.opclass_name) != (
        "hnsw", "repomap_vector", "vector_cosine_ops"
    ):
        return "hnsw_index_operator_mismatch"
    if state.is_valid is not True or state.is_ready is not True:
        return "hnsw_index_not_ready"
    if state.index_owner != spec.owner_identity or state.current_user != spec.owner_identity:
        return "hnsw_index_owner_mismatch"
    expression = _normalized_sql(state.expression)
    if expression not in {
        "embedding::repomap_vector.vector(384)",
        "(embedding)::repomap_vector.vector(384)",
    }:
        return "hnsw_index_expression_mismatch"
    predicate = _normalized_sql(state.predicate)
    expected_predicate = {
        f"(rebuild_id='{spec.rebuild_id.lower()}'::text)and(dimensions=384)",
        f"(rebuild_id='{spec.rebuild_id.lower()}')and(dimensions=384)",
    }
    if predicate not in expected_predicate:
        return "hnsw_index_dimension_predicate_mismatch"
    return None


@dataclass(frozen=True, slots=True)
class HnswCleanupReport:
    index_name: str
    drop_attempted: bool
    verified_absent: bool
    ownership_refused: bool
    failure_code: str | None

    def validate(self) -> HnswCleanupReport:
        if type(self.index_name) is not str or not self.index_name:
            raise ValueError("invalid cleanup index name")
        if type(self.drop_attempted) is not bool or type(self.verified_absent) is not bool:
            raise ValueError("invalid cleanup booleans")
        if type(self.ownership_refused) is not bool:
            raise ValueError("invalid cleanup ownership flag")
        if self.failure_code is not None and re.fullmatch(
            r"[a-z][a-z0-9_]{0,79}", self.failure_code
        ) is None:
            raise ValueError("invalid cleanup failure code")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "index_name": self.index_name, "drop_attempted": self.drop_attempted,
            "verified_absent": self.verified_absent, "ownership_refused": self.ownership_refused,
            "failure_code": self.failure_code,
        }


def cleanup_owned_hnsw_index(
    spec: HnswIndexSpec,
    *,
    expected_index_oid: int | None = None,
    expected_table_oid: int | None = None,
    read_catalog: IndexCatalogReader,
    execute_ddl: FixedDdlExecutor,
) -> HnswCleanupReport:
    """RESTRICT-drop only an index proved created by this invocation.

    A name and shape are not enough for destructive cleanup: callers must
    carry the OIDs from their fresh creation receipt.
    """
    spec.validate()
    if (
        type(expected_index_oid) is not int or expected_index_oid <= 0
        or type(expected_table_oid) is not int or expected_table_oid <= 0
    ):
        return HnswCleanupReport(spec.name, False, False, True, "creation_receipt_required")
    try:
        before = read_catalog(build_hnsw_index_catalog_sql(spec), label="hnsw index cleanup preflight")
    except Exception:
        return HnswCleanupReport(spec.name, False, False, False, "catalog_read_failed")
    if not before.present:
        return HnswCleanupReport(spec.name, False, True, False, None)
    mismatch = verify_hnsw_index_catalog(before, spec)
    if mismatch is not None:
        return HnswCleanupReport(spec.name, False, False, True, mismatch)
    if before.index_oid != expected_index_oid or before.table_oid != expected_table_oid:
        return HnswCleanupReport(spec.name, False, False, True, "creation_oid_mismatch")
    try:
        execute_ddl(build_hnsw_index_drop_sql(spec), label="hnsw index cleanup")
    except Exception:
        return HnswCleanupReport(spec.name, True, False, False, "drop_failed")
    try:
        after = read_catalog(build_hnsw_index_catalog_sql(spec), label="hnsw index cleanup verification")
    except Exception:
        return HnswCleanupReport(spec.name, True, False, False, "cleanup_readback_failed")
    return HnswCleanupReport(
        spec.name, True, not after.present, False,
        None if not after.present else "drop_not_verified",
    )
