"""Single-statement PostgreSQL query execution for cloe_lexical query styles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any

from common_lore_index.retrieval.lexical_policy import normalize_lexical_path_prefix
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchone,
)
from common_lore_index.storage.lexical_fence_sql import (
    LATERAL_EVIDENCE_LINK_SQL,
    LEXICAL_FENCE_CTE_SQL,
)
from common_lore_index.storage.lexical_literal_sql import (
    DEFAULT_MAX_OCCURRENCES_PER_FILE,
    LITERAL_CAPTURED_TEXT_QUERY_SQL,
)

ALLOWED_LEXICAL_QUERY_STYLES = frozenset(
    {
        "ranked_terms",
        "normalized_phrase",
        "literal_captured_text",
    }
)

_QUERY_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_QUERY_DELIM_RE = re.compile(r"[/_.:-]+")
_QUERY_CAMEL_1_RE = re.compile(r"([a-z0-9])([A-Z])")
_QUERY_CAMEL_2_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_QUERY_TOKEN_RE = re.compile(r"^[a-z0-9]{2,64}$")


def _build_alias_query_text(query_text: str) -> str:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _QUERY_CANDIDATE_RE.finditer(query_text):
        for part in _QUERY_DELIM_RE.split(match.group(0)):
            if not part:
                continue
            step1 = _QUERY_CAMEL_2_RE.sub(r"\1 \2", part)
            step2 = _QUERY_CAMEL_1_RE.sub(r"\1 \2", step1)
            for sub in step2.split(" "):
                low = sub.lower()
                if _QUERY_TOKEN_RE.fullmatch(low) is not None and low not in seen:
                    seen.add(low)
                    tokens.append(low)
    return " ".join(tokens)


def _build_fts_query_sql(
    *, tsquery_fn: str, vector_col: str, include_alias_query: bool = False
) -> str:
    if include_alias_query:
        tsquery_expr = (
            f"CASE "
            f"WHEN numnode(plainto_tsquery('pg_catalog.simple'::regconfig, %(alias_query_text)s)) > 0 "
            f"AND numnode({tsquery_fn}('pg_catalog.simple'::regconfig, %(query_text)s)) > 0 "
            f"THEN {tsquery_fn}('pg_catalog.simple'::regconfig, %(query_text)s) "
            f"|| plainto_tsquery('pg_catalog.simple'::regconfig, %(alias_query_text)s) "
            f"WHEN numnode({tsquery_fn}('pg_catalog.simple'::regconfig, %(query_text)s)) > 0 "
            f"THEN {tsquery_fn}('pg_catalog.simple'::regconfig, %(query_text)s) "
            f"ELSE plainto_tsquery('pg_catalog.simple'::regconfig, %(alias_query_text)s) "
            f"END"
        )
    else:
        tsquery_expr = f"{tsquery_fn}('pg_catalog.simple'::regconfig, %(query_text)s)"
    return f"""
WITH
{LEXICAL_FENCE_CTE_SQL},
parsed_tsquery AS MATERIALIZED (
    SELECT
        {tsquery_expr} AS q
),
raw_matched_chunks AS MATERIALIZED (
    SELECT
        ch.repository_id,
        ch.lexical_generation_id,
        ag.gen_run_id AS run_id,
        ag.representation_version,
        ch.binding_id,
        ch.source_relative_path,
        ch.chunk_ordinal,
        ch.start_line,
        ch.end_line,
        ch.chunk_id,
        ch.chunk_sha256,
        ch.artifact_privacy,
        ch.{vector_col} AS match_vec
    FROM cloe_lexical.chunks ch
    JOIN admitted_generation ag
      ON ag.repository_id = ch.repository_id
     AND ag.lexical_generation_id = ch.lexical_generation_id
    CROSS JOIN parsed_tsquery tq
    WHERE ch.binding_id = ANY(%(admitted_binding_ids)s::text[])
      AND (
          cardinality(%(path_prefixes)s::text[]) = 0
          OR EXISTS (
              SELECT 1
              FROM unnest(%(path_prefixes)s::text[]) AS p(prefix)
               WHERE ch.source_relative_path = p.prefix OR
                     left(ch.source_relative_path, length(p.prefix) + 1) = p.prefix || '/'
          )
      )
      AND numnode(tq.q) > 0
      AND ch.{vector_col} @@ tq.q
    ORDER BY
        ch.binding_id COLLATE "C" ASC,
        ch.source_relative_path COLLATE "C" ASC,
        ch.chunk_ordinal ASC
    LIMIT 5001
),
candidate_budget AS MATERIALIZED (
    SELECT
        (
            count(*) > 5000
            OR count(DISTINCT (rmc.binding_id, rmc.source_relative_path)) > 1000
        ) AS overflowed
    FROM raw_matched_chunks rmc
),
matched_chunks AS MATERIALIZED (
    SELECT
        ch.repository_id,
        ch.lexical_generation_id,
        ch.run_id,
        ch.representation_version,
        ch.binding_id,
        ch.source_relative_path,
        ch.start_line,
        ch.end_line,
        ch.chunk_id,
        ch.chunk_sha256,
        ch.artifact_privacy,
        round(
            ts_rank_cd(
                '{{0.1, 0.2, 0.4, 1.0}}'::real[],
                ch.match_vec,
                tq.q,
                32
            )::numeric,
            8
        )::double precision AS score
    FROM (SELECT * FROM raw_matched_chunks LIMIT 5000) ch
    CROSS JOIN parsed_tsquery tq
    ORDER BY
        score DESC,
        ch.binding_id COLLATE "C" ASC,
        ch.source_relative_path COLLATE "C" ASC,
        ch.start_line ASC,
        ch.end_line ASC,
        ch.chunk_id COLLATE "C" ASC
),
paged AS MATERIALIZED (
    SELECT *
    FROM matched_chunks
    OFFSET %(offset)s
    LIMIT %(limit)s
),
enriched_hits AS MATERIALIZED (
    SELECT
        paged.binding_id,
        paged.source_relative_path,
        paged.start_line,
        paged.end_line,
        paged.chunk_id,
        paged.chunk_sha256,
        paged.representation_version,
        paged.artifact_privacy,
        paged.score,
        ev.canonical_key,
        ev.evidence_key,
        ev.link_kind
    FROM paged
    {LATERAL_EVIDENCE_LINK_SQL}
    ORDER BY
        paged.score DESC,
        paged.binding_id COLLATE "C" ASC,
        paged.source_relative_path COLLATE "C" ASC,
        paged.start_line ASC,
        paged.end_line ASC,
        paged.chunk_id COLLATE "C" ASC
)
SELECT json_build_object(
    'fence_status', (SELECT status FROM fence_state),
    'lexical_generation_id', (SELECT active_generation_id FROM fence_state),
    'latest_generation_id', (SELECT latest_generation_id FROM fence_state),
    'latest_revocation_reason', (SELECT latest_revocation_reason FROM fence_state),
    'run_id', (SELECT live_run_id FROM fence_state),
    'publication_bundle_id', (SELECT live_bundle_id FROM fence_state),
    'snapshot_manifest_id', (SELECT live_manifest_id FROM fence_state),
    'extraction_receipt_id', (SELECT live_receipt_id FROM fence_state),
    'graph_candidate_id', (SELECT live_candidate_id FROM fence_state),
    'empty_tsquery', (SELECT numnode(q) = 0 FROM parsed_tsquery),
    'total_matches', (SELECT count(*)::int FROM matched_chunks),
    'candidate_overflow', COALESCE((SELECT overflowed FROM candidate_budget), false),
    'capped_files', '[]'::json,
    'omissions', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'binding_id', so.binding_id,
                    'source_relative_path', so.source_relative_path,
                    'reason_code', so.reason_code,
                    'detail', so.detail
                )
                ORDER BY so.omission_ordinal ASC
            )
            FROM scoped_omissions so
        ),
        '[]'::json
    ),
    'hits', COALESCE(
        (
            SELECT json_agg(row_to_json(eh) ORDER BY
                eh.score DESC, eh.binding_id COLLATE "C" ASC,
                eh.source_relative_path COLLATE "C" ASC, eh.start_line ASC,
                eh.end_line ASC, eh.chunk_id COLLATE "C" ASC)
            FROM enriched_hits eh
        ),
        '[]'::json
    )
)::text
"""


RANKED_TERMS_QUERY_SQL = _build_fts_query_sql(
    tsquery_fn="websearch_to_tsquery",
    vector_col="ranked_vector",
    include_alias_query=True,
)

NORMALIZED_PHRASE_QUERY_SQL = _build_fts_query_sql(
    tsquery_fn="phraseto_tsquery",
    vector_col="phrase_vector",
)


@dataclass(frozen=True)
class RawLexicalQueryRow:
    """Decoded single-statement payload from a cloe_lexical query execution."""

    fence_status: str
    lexical_generation_id: str | None
    latest_generation_id: str | None
    latest_revocation_reason: str | None
    run_id: int | None
    publication_bundle_id: str | None
    snapshot_manifest_id: str | None
    extraction_receipt_id: str | None
    graph_candidate_id: str | None
    empty_tsquery: bool
    total_matches: int
    capped_files: tuple[tuple[str, str], ...]
    omissions: tuple[Mapping[str, Any], ...]
    hits: tuple[Mapping[str, Any], ...]
    candidate_overflow: bool = False


def execute_single_statement_lexical_query(
    connection: Any,
    *,
    query_style: str,
    query_text: str,
    repository_identity: str | None,
    repository_name: str | None,
    root_path: str | None,
    expected_policy_digest: str,
    expected_binding_policy_digests_json: str,
    admitted_binding_ids: Sequence[str],
    omission_binding_ids: Sequence[str],
    path_prefixes: Sequence[str] = (),
    limit: int = 50,
    offset: int = 0,
    max_occurrences_per_file: int = DEFAULT_MAX_OCCURRENCES_PER_FILE,
    privacy_excluded_bindings_json: str = "{}",
) -> RawLexicalQueryRow:
    """Execute one lexical query style in a single SQL statement."""
    if query_style == "ranked_terms":
        sql = RANKED_TERMS_QUERY_SQL
    elif query_style == "normalized_phrase":
        sql = NORMALIZED_PHRASE_QUERY_SQL
    elif query_style == "literal_captured_text":
        sql = LITERAL_CAPTURED_TEXT_QUERY_SQL
    else:
        raise LexicalStorageError(
            "lexical_unsupported_query_style",
            f"unsupported lexical query_style {query_style!r}",
        )

    params: dict[str, Any] = {
        "repository_identity": repository_identity,
        "repository_name": repository_name,
        "root_path": root_path,
        "expected_policy_digest": expected_policy_digest,
        "expected_binding_policy_digests_json": expected_binding_policy_digests_json,
        "privacy_excluded_bindings_json": privacy_excluded_bindings_json,
        "admitted_binding_ids": list(admitted_binding_ids),
        "omission_binding_ids": list(omission_binding_ids),
        "path_prefixes": list(dict.fromkeys(normalize_lexical_path_prefix(p) for p in path_prefixes)),
        "query_text": query_text,
        "alias_query_text": _build_alias_query_text(query_text),
        "limit": int(limit),
        "offset": int(offset),
        "max_occurrences_per_file": int(max_occurrences_per_file),
    }
    row = execute_fetchone(
        connection,
        sql,
        params,
        operation=f"lexical_query_{query_style}",
    )
    if row is None or not row[0]:
        raise LexicalStorageError(
            "lexical_empty_query_response",
            "PostgreSQL lexical query returned an empty row",
        )
    try:
        payload = json.loads(str(row[0]))
    except (TypeError, ValueError) as error:
        raise LexicalStorageError(
            "lexical_invalid_query_json",
            "PostgreSQL lexical query returned invalid JSON",
        ) from error

    capped = tuple(
        (str(item["binding_id"]), str(item["source_relative_path"]))
        for item in (payload.get("capped_files") or ())
        if isinstance(item, Mapping)
    )
    return RawLexicalQueryRow(
        fence_status=str(payload["fence_status"]),
        lexical_generation_id=(
            str(payload["lexical_generation_id"])
            if payload.get("lexical_generation_id") is not None
            else None
        ),
        latest_generation_id=(
            str(payload["latest_generation_id"])
            if payload.get("latest_generation_id") is not None
            else None
        ),
        latest_revocation_reason=(
            str(payload["latest_revocation_reason"])
            if payload.get("latest_revocation_reason") is not None
            else None
        ),
        run_id=int(payload["run_id"]) if payload.get("run_id") is not None else None,
        publication_bundle_id=(
            str(payload["publication_bundle_id"])
            if payload.get("publication_bundle_id") is not None
            else None
        ),
        snapshot_manifest_id=(
            str(payload["snapshot_manifest_id"])
            if payload.get("snapshot_manifest_id") is not None
            else None
        ),
        extraction_receipt_id=(
            str(payload["extraction_receipt_id"])
            if payload.get("extraction_receipt_id") is not None
            else None
        ),
        graph_candidate_id=(
            str(payload["graph_candidate_id"])
            if payload.get("graph_candidate_id") is not None
            else None
        ),
        empty_tsquery=bool(payload.get("empty_tsquery", False)),
        total_matches=int(payload.get("total_matches", 0)),
        capped_files=capped,
        omissions=tuple(payload.get("omissions") or ()),
        hits=tuple(payload.get("hits") or ()),
        candidate_overflow=bool(payload.get("candidate_overflow", False)),
    )


__all__ = [
    "ALLOWED_LEXICAL_QUERY_STYLES",
    "NORMALIZED_PHRASE_QUERY_SQL",
    "RANKED_TERMS_QUERY_SQL",
    "RawLexicalQueryRow",
    "execute_single_statement_lexical_query",
]
