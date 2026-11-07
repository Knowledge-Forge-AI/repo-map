"""Bind the functional adapter to exact maintained per-binding ANN SQL."""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any

from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.semantic_candidates import CandidateQuery
from repomap_test_support.w5_component_planner_adapter import FunctionalAdapter
from repomap_test_support.w5_experiment_postgres import HNSW_OWNER_ROLE, READ_ROLE
from retrieval_semantic_ann import HnswEvaluationQuery
from retrieval_semantic_ann_sql import build_hnsw_explain_sql, build_hnsw_query_sql
from retrieval_semantic_experiment_contracts import ExperimentRefusal


def functional_hnsw_queries(publication: Any, profile: Any, pin: Any,
                            bindings: Sequence[str], *, rebuild_id: str,
                            vector: tuple[float, ...]) -> tuple[HnswEvaluationQuery, ...]:
    """Register the maintained call's explicit limits, independent of defaults."""
    return tuple(HnswEvaluationQuery(
        CandidateQuery(publication,profile,rebuild_id,vector,selected=True,
                       limit=20,evidence_limit=5,source_binding_id=binding),
        pin,"w5-semantic-g1",owner_identity=HNSW_OWNER_ROLE,
    ).validate() for binding in bindings)


def functional_sql_payloads(queries: Sequence[HnswEvaluationQuery]) -> dict[str, tuple[str, ...]]:
    """Two fixed classes, at most two exact public binding payloads per class."""
    if not 1 <= len(queries) <= 2:
        raise ExperimentRefusal("functional_binding_count")
    explain: list[str] = []
    candidates: list[str] = []
    prefix = f'SET ROLE "{READ_ROLE}";\n'
    for query in queries:
        query.validate()
        explain.append(prefix + build_hnsw_explain_sql(
            query.candidate_query, source_scope=query.public_source_scope,
            ann_scan_limit=query.ann_scan_limit,
        ))
        candidates.append(prefix + build_hnsw_query_sql(
            query.candidate_query, source_scope=query.public_source_scope,
            ann_scan_limit=query.ann_scan_limit,
        ))
    return {"ann_explain":tuple(explain),"ann_candidates":tuple(candidates)}


class FunctionalPostgres:
    """Keep fixture connection arguments and route only its psql executable."""

    def __init__(self, database: Any, adapter: FunctionalAdapter) -> None:
        self.adapter = adapter
        self.psql_command = str(adapter.command)
        self.psql_args: Sequence[str] = database.psql_args

    def psql_scalar(self, sql: str) -> str:
        result = run_psql([self.psql_command,*self.psql_args,"-qAt","-v","ON_ERROR_STOP=1"], input_text=sql)
        return result.stdout.strip()


def observe_default_reader_session(postgres: FunctionalPostgres) -> dict[str, object]:
    """A disclosed separate session, never proof of EXPLAIN's own settings."""
    raw = postgres.psql_scalar(
        f'SET ROLE "{READ_ROLE}"; BEGIN READ ONLY; '
        "SELECT json_build_object('reader_role',current_user='w5_experiment_reader',"
        "'transaction_read_only',current_setting('transaction_read_only'),"
        "'enable_seqscan',current_setting('enable_seqscan'),"
        "'enable_sort',current_setting('enable_sort')); COMMIT;"
    )
    result = json.loads(raw)
    if type(result) is not dict or result.get("reader_role") is not True or (
        result.get("transaction_read_only") != "on" or result.get("enable_seqscan") != "on"
        or result.get("enable_sort") != "on"
    ):
        raise ExperimentRefusal("functional_default_reader_session")
    return {"kind":"separate_session_observation",**result}


__all__ = ["FunctionalPostgres","functional_hnsw_queries","functional_sql_payloads","observe_default_reader_session"]
