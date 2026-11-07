"""PostgreSQL read-only context adapter with per_statement_identity_checked verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from common_lore_index.retrieval.context_identity import attach_vector_status as _attach_pg_vector_status

from common_lore_index.retrieval.context_work import (
    MAX_SQL_STATEMENTS_POSTGRES,
    WorkLedger,
)
from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
)
from common_lore_index.retrieval.intent_policy import CONTEXT_DIRECT_EVIDENCE_ROLE_V1
from common_lore_index.server._navigation_groups import source_scope_admission
from common_lore_index.storage.context_postgres_identity import (
    read_postgres_context_identity_with_executor,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    read_postgres_navigation_search_with_executor,
)
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)
from common_lore_index.storage.readback_driver import execute_json_readback


def postgres_accepted_identities_match(
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
) -> bool:
    """Compare all 8 PostgreSQL context accepted-publication identity fields across statements."""
    matched, _malformed = _compare_postgres_accepted_identities(expected, actual)
    return matched


def _compare_postgres_accepted_identities(
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
) -> tuple[bool, bool]:
    if not isinstance(expected, Mapping):
        return False, True
    try:
        exp = normalize_accepted_publication(expected)
    except (ContextIdentityError, TypeError):
        return False, True
    if actual is None:
        return False, False
    try:
        act = normalize_accepted_publication(actual)
    except (ContextIdentityError, TypeError):
        return False, True
    return (
        exp.get("repository_id") == act.get("repository_id")
        and exp["generation"] == act["generation"]
        and exp["accepted_run_id"] == act["accepted_run_id"]
        and exp["publication_bundle_id"] == act["publication_bundle_id"]
        and exp["snapshot_manifest_id"] == act["snapshot_manifest_id"]
        and exp["extraction_receipt_id"] == act["extraction_receipt_id"]
        and exp["job_id"] == act["job_id"]
        and exp["attempt"] == act["attempt"]
        and exp["snapshot_vector"] == act["snapshot_vector"],
        False,
    )




class PostgresContextReadAdapter:
    """Read-only PostgreSQL context port enforcing per_statement_identity_checked and 12-statement cap."""

    backend: str = "postgresql"
    consistency_mode: str = "per_statement_identity_checked"

    def __init__(
        self,
        *,
        graph_id: str,
        repository_id: str | None = None,
        root_path: str = "",
        executor: Callable[[str], Any] | None = None,
        psql_args: Sequence[str] = (),
        psql_command: str = "psql",
        password: str | None = None,
        configured_bindings: Mapping[str, Mapping[str, Any]] | None = None,
        private_markers: tuple[str, ...] = (),
    ) -> None:
        self.graph_id = graph_id
        self.repository_id = repository_id or f"repo1:{graph_id}"
        self.root_path = root_path
        self._custom_executor = executor
        self._psql_args = tuple(psql_args)
        self._psql_command = psql_command
        self._password = password
        self._configured_bindings: dict[str, dict[str, Any]] = {
            str(k): dict(v) for k, v in (configured_bindings or {}).items()
        }
        self.private_markers = private_markers

    def close(self) -> None:
        pass

    def __enter__(self) -> "PostgresContextReadAdapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def configured_bindings_by_id(self) -> Mapping[str, Mapping[str, Any]]:
        return self._configured_bindings

    def _run_sql_object(self, sql: str, *, label: str) -> Any:
        if self._custom_executor is not None:
            return self._custom_executor(sql)
        return execute_json_readback(
            sql,
            psql_args=self._psql_args,
            psql_command=self._psql_command,
            label=label,
            expected_shape="object",
            password=self._password,
        )

    def read_initial_identity(self, ledger: WorkLedger) -> dict[str, Any]:
        ledger.max_sql_statements = min(ledger.max_sql_statements, MAX_SQL_STATEMENTS_POSTGRES)
        if not ledger.can_execute_logical_unit() or not ledger.can_execute_statements(1):
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        ledger.record_logical_unit()
        if not ledger.record_statement_start():
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}
        try:
            res = read_postgres_context_identity_with_executor(
                self.repository_id,
                executor=lambda sql: self._run_sql_object(sql, label="context identity"),
            )
        except StorageSchemaError:
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        except (RuntimeError, OSError):
            return {"status": "unavailable", "reason": "database_unavailable"}

        if res.get("status") != "ok" or not isinstance(res.get("accepted_publication"), Mapping):
            return {"status": "unavailable", "reason": res.get("reason", "publication_absent")}

        try:
            acc = normalize_accepted_publication(res["accepted_publication"])
        except (ContextIdentityError, TypeError):
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        return {
            "status": "ok",
            "graph_id": self.graph_id,
            "repository_id": self.repository_id,
            "accepted_publication": acc,
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
        ledger.record_logical_unit()
        if not ledger.record_statement_start():
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}

        admits = (
            source_scope_admission(query, self.private_markers)
            if query.source_binding_id is not None
            else None
        )
        try:
            res = read_postgres_navigation_search_with_executor(
                query,
                executor=lambda sql: self._run_sql_object(sql, label="context navigation search"),
                root_path=self.root_path,
                repository_identity=self.repository_id,
                admits_location=admits,
                role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
                context_identity=True,
            )
        except StorageSchemaError:
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        except (RuntimeError, OSError):
            return {"status": "unavailable", "reason": "database_unavailable"}

        ledger.scan_units_executed += 1
        scan_meta = res.get("scan") or {}
        ledger.candidate_rows_scanned += int(scan_meta.get("nodes", 0))
        ledger.evidence_rows_scanned += int(scan_meta.get("evidence", 0))

        actual_acc = res.get("accepted_publication")
        matched, malformed = _compare_postgres_accepted_identities(expected_identity, actual_acc)
        if malformed:
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        if not matched:
            return {"status": "stale", "reason": "publication_advanced_during_assembly"}
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
        ledger.record_logical_unit()
        if not ledger.record_statement_start():
            return {"status": "exhausted", "reason": ledger.exhausted_reason or "statement_limit"}

        loc_q = NodeLocationsQuery(
            canonical_key=canonical_key, evidence_role="direct", limit=50
        )
        try:
            res = read_postgres_node_locations_with_executor(
                loc_q,
                executor=lambda sql: self._run_sql_object(sql, label="context node locations"),
                root_path=self.root_path,
                repository_identity=self.repository_id,
                role_sql=CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
                context_identity=True,
            )
        except StorageSchemaError:
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        except (RuntimeError, OSError):
            return {"status": "unavailable", "reason": "database_unavailable"}

        ledger.scan_units_executed += 1
        actual_acc = res.get("accepted_publication")
        matched, malformed = _compare_postgres_accepted_identities(expected_identity, actual_acc)
        if malformed:
            return {"status": "unavailable", "reason": "accepted_publication_unverified"}
        if actual_acc is not None and not matched:
            return {"status": "stale", "reason": "publication_advanced_during_assembly"}
        if res.get("status") != "ok":
            if res.get("reason") == "publication_absent":
                return {"status": "stale", "reason": "publication_advanced_during_assembly"}
            return {"status": "ok", "node": None}

        vec = expected_identity.get("snapshot_vector") or ()
        locs = [_attach_pg_vector_status(loc, vec) for loc in res.get("locations", ())]
        ledger.candidate_rows_scanned += 1
        ledger.evidence_rows_scanned += len(locs)
        return {
            "status": "ok",
            "node": {
                "canonical_key": canonical_key,
                "kind": str(res.get("node_kind") or ""),
                "display_name": str(res.get("node_display_name") or ""),
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
        return {"status": "unavailable", "reason": "backend_unsupported"}
