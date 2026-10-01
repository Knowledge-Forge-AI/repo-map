"""Same-input source/feed parity: SQLite Local adapter vs PostgreSQL owners (PRODUCT3-SQLITE-LOCAL5).

Four real offline feed acquisitions (``acquire_feed_runs``) are canonicalized
once per generation by the production ``build_staged_rows`` and the same
validated bundle is published by the SQLite Local publisher and by the
incumbent staged PostgreSQL publisher into a disposable C-collation database
under the same ``graph:`` root. Generation 2 re-extracts generation 1 and adds
a later parse-error run, so "latest run" moves and fan-out counts double.
After each generation every source/feed operation of the real
``SqliteSourceReadStore`` (one read-only snapshot per call) is compared with
the maintained PostgreSQL owners ``query_ingested_source_records``,
``query_source_summary``, ``query_source_run_records``,
``query_source_feed_item_records``, ``query_source_reference_records`` and
``query_source_feed_item_explanation`` over every filter, limit and absent
case. Records must be equal and their public JSON must be byte-identical; the
explanation is compared as exact JSON text, so key order counts.

A second, comparison-only graph (``crafted_feed_observations``: real
extraction re-annotated, never acceptance data) reaches paths real feeds do
not: missing acquisition times and run ids, byte lengths and HTTP statuses
spelled as text, ``link``/``enclosure`` reference scopes and ``not_fetched`` /
``duplicate_identity`` spellings and defaults.

No value is normalized: none of the six outputs carries a publication run id
or timestamp. Where PostgreSQL leaves tied rows unordered, the test asserts
the tied rows are payload-identical, so the parity cannot silently depend on
an unspecified order.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from itertools import groupby
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.server.source_read_store import (
    IngestedSourcesQuery,
    SourceFeedItemExplanationQuery,
    SourceFeedItemsQuery,
    SourceReferencesQuery,
    SourceRunsQuery,
    SourceSummaryQuery,
)
from repomap_kg.server.sqlite_read_binding import SqliteSourceReadStore
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    ingested_source_records_to_jsonable,
    query_ingested_source_records,
    query_source_feed_item_explanation,
    query_source_feed_item_records,
    query_source_reference_records,
    query_source_run_records,
    query_source_summary,
    source_feed_item_records_to_jsonable,
    source_reference_records_to_jsonable,
    source_run_records_to_jsonable,
    source_summary_to_jsonable,
)
from repomap_kg.storage.readback_driver import READBACK_DRIVER_ENV
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database, read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.source_queries import source_observations
from repomap_test_support.portable_publication_fixtures import authority, binding, publish_portable_bundle
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.sqlite_local_feed_corpus import (
    RSS,
    SECRET_MARKERS,
    acquire_feed_runs,
    crafted_feed_observations,
    feed_bundle,
    generation_observations,
)
from repomap_test_support.sqlite_local_fixtures import local_binding, publication_for

FEEDS, CRAFTED = "feed-parity", "feed-crafted"
C_COLLATIONS = frozenset({"C", "POSIX", "C.UTF-8", "C.utf8"})
ABSENT_SOURCE, ABSENT_RUN = "no-such-source", "no-such-run"
ABSENT_ITEM = "feed.item:feed.channel%3Aabsent:guid%3Anone"
TARGET_KINDS = (None, "feed.author", "feed.category", "external.url", "file", "no-kind")
SERIALIZERS: dict[str, Callable[..., Any]] = {
    "ingested": ingested_source_records_to_jsonable,
    "runs": source_run_records_to_jsonable,
    "items": source_feed_item_records_to_jsonable,
    "references": source_reference_records_to_jsonable,
}


def test_feed_publications_match_postgresql_source_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_postgres_binaries()
    for name in ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    with temporary_postgres() as postgres:
        name = f"sqlite_source_differential_{uuid.uuid4().hex[:10]}"
        postgres.psql_scalar(
            f'CREATE DATABASE "{name}" WITH TEMPLATE template0 ENCODING \'UTF8\' '
            "LC_COLLATE 'C' LC_CTYPE 'C';"
        )
        try:
            database = replace(postgres, database=name)
            if getattr(database, "password", None) is not None:
                monkeypatch.setenv("PGPASSWORD", database.password)
            _prove(tmp_path, database)
        finally:
            postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


class _Pair:
    """One logical graph published to both backends from the same bundles."""

    def __init__(self, tmp_path: Path, database: Any, graph: str) -> None:
        self.database, self.graph, self.root = database, graph, f"graph:{graph}"
        self.path = tmp_path / f"{graph}.sqlite3"
        self.binding = local_binding(graph)
        initialize_graph_database(self.path, self.binding, applied_at="2026-09-29T00:00:00Z")
        self.store = SqliteSourceReadStore(self.path, self.binding)
        self.compared = 0

    def publish(self, generation: int, observations: Sequence[Any]) -> None:
        bundle = feed_bundle(self.graph, generation, observations)
        publish_generation(self.path, publication_for(bundle, self.graph), bundle.families,
                           expected_generation=generation - 1)
        # Each PostgreSQL generation is a newer coordinator claim: fencing epochs advance.
        claim = replace(authority(bundle), singleton_fencing_epoch=6 + generation,
                        graph_lease_fencing_epoch=8 + generation)
        publish_portable_bundle(self.database.psql_args, bundle, repository_name=self.graph,
                                root_path=self.root, authority_override=claim,
                                binding_override=binding(bundle, claim))

    def pg(self, owner: Callable[..., Any], **arguments: Any) -> Any:
        return owner(self.database.psql_args, root_path=self.root,
                     psql_command=self.database.psql_command, **arguments)

    def same(self, label: str, actual: Any, expected: Any, serializer: Callable[..., Any] | None) -> Any:
        assert actual == expected, (self.graph, label, actual, expected)
        if serializer is not None:
            left, right = json.dumps(serializer(actual)), json.dumps(serializer(expected))
        else:
            left, right = json.dumps(actual), json.dumps(expected)
        assert left == right, (self.graph, label, left, right)
        assert not any(marker in left for marker in SECRET_MARKERS), (self.graph, label)
        self.compared += 1
        return actual


def _ingested(pair: _Pair) -> list[str]:
    sources: list[str] = []
    for source_type in (None, "feed.rss", "feed.atom", "feed.json", "nope"):
        for policy in (None, "allowed", "allowed_with_limits"):
            for limit in (50, 1):
                actual = pair.store.ingested_sources(IngestedSourcesQuery(source_type, policy, limit))
                expected = pair.pg(query_ingested_source_records, source_type=source_type,
                                   policy_status=policy, limit=limit)
                rows = pair.same(f"ingested {source_type} {policy} {limit}", actual, expected,
                                 SERIALIZERS["ingested"])
                if (source_type, policy, limit) == (None, None, 50):
                    sources = [row.source_id for row in rows]
    assert sources, pair.graph  # never a zero-vs-zero comparison
    return sources


def _source(pair: _Pair, source_id: str) -> tuple[list[str], list[str]]:
    summary = pair.same(f"summary {source_id}", pair.store.source_summary(SourceSummaryQuery(source_id)),
                        pair.pg(query_source_summary, source_id=source_id), source_summary_to_jsonable)
    assert summary.source_id == source_id
    run_ids: list[str] = []
    for limit in (25, 1):
        runs = pair.same(f"runs {source_id} {limit}",
                         pair.store.source_runs(SourceRunsQuery(source_id, limit)),
                         pair.pg(query_source_run_records, source_id=source_id, limit=limit),
                         SERIALIZERS["runs"])
        run_ids = run_ids or [run.source_run_id for run in runs]
    item_keys: list[str] = []
    for run in (None, *run_ids, ABSENT_RUN):
        for limit in (50, 1):
            items = pair.same(
                f"items {source_id} {run} {limit}",
                pair.store.source_feed_items(SourceFeedItemsQuery(source_id, run, limit)),
                pair.pg(query_source_feed_item_records, source_id=source_id, source_run_id=run, limit=limit),
                SERIALIZERS["items"],
            )
            if run is None and limit == 50:
                item_keys = [item.item_key for item in items]
        for kind in TARGET_KINDS:
            for limit in (100, 1):
                references = pair.same(
                    f"references {source_id} {run} {kind} {limit}",
                    pair.store.source_references(SourceReferencesQuery(source_id, run, kind, limit)),
                    pair.pg(query_source_reference_records, source_id=source_id, source_run_id=run,
                            target_kind=kind, limit=limit),
                    SERIALIZERS["references"],
                )
                _ties_identical(
                    references, lambda row: (row.source_item_key, row.target_key), "references")
    return run_ids, item_keys


def _explanations(pair: _Pair, sources: list[str], item_keys: list[str]) -> int:
    explained = 0
    for key in (*item_keys, ABSENT_ITEM):
        for source_id in (None, *sources, ABSENT_SOURCE):
            actual = pair.store.source_feed_item_explanation(SourceFeedItemExplanationQuery(key, source_id))
            expected = pair.pg(query_source_feed_item_explanation, item_key=key, source_id=source_id)
            payload = pair.same(f"explain {key} {source_id}", actual, expected, None)
            _ties_identical(payload["evidence"], lambda row: _ordinal(row), "evidence")
            _ties_identical(payload["references"], lambda row: row["target_key"], "explained references")
            explained += payload["item"] is not None and bool(payload["evidence"])
    return explained


def _ordinal(row: dict[str, Any]) -> str:
    """The PostgreSQL evidence ORDER BY key, recovered from ``evidence:<ordinal>:...``."""
    return str(row["evidence_key"]).split(":", 2)[1]


def _ties_identical(rows: Sequence[Any], key: Callable[[Any], Any], label: str) -> None:
    """Rows PostgreSQL leaves unordered must be payload-identical, or parity is luck."""
    for group_key, group in groupby(rows, key=key):
        payloads = [json.dumps(row if isinstance(row, dict) else asdict(row), sort_keys=True) for row in group]
        assert len(set(payloads)) == 1, (label, group_key, payloads)


def _latest_ties(pair: _Pair) -> None:
    """``ARRAY_AGG(... ORDER BY acquired DESC NULLS LAST)[1]`` and explanation-source ties."""
    with read_transaction(pair.path, pair.binding) as connection:
        observations = source_observations(connection)
    maxima: dict[str, str | None] = {}
    for source_id in {item.source_id for item in observations}:
        group = [item for item in observations if item.source_id == source_id]
        dated = [item.acquired_at for item in group if item.acquired_at is not None]
        newest = max(dated) if dated else None
        firsts = {(item.source_run_id, item.artifact_id, item.artifact_path)
                  for item in group if item.acquired_at == newest}
        assert len(firsts) == 1, (pair.graph, source_id, firsts)
        maxima[source_id] = newest
    present = [value for value in maxima.values() if value is not None]
    assert len(present) == len(set(present)), (pair.graph, maxima)


def _prove(tmp_path: Path, database: Any) -> None:
    collation = database.psql_scalar("SELECT datcollate || '|' || datctype FROM pg_database "
                                     "WHERE datname = current_database();")
    assert set(collation.split("|")) <= C_COLLATIONS, f"comparator is not byte-ordered C: {collation}"
    apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    runs = acquire_feed_runs(tmp_path / "feed-root")
    feeds = _Pair(tmp_path, database, FEEDS)
    for generation in (1, 2):
        feeds.publish(generation, generation_observations(runs, generation))
        _latest_ties(feeds)
        sources = _ingested(feeds)
        assert len(sources) == 3, sources
        keys: list[str] = []
        for source_id in (*sources, ABSENT_SOURCE):
            run_ids, item_keys = _source(feeds, source_id)
            keys += item_keys
            if source_id == RSS:
                assert len(run_ids) == generation, (generation, run_ids)
        assert len(keys) >= 8, keys
        assert _explanations(feeds, sources, keys) >= len(keys), generation
    rss = feeds.store.source_summary(SourceSummaryQuery(RSS))
    assert rss.latest_source_run_id == runs["rss2"].source_run_id and rss.parse_errors == 1, rss
    statuses = [run.status_summary for run in feeds.store.source_runs(SourceRunsQuery(RSS, 25))]
    assert statuses == ["parse_errors", "ok"], statuses

    crafted = _Pair(tmp_path, database, CRAFTED)
    crafted.publish(1, crafted_feed_observations())
    _latest_ties(crafted)
    sources = _ingested(crafted)
    keys = []
    for source_id in (*sources, ABSENT_SOURCE):
        keys += _source(crafted, source_id)[1]
    assert _explanations(crafted, sources, keys) >= len(keys)
    alpha = crafted.store.source_summary(SourceSummaryQuery("crafted-alpha"))
    assert alpha.link_references > 0 and alpha.enclosure_references > 0, alpha
    assert alpha.latest_source_run_id is None and alpha.latest_acquired_at is not None, alpha
    alpha_runs = crafted.store.source_runs(SourceRunsQuery("crafted-alpha", 25))
    assert [(run.acquired_at is None, run.artifact_byte_length, run.http_status) for run in alpha_runs] == [
        (False, 1000, 201), (True, None, None)], alpha_runs
    references = crafted.store.source_references(SourceReferencesQuery("crafted-alpha", None, None, 100))
    assert {row.not_fetched for row in references} == {True, False}, references
    items = crafted.store.source_feed_items(SourceFeedItemsQuery("crafted-alpha", None, 50))
    assert any(item.link_targets for item in items), items
    assert {item.duplicate_identity for item in items} == {True, False}, items
    assert feeds.compared > 400 and crafted.compared > 150, (feeds.compared, crafted.compared)
