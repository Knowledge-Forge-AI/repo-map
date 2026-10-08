"""A7 durable publication strengthening assertions and family readback helpers.

Verifies the seven retained staging families across durable publication:
- 4 IDENTICAL_ONLY: files, canonical_nodes, canonical_edges, canonical_evidence
- 2 SET_DEDUPLICATED: canonical_node_evidence, canonical_edge_evidence
- 1 SOURCE_ORDINAL_IDEMPOTENT: raw_observations
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping, Sequence

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.storage.staging_family_contracts import (
    DuplicatePolicy,
    STAGING_FAMILY_DESCRIPTORS,
    StageFamily,
)

__all__ = (
    "ConflictingPayloadError",
    "DuplicateIdentityError",
    "DurableFamilyVerificationError",
    "ExtraIdentityError",
    "FamilyVerificationCounts",
    "MissingIdentityError",
    "StaleLastSeenError",
    "assert_durable_families",
    "verify_family_rows",
)


class DurableFamilyVerificationError(AssertionError):
    """Base error for durable family readback and contract verification failure."""


class MissingIdentityError(DurableFamilyVerificationError):
    """Expected identities are missing from persisted storage."""


class ExtraIdentityError(DurableFamilyVerificationError):
    """Unexpected extra identities found in persisted storage."""


class DuplicateIdentityError(DurableFamilyVerificationError):
    """Duplicate identities found in persisted storage."""


class ConflictingPayloadError(DurableFamilyVerificationError):
    """Payload representative does not match expected contract payload."""


class StaleLastSeenError(DurableFamilyVerificationError):
    """Persisted row has stale last_seen_run_id."""


@dataclass(frozen=True, slots=True)
class FamilyVerificationCounts:
    """Exact row and identity counts recorded during durable verification."""

    family: str
    input_rows: int
    expected_distinct: int
    persisted_rows: int
    persisted_distinct: int


@dataclass(frozen=True, slots=True)
class _FamilySpec:
    family: StageFamily
    identity_columns: tuple[str, ...]
    bundle_payload_columns: tuple[str, ...]
    db_payload_columns: tuple[str, ...]
    payload_mapping: Mapping[str, str]
    identity_mapping: Mapping[str, str]
    query: str
    query_columns: tuple[str, ...]
    has_last_seen: bool
    duplicate_policy: DuplicatePolicy


def _init_specs() -> Mapping[StageFamily, _FamilySpec]:
    files_b_payload = ("language", "role", "confidence", "content_hash", "executable", "generated", "metadata_json")
    files_db_payload = ("language", "role", "content_hash", "executable", "generated", "metadata_json")
    raw_payload = ("schema_version", "kind", "source_id", "path", "payload_json", "payload_hash")
    nodes_payload = ("kind", "display_name", "metadata_json", "confidence", "conflict")
    edge_ident = ("graph_key_version", "source_canonical_key", "edge_kind", "target_canonical_key", "identity_metadata_hash")
    edge_payload = ("identity_metadata_json", "metadata_json", "confidence", "conflict")
    ev_payload = ("raw_observation_ordinal", "raw_schema_version", "raw_kind", "raw_source_id", "path", "start_line", "end_line", "extractor", "extractor_version", "confidence", "metadata_json")
    node_ev_ident = ("graph_key_version", "canonical_key", "evidence_key", "link_kind")
    edge_ev_ident = (*edge_ident, "evidence_key", "link_kind")

    base: dict[StageFamily, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], dict[str, str], bool]] = {
        "files": (("path",), files_b_payload, files_db_payload, {"path": "path"}, True),
        "raw_observations": (("source_ordinal",), raw_payload, raw_payload, {"ordinal": "source_ordinal"}, False),
        "canonical_nodes": (("graph_key_version", "canonical_key"), nodes_payload, nodes_payload, {"graph_key_version": "graph_key_version", "canonical_key": "canonical_key"}, True),
        "canonical_edges": (edge_ident, edge_payload, edge_payload, {c: c for c in edge_ident}, True),
        "canonical_evidence": (("graph_key_version", "evidence_key"), ev_payload, ev_payload, {"graph_key_version": "graph_key_version", "evidence_key": "evidence_key"}, False),
    }

    specs: dict[StageFamily, _FamilySpec] = {}
    for fam, (ident, b_pay, db_pay, id_map, last_seen) in base.items():
        q_cols = (*id_map.keys(), *db_pay, "last_seen_run_id" if last_seen else "run_id")
        where = "WHERE repository_id = %s" if last_seen else "WHERE repository_id = %s AND run_id = %s"
        specs[fam] = _FamilySpec(
            family=fam, identity_columns=ident, bundle_payload_columns=b_pay, db_payload_columns=db_pay,
            payload_mapping={c: c for c in db_pay}, identity_mapping=id_map,
            query=f"SELECT {', '.join(q_cols)} FROM {fam} {where}",
            query_columns=q_cols, has_last_seen=last_seen,
            duplicate_policy=STAGING_FAMILY_DESCRIPTORS[fam].duplicate_policy,
        )

    specs["canonical_node_evidence"] = _FamilySpec(
        family="canonical_node_evidence", identity_columns=node_ev_ident, bundle_payload_columns=(),
        db_payload_columns=(), payload_mapping={}, identity_mapping={c: c for c in node_ev_ident},
        query=(
            "SELECT t.graph_key_version, t.canonical_key, e.evidence_key, l.link_kind "
            "FROM canonical_node_evidence l JOIN canonical_evidence e ON e.id = l.canonical_evidence_id "
            "JOIN canonical_nodes t ON t.id = l.canonical_node_id AND t.repository_id = e.repository_id "
            "WHERE e.repository_id = %s AND e.run_id = %s"
        ),
        query_columns=node_ev_ident, has_last_seen=False,
        duplicate_policy=STAGING_FAMILY_DESCRIPTORS["canonical_node_evidence"].duplicate_policy,
    )
    specs["canonical_edge_evidence"] = _FamilySpec(
        family="canonical_edge_evidence", identity_columns=edge_ev_ident, bundle_payload_columns=(),
        db_payload_columns=(), payload_mapping={}, identity_mapping={c: c for c in edge_ev_ident},
        query=(
            "SELECT t.graph_key_version, t.source_canonical_key, t.edge_kind, t.target_canonical_key, "
            "t.identity_metadata_hash, e.evidence_key, l.link_kind FROM canonical_edge_evidence l "
            "JOIN canonical_evidence e ON e.id = l.canonical_evidence_id "
            "JOIN canonical_edges t ON t.id = l.canonical_edge_id AND t.repository_id = e.repository_id "
            "WHERE e.repository_id = %s AND e.run_id = %s"
        ),
        query_columns=edge_ev_ident, has_last_seen=False,
        duplicate_policy=STAGING_FAMILY_DESCRIPTORS["canonical_edge_evidence"].duplicate_policy,
    )
    return specs


_SPECS = _init_specs()


def _normalize(val: Any, column: str) -> Any:
    if column.endswith("_json") and isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return val


def verify_family_rows(
    family: StageFamily,
    expected_bundle_rows: Sequence[Mapping[str, object]],
    actual_persisted_rows: Sequence[Mapping[str, object] | Sequence[object]],
    expected_run_id: int,
    *,
    column_names: Sequence[str] | None = None,
    record_property: Callable[[str, object], None] | None = None,
) -> FamilyVerificationCounts:
    """Verify durable identity and payload contracts for one staging family."""
    spec = _SPECS[family]
    input_rows = len(expected_bundle_rows)
    expected_by_identity: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
    for r in expected_bundle_rows:
        ident = tuple(r[c] for c in spec.identity_columns)
        expected_by_identity.setdefault(ident, []).append(r)

    expected_distinct = len(expected_by_identity)

    # Validate collapsible rows for IDENTICAL_ONLY and SOURCE_ORDINAL_IDEMPOTENT
    if spec.duplicate_policy in (
        DuplicatePolicy.IDENTICAL_ONLY,
        DuplicatePolicy.SOURCE_ORDINAL_IDEMPOTENT,
    ):
        for ident, rows in expected_by_identity.items():
            if len(rows) > 1:
                rep = {c: _normalize(rows[0][c], c) for c in spec.bundle_payload_columns}
                for other in rows[1:]:
                    other_rep = {c: _normalize(other[c], c) for c in spec.bundle_payload_columns}
                    if rep != other_rep:
                        raise ConflictingPayloadError(
                            f"{family} input collapsible rows conflict for identity {ident}"
                        )

    rep_bundle_row = {ident: rows[0] for ident, rows in expected_by_identity.items()}
    col_names = tuple(column_names or spec.query_columns)
    db_dicts: list[dict[str, object]] = [
        dict(r) if isinstance(r, (dict, Mapping)) else dict(zip(col_names, r))
        for r in actual_persisted_rows
    ]

    def extract_id(r: dict[str, object]) -> tuple[object, ...]:
        return tuple(r[db_col] for db_col in spec.identity_mapping)

    persisted_for_run: list[dict[str, object]] = []
    if spec.has_last_seen:
        by_id: dict[tuple[object, ...], list[dict[str, object]]] = {}
        for r in db_dicts:
            by_id.setdefault(extract_id(r), []).append(r)
        for ident in expected_by_identity:
            matching = by_id.get(ident)
            if not matching:
                raise MissingIdentityError(f"{family} missing identities: {ident}")
            if len(matching) > 1:
                raise DuplicateIdentityError(f"{family} duplicate identities: {ident}")
            last_seen = matching[0].get("last_seen_run_id")
            if last_seen != expected_run_id:
                raise StaleLastSeenError(
                    f"{family} stale last_seen for {ident}: expected {expected_run_id}, got {last_seen}"
                )
        for r in db_dicts:
            if r.get("last_seen_run_id") == expected_run_id:
                ident = extract_id(r)
                if ident not in expected_by_identity:
                    raise ExtraIdentityError(f"{family} extra identities: {ident}")
                persisted_for_run.append(r)
    else:
        for r in db_dicts:
            rid = r.get("run_id")
            if rid is not None and rid != expected_run_id:
                raise StaleLastSeenError(f"{family} stale last_seen: expected {expected_run_id}, got {rid}")
            persisted_for_run.append(r)
        actual_ids = [extract_id(r) for r in persisted_for_run]
        actual_set, exp_set = set(actual_ids), set(expected_by_identity)
        if exp_set - actual_set:
            raise MissingIdentityError(f"{family} missing identities: {sorted(str(k) for k in (exp_set - actual_set))[:3]}")
        if actual_set - exp_set:
            raise ExtraIdentityError(f"{family} extra identities: {sorted(str(k) for k in (actual_set - exp_set))[:3]}")

    persisted_rows = len(persisted_for_run)
    actual_run_ids = [extract_id(r) for r in persisted_for_run]
    persisted_distinct = len(set(actual_run_ids))
    if persisted_rows != persisted_distinct:
        raise DuplicateIdentityError(f"{family} duplicate identities: {persisted_rows} != {persisted_distinct}")

    # Nonidentity payload equality
    persisted_map = {extract_id(r): r for r in persisted_for_run}
    for ident, exp_row in rep_bundle_row.items():
        act_row = persisted_map[ident]
        for db_c in spec.db_payload_columns:
            bundle_c = spec.payload_mapping[db_c]
            exp_v, act_v = _normalize(exp_row[bundle_c], bundle_c), _normalize(act_row[db_c], db_c)
            if exp_v != act_v:
                raise ConflictingPayloadError(
                    f"{family} conflicting payload representative for {ident} at {db_c!r}"
                )

    counts = FamilyVerificationCounts(family, input_rows, expected_distinct, persisted_rows, persisted_distinct)
    if record_property is not None:
        record_property(f"durable_{family}_counts", asdict(counts))
    print(f"[run25_durable_families] {family}: input={input_rows} expected_distinct={expected_distinct} persisted={persisted_rows} persisted_distinct={persisted_distinct}")
    return counts


def assert_durable_families(
    connection: Any,
    bundle: PublicationBundle,
    repository_id: int,
    run_id: int,
    *,
    record_property: Callable[[str, object], None] | None = None,
) -> dict[StageFamily, FamilyVerificationCounts]:
    """Execute durable readback queries and verify all seven retained families."""
    counts_by_family: dict[StageFamily, FamilyVerificationCounts] = {}
    for family in PUBLICATION_FAMILIES:
        spec = _SPECS[family]
        params = (repository_id, run_id) if "%s AND %s" in spec.query or spec.query.count("%s") == 2 else (repository_id,)
        cursor = connection.execute(spec.query, params)
        if hasattr(cursor, "fetchall"):
            rows = cursor.fetchall()
            col_names: Sequence[str] = [
                d[0] if isinstance(d, (tuple, list)) else getattr(d, "name", str(d))
                for d in getattr(cursor, "description", ())
            ] or spec.query_columns
        else:
            rows = cursor
            col_names = spec.query_columns

        counts = verify_family_rows(
            family, bundle.families[family], rows, run_id,
            column_names=col_names, record_property=record_property,
        )
        counts_by_family[family] = counts
    return counts_by_family
