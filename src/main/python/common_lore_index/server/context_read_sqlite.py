"""SQLite Local read-only context adapter with single-read-transaction and statement guards."""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
import sqlite3
from typing import Any

from common_lore_index.retrieval.context_identity import attach_vector_status as _attach_vector_status

from common_lore_index.retrieval.context_work import (
    MAX_AGGREGATE_RELATIONS,
    MAX_CANDIDATE_NEIGHBORS,
    ContextWorkExhaustedError,
    GuardedSQLiteConnection,
    WorkLedger,
)
from common_lore_index.retrieval.intent_policy import CONTEXT_DIRECT_EVIDENCE_ROLE_V1
from common_lore_index.server._navigation_groups import source_scope_admission
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.sqlite_local.context_expansion_queries import (
    batch_neighbor_direct_locations,
    expand_seed_incident_edges,
    read_sqlite_context_publication,
)
from common_lore_index.storage.sqlite_local.connection import read_transaction
from common_lore_index.storage.sqlite_local.navigation_queries import navigation_candidates
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    GRAPH_MISMATCH,
    LocalGraphBinding,
    LocalStoreError,
    RUNTIME_UNSUPPORTED,
    SCHEMA_BEHIND,
    SCHEMA_DRIFT,
    SCHEMA_UNSUPPORTED,
    UNRECOGNIZED,
)
from common_lore_index.storage.sqlite_local.node_location_queries import node_locations

_SQLITE_INTERRUPT = int(getattr(sqlite3, "SQLITE_INTERRUPT", 9))
_EXHAUSTION_REASONS = frozenset(("statement_limit", "work_budget_exhausted", "deadline_exceeded"))
_UNVERIFIED_STORE_CODES = frozenset((GRAPH_MISMATCH, RUNTIME_UNSUPPORTED, SCHEMA_BEHIND, SCHEMA_DRIFT, SCHEMA_UNSUPPORTED, UNRECOGNIZED))


def _storage_unavailable_reason(error: BaseException) -> str:
    if isinstance(error, StorageSchemaError) and (
        not isinstance(error, LocalStoreError) or error.code in _UNVERIFIED_STORE_CODES
    ):
        return "accepted_publication_unverified"
    return "database_unavailable"


def _read_failure(error: BaseException, ledger: WorkLedger) -> dict[str, str]:
    if (isinstance(error, sqlite3.OperationalError) and getattr(error, "sqlite_errorcode", None) == _SQLITE_INTERRUPT
            and ledger.exhausted_reason in _EXHAUSTION_REASONS):
        return {"status": "exhausted", "reason": ledger.exhausted_reason or "work_budget_exhausted"}
    return {"status": "unavailable", "reason": _storage_unavailable_reason(error)}


def _expansion_unavailable(error: BaseException) -> dict[str, Any]:
    return {"status": "unavailable", "reason": _storage_unavailable_reason(error)}


class SqliteContextReadAdapter:
    """Read-only SQLite Local context port enforcing single_read_transaction and 36-statement cap."""
    backend: str = "sqlite"
    consistency_mode: str = "single_read_transaction"

    def __init__(
        self,
        *,
        graph_id: str,
        repository_id: str | None = None,
        connection: sqlite3.Connection | None = None,
        db_path: Path | None = None,
        binding: LocalGraphBinding | None = None,
        configured_bindings: Mapping[str, Mapping[str, Any]] | None = None,
        private_markers: tuple[str, ...] = (),
    ) -> None:
        self.graph_id = graph_id
        self.repository_id = repository_id or f"repo1:{graph_id}"
        self._external_conn = connection
        self._db_path = db_path
        self._owned_conn: sqlite3.Connection | None = None
        self._owned_transaction: AbstractContextManager[sqlite3.Connection] | None = None
        self._binding = binding
        self._external_snapshot_started = False
        self._external_transaction_started = False
        self._configured_bindings: dict[str, dict[str, Any]] = {
            str(k): dict(v) for k, v in (configured_bindings or {}).items()
        }
        self.private_markers = private_markers

    def _get_connection(self) -> sqlite3.Connection:
        if self._external_conn is not None:
            if not self._external_snapshot_started:
                if not self._external_conn.in_transaction:
                    self._external_conn.execute("BEGIN DEFERRED")
                    self._external_transaction_started = True
                self._external_snapshot_started = True
            return self._external_conn
        if self._owned_conn is None:
            if self._db_path is None or self._binding is None:
                raise LocalStoreError(DATABASE_UNAVAILABLE)
            transaction = read_transaction(self._db_path, self._binding)
            self._owned_conn = transaction.__enter__()
            self._owned_transaction = transaction
        return self._owned_conn

    def close(self) -> None:
        if self._external_conn is not None:
            if self._external_transaction_started:
                try:
                    self._external_conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            self._external_transaction_started = False
            self._external_snapshot_started = False
        if self._owned_transaction is not None:
            try:
                self._owned_transaction.__exit__(None, None, None)
            except (LocalStoreError, sqlite3.Error):
                pass
            self._owned_transaction = None
            self._owned_conn = None
        elif self._owned_conn is not None:
            try:
                self._owned_conn.close()
            except sqlite3.Error:
                pass
            self._owned_conn = None

    def __enter__(self) -> "SqliteContextReadAdapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def configured_bindings_by_id(self) -> Mapping[str, Mapping[str, Any]]:
        return self._configured_bindings

    @contextmanager
    def _guarded_unit(
        self, ledger: WorkLedger
    ) -> Iterator[GuardedSQLiteConnection]:
        conn = self._get_connection()
        ledger.record_logical_unit()
        conn.set_progress_handler(
            ledger.make_sqlite_progress_handler(),
            max(1, ledger.sqlite_progress_interval_ops),
        )
        try:
            yield GuardedSQLiteConnection(conn, ledger)
        finally:
            conn.set_progress_handler(None, 0)

    def read_initial_identity(self, ledger: WorkLedger) -> dict[str, Any]:
        if not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        try:
            with self._guarded_unit(ledger) as guarded:
                ident = read_sqlite_context_publication(guarded)
        except ContextWorkExhaustedError:
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        except (StorageSchemaError, sqlite3.Error) as error:
            return _read_failure(error, ledger)
        if ident is None:
            return {"status": "unavailable", "reason": "publication_absent"}
        return {
            "status": "ok",
            "graph_id": ident.graph_id,
            "repository_id": ident.repository_id,
            "accepted_publication": {
                "generation": ident.generation,
                "accepted_run_id": ident.run_id,
                "run_id": ident.run_id,
                "publication_bundle_id": ident.publication_bundle_id,
                "snapshot_manifest_id": ident.snapshot_manifest_id,
                "extraction_receipt_id": ident.extraction_receipt_id,
                "job_id": ident.publication_job_id,
                "publication_job_id": ident.publication_job_id,
                "attempt": ident.publication_attempt,
                "publication_attempt": ident.publication_attempt,
                "snapshot_vector": ident.snapshot_vector,
            },
        }

    def query_candidates_unit(
        self,
        query: NavigationSearchQuery,
        *,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        admits = (
            source_scope_admission(query, self.private_markers)
            if query.source_binding_id is not None
            else None
        )
        try:
            with self._guarded_unit(ledger) as guarded:
                res = navigation_candidates(
                    guarded,
                    query,
                    admits_location=admits,
                    role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
                    context_identity=True,
                )
        except ContextWorkExhaustedError:
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        except (StorageSchemaError, sqlite3.Error) as error:
            return _read_failure(error, ledger)
        ledger.scan_units_executed += 1
        scan_meta = res.get("scan") or {}
        ledger.candidate_rows_scanned += int(scan_meta.get("nodes", 0))
        ledger.evidence_rows_scanned += int(scan_meta.get("evidence", 0))
        return res

    def query_node_by_canonical_key(
        self,
        canonical_key: str,
        *,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        loc_q = NodeLocationsQuery(
            canonical_key=canonical_key, evidence_role="direct", limit=50
        )
        try:
            with self._guarded_unit(ledger) as guarded:
                res = node_locations(
                    guarded,
                    loc_q,
                    role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
                    context_identity=True,
                    include_node_summary=True,
                )
        except ContextWorkExhaustedError:
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        except (StorageSchemaError, sqlite3.Error) as error:
            return _read_failure(error, ledger)
        ledger.scan_units_executed += 1
        if res.get("status") != "ok":
            return {"status": "ok", "node": None}
        summary = res.get("node_summary") or {}
        vec = expected_identity.get("snapshot_vector") or ()
        locs = [_attach_vector_status(loc, vec) for loc in res.get("locations", ())]
        ledger.candidate_rows_scanned += 1
        ledger.evidence_rows_scanned += len(locs)
        return {
            "status": "ok",
            "node": {
                "id": summary.get("id"),
                "canonical_key": canonical_key,
                "kind": summary.get("kind", ""),
                "display_name": summary.get("display_name", ""),
                "first_seen_run_id": res.get("node_first_seen_run_id"),
                "last_seen_run_id": res.get("node_last_seen_run_id"),
                "locations": locs,
            },
        }

    def expand_seeds_depth1(
        self,
        seed_keys: Sequence[str],
        *,
        edge_kinds: Sequence[str],
        node_limit: int,
        edge_limit: int,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        seed_set = set(seed_keys)
        neighbor_by_ck: dict[str, dict[str, Any]] = {}
        edges_by_nbr: dict[str, list[dict[str, Any]]] = {}
        seed_to_seed_edges: list[dict[str, Any]] = []
        seen_edge_keys: set[str] = set()
        rejected_edge_keys: set[str] = set()
        seeds_expanded = 0
        edge_limit_hit = 0
        node_limit_hit = 0
        partial_reason: str | None = None
        for seed_ck in seed_keys:
            if not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
                partial_reason = ledger.exhausted_reason or "statement_limit"
                break
            try:
                with self._guarded_unit(ledger) as guarded:
                    exp = expand_seed_incident_edges(
                        guarded,
                        seed_canonical_key=seed_ck,
                        edge_kinds=edge_kinds,
                        per_seed_limit=edge_limit,
                    )
            except ContextWorkExhaustedError:
                partial_reason = ledger.exhausted_reason or "statement_limit"
                break
            except (StorageSchemaError, sqlite3.Error) as error:
                failure = _read_failure(error, ledger)
                if failure["status"] == "exhausted":
                    partial_reason = failure["reason"]
                    break
                return _expansion_unavailable(error)
            seeds_expanded += 1
            ledger.seed_expansions_executed += 1
            if exp.get("truncated"):
                edge_limit_hit += 1
            seed_nbr_count = 0
            for edge in exp.get("edges", ()):
                nbr_ck = str(edge["neighbor_canonical_key"])
                ekey = str(edge["edge_key"])
                if ekey in seen_edge_keys or ekey in rejected_edge_keys:
                    continue
                if len(seen_edge_keys) >= MAX_AGGREGATE_RELATIONS:
                    rejected_edge_keys.add(ekey)
                    edge_limit_hit += 1
                    continue
                if nbr_ck in seed_set:
                    seen_edge_keys.add(ekey)
                    seed_to_seed_edges.append(edge)
                    continue
                if nbr_ck not in neighbor_by_ck:
                    if seed_nbr_count >= node_limit or len(neighbor_by_ck) >= MAX_CANDIDATE_NEIGHBORS:
                        node_limit_hit += 1
                        continue
                    seed_nbr_count += 1
                    neighbor_by_ck[nbr_ck] = {
                        "id": int(edge["neighbor_id"]),
                        "canonical_key": nbr_ck,
                        "kind": str(edge["neighbor_kind"]),
                        "display_name": edge["neighbor_display_name"],
                        "first_seen_run_id": int(edge["neighbor_first_seen_run_id"]),
                        "last_seen_run_id": int(edge["neighbor_last_seen_run_id"]),
                        "locations": [],
                    }
                    edges_by_nbr[nbr_ck] = []
                seen_edge_keys.add(ekey)
                edges_by_nbr[nbr_ck].append(edge)
        neighbor_locations_incomplete = False
        if neighbor_by_ck and partial_reason is None:
            raw_run_id = expected_identity.get(
                "accepted_run_id", expected_identity.get("run_id")
            )
            if type(raw_run_id) is not int or raw_run_id < 1:
                partial_reason = "accepted_publication_unverified"
                neighbor_by_ck.clear()
            elif not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
                partial_reason = ledger.exhausted_reason or "statement_limit"
                neighbor_by_ck.clear()
            else:
                nbr_ids = [int(n["id"]) for n in neighbor_by_ck.values()]
                vec = expected_identity.get("snapshot_vector") or ()
                try:
                    with self._guarded_unit(ledger) as guarded:
                        loc_res = batch_neighbor_direct_locations(
                            guarded,
                            neighbor_ids=nbr_ids,
                            accepted_run_id=raw_run_id,
                            role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
                            snapshot_vector=vec,
                        )
                    ledger.evidence_rows_scanned += int(loc_res.get("evidence_scanned", 0))
                    if loc_res.get("incomplete"):
                        neighbor_locations_incomplete = True
                        partial_reason = partial_reason or "evidence_scan_limit"
                    by_id = loc_res.get("locations_by_node_id") or {}
                    for nbr in neighbor_by_ck.values():
                        nbr["locations"] = list(by_id.get(int(nbr["id"]), ()))
                except ContextWorkExhaustedError:
                    partial_reason = ledger.exhausted_reason or "statement_limit"
                    neighbor_by_ck.clear()
                except (StorageSchemaError, sqlite3.Error) as error:
                    failure = _read_failure(error, ledger)
                    if failure["status"] == "exhausted":
                        partial_reason = failure["reason"]
                        neighbor_by_ck.clear()
                    else:
                        return _expansion_unavailable(error)
        neighbor_units = [
            {"node": nbr, "edges": edges_by_nbr.get(ck, [])}
            for ck, nbr in neighbor_by_ck.items()
        ]
        return {
            "status": "partial" if partial_reason else "ok",
            "reason": partial_reason,
            "seeds_expanded": seeds_expanded,
            "neighbor_units": neighbor_units,
            "seed_to_seed_edges": seed_to_seed_edges,
            "edge_limit_hit": edge_limit_hit,
            "node_limit_hit": node_limit_hit,
            "neighbor_locations_incomplete": neighbor_locations_incomplete,
        }
