"""SQLite Local source/feed reads over real offline feed publications (PRODUCT3-SQLITE-LOCAL5).

Four real offline acquisitions (``acquire_feed_runs``) are published through
the production canonicalizer and the SQLite Local publisher as two
generations. Expected values come from the acquisition summaries and the
checked-in fixture bodies, not from the reader: source identity and policy,
the latest-run transition, run artifacts and statuses, item order with
undated items last, author/category/link references, filters, limits,
absent and non-matching cases, and the explanation shape. The comparison-only
crafted corpus covers NULL and default paths real feeds never reach.
Same-input equality with the PostgreSQL owners is the integration claim.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.source import FeedIngestionSummary
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sqlite_local import source_feed_queries, source_queries
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database, read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.sqlite_local_feed_corpus import (
    ATOM,
    RSS,
    SECRET,
    SECRET_MARKERS,
    acquire_feed_runs,
    crafted_feed_observations,
    feed_bundle,
    generation_observations,
)
from repomap_test_support.sqlite_local_fixtures import local_binding, publication_for

GRAPH = "feed-unit"
BINDING = local_binding(GRAPH)
ABSENT_ITEM = "feed.item:feed.channel%3Aabsent:guid%3Anone"


def _database(tmp_path: Path, name: str = GRAPH) -> Path:
    path = tmp_path / f"{name}.sqlite3"
    initialize_graph_database(path, local_binding(name), applied_at="2026-09-29T00:00:00Z")
    return path


def _publish(path: Path, generation: int, observations: tuple[RawObservation, ...], name: str = GRAPH) -> None:
    bundle = feed_bundle(name, generation, observations)
    publish_generation(path, publication_for(bundle, name), bundle.families, expected_generation=generation - 1)


@pytest.fixture
def feeds(tmp_path: Path) -> tuple[Path, dict[str, FeedIngestionSummary]]:
    runs = acquire_feed_runs(tmp_path / "feed-root")
    path = _database(tmp_path)
    _publish(path, 1, generation_observations(runs, 1))
    return path, runs


def _read(path: Path, name: str = GRAPH) -> Any:
    return read_transaction(path, local_binding(name))


def _everything(connection: Any, sources: tuple[str, ...]) -> str:
    """Every operation's output as one JSON text, for the privacy scan."""
    out: list[Any] = [asdict(row) for row in source_queries.ingested_sources(
        connection, source_type=None, policy_status=None, limit=50)]
    for source_id in sources:
        out.append(asdict(source_queries.source_summary(connection, source_id=source_id)))
        out += [asdict(row) for row in source_queries.source_runs(connection, source_id=source_id, limit=25)]
        items = source_feed_queries.source_feed_items(connection, source_id=source_id, source_run_id=None, limit=50)
        out += [asdict(row) for row in items]
        out += [asdict(row) for row in source_feed_queries.source_references(
            connection, source_id=source_id, source_run_id=None, target_kind=None, limit=100)]
        out += [source_feed_queries.source_feed_item_explanation(connection, item_key=item.item_key, source_id=None)
                for item in items]
    return json.dumps(out)


def test_inventory_summary_and_runs_follow_the_acquisitions(
    feeds: tuple[Path, dict[str, FeedIngestionSummary]],
) -> None:
    path, runs = feeds
    rss1 = runs["rss1"]
    with _read(path) as connection:
        inventory = source_queries.ingested_sources(connection, source_type=None, policy_status=None, limit=50)
        assert [row.source_id for row in inventory] == [ATOM, RSS, SECRET]  # source-id order
        by_id = {row.source_id: row for row in inventory}
        assert (by_id[RSS].source_type, by_id[RSS].display_name, by_id[RSS].policy_status) == (
            "feed.rss", "Example RSS Feed", "allowed_with_limits")
        assert (by_id[ATOM].source_type, by_id[ATOM].policy_status) == ("feed.atom", "allowed")
        assert by_id[SECRET].source_type == "feed.json"
        assert (by_id[RSS].latest_source_run_id, by_id[RSS].latest_artifact_path) == (
            rss1.source_run_id, rss1.artifact_path)
        assert by_id[RSS].latest_acquired_at == "2026-06-30T12:00:00Z"
        assert [by_id[key].canonical_feed_item_count for key in (ATOM, RSS, SECRET)] == [2, 5, 1]
        # COUNT(*) over the evidence x node-link fan-out, never below the raw rows.
        assert by_id[RSS].feed_observation_count >= rss1.observations
        filtered = source_queries.ingested_sources(connection, source_type="feed.atom", policy_status=None, limit=50)
        assert [row.source_id for row in filtered] == [ATOM]
        allowed = source_queries.ingested_sources(connection, source_type=None, policy_status="allowed", limit=50)
        assert [row.source_id for row in allowed] == [ATOM]
        assert [row.source_id for row in source_queries.ingested_sources(
            connection, source_type=None, policy_status=None, limit=1)] == [ATOM]
        assert source_queries.ingested_sources(connection, source_type="nope", policy_status=None, limit=5) == ()

        summary = source_queries.source_summary(connection, source_id=RSS)
        assert summary.configured_url_summary == "https://example.invalid/rss.xml"
        assert (summary.feed_documents, summary.feed_channels, summary.feed_items) == (1, 1, 5)
        assert (summary.feed_authors, summary.feed_categories, summary.parse_errors) == (1, 1, 0)
        # The extractor writes item/channel scopes; the maintained contract counts link/enclosure.
        assert (summary.link_references, summary.enclosure_references) == (0, 0)
        assert summary.known_limitations == ("source metadata is inferred from RSS2 evidence",)

        (run,) = source_queries.source_runs(connection, source_id=RSS, limit=25)
        assert (run.source_run_id, run.artifact_path, run.artifact_sha256) == (
            rss1.source_run_id, rss1.artifact_path, rss1.artifact_sha256)
        assert (run.artifact_id, run.artifact_byte_length) == (rss1.artifact_sha256[:16], rss1.artifact_bytes)
        assert (run.http_status, run.content_type) == (200, "application/rss+xml")
        assert (run.observation_count, run.status_summary) == (rss1.observations, "ok")


def test_feed_items_references_and_explanations(feeds: tuple[Path, dict[str, FeedIngestionSummary]]) -> None:
    path, runs = feeds
    with _read(path) as connection:
        items = source_feed_queries.source_feed_items(connection, source_id=RSS, source_run_id=None, limit=50)
        assert [item.title for item in items] == [
            "RSS Weak Fallback", "RSS Link Fallback", "RSS GUID Item", "RSS Duplicate A", "RSS Duplicate B"]
        assert [item.published_at is None for item in items] == [False, False, False, True, True]
        guid = items[2]
        assert (guid.authors, guid.categories, guid.identity_source) == (("RSS Writer",), ("Release Notes",), "guid")
        assert [item.duplicate_identity for item in items] == [False, False, False, True, True]
        assert items[0].identity_strength == "weak" and all(not item.link_targets for item in items)
        assert {(item.source_run_id, item.artifact_path) for item in items} == {
            (runs["rss1"].source_run_id, runs["rss1"].artifact_path)}
        assert source_feed_queries.source_feed_items(
            connection, source_id=RSS, source_run_id=None, limit=2) == items[:2]

        references = source_feed_queries.source_references(
            connection, source_id=RSS, source_run_id=None, target_kind=None, limit=50)
        assert [(row.source_item_key, row.target_key) for row in references] == sorted(
            (row.source_item_key, row.target_key) for row in references)
        assert {row.target_key.split(":", 1)[0] for row in references} == {
            "external.url", "feed.author", "feed.category", "file"}
        enclosure = next(row for row in references if row.target_key.endswith("/media/rss-audio.mp3"))
        assert (enclosure.media_type, enclosure.not_fetched, enclosure.relation) == ("audio/mpeg", True, "references")
        assert enclosure.target_display == "media/rss-audio.mp3"
        authors = source_feed_queries.source_references(
            connection, source_id=RSS, source_run_id=None, target_kind="feed.author", limit=50)
        assert [row.source_item_key for row in authors] == [guid.item_key]
        assert source_feed_queries.source_references(
            connection, source_id=RSS, source_run_id="no-such-run", target_kind=None, limit=50) == ()

        explained = source_feed_queries.source_feed_item_explanation(connection, item_key=guid.item_key, source_id=None)
        assert list(explained) == ["item", "source", "evidence", "references", "content_policy"]
        assert explained["content_policy"] == "full feed bodies are not exposed"
        assert explained["item"]["canonical_key"] == guid.item_key and explained["item"]["conflict"] is False
        assert explained["item"]["metadata"]["title"] == "RSS GUID Item"
        assert explained["source"]["source_id"] == RSS  # the newest source overall, not tied to the item
        assert explained["evidence"] and all(row["raw_kind"] for row in explained["evidence"])
        assert [row["target_key"] for row in explained["references"]] == sorted(
            row.target_key for row in references if row.source_item_key == guid.item_key)
        other = source_feed_queries.source_feed_item_explanation(connection, item_key=guid.item_key, source_id=ATOM)
        # A non-matching source: no item or evidence, but references are not source-filtered.
        assert (other["item"], other["evidence"], other["source"]["source_id"]) == (None, [], ATOM)
        assert other["references"] == explained["references"]
        absent = source_feed_queries.source_feed_item_explanation(connection, item_key=ABSENT_ITEM, source_id=None)
        assert (absent["item"], absent["evidence"], absent["references"]) == (None, [], [])
        assert absent["source"]["source_id"] == RSS

        missing = source_queries.source_summary(connection, source_id="no-such-source")
        assert (missing.policy_status, missing.source_type, missing.feed_items) == ("unknown", "unknown", 0)
        assert missing.known_limitations == ("source metadata unavailable",)
        assert source_queries.source_runs(connection, source_id="no-such-source", limit=5) == ()
        assert source_feed_queries.source_feed_items(
            connection, source_id="no-such-source", source_run_id=None, limit=5) == ()
        text = _everything(connection, (ATOM, RSS, SECRET))
    assert not any(marker in text for marker in SECRET_MARKERS)
    assert "/" + "Users" not in text and str(path.parent) not in text  # artifact-relative paths only


def test_second_generation_moves_the_latest_run(feeds: tuple[Path, dict[str, FeedIngestionSummary]]) -> None:
    path, runs = feeds
    with _read(path) as connection:
        before = {row.source_id: row for row in source_queries.ingested_sources(
            connection, source_type=None, policy_status=None, limit=50)}
    _publish(path, 2, generation_observations(runs, 2))
    rss1, rss2 = runs["rss1"], runs["rss2"]
    with _read(path) as connection:
        after = {row.source_id: row for row in source_queries.ingested_sources(
            connection, source_type=None, policy_status=None, limit=50)}
        assert (after[RSS].latest_source_run_id, after[RSS].latest_acquired_at) == (
            rss2.source_run_id, "2026-07-01T12:00:00Z")
        assert after[ATOM].latest_source_run_id == before[ATOM].latest_source_run_id
        # Both publications keep their raw rows, so the fan-out doubles; distinct items do not.
        assert after[ATOM].feed_observation_count == 2 * before[ATOM].feed_observation_count
        assert after[RSS].canonical_feed_item_count == before[RSS].canonical_feed_item_count == 5
        runs_after = source_queries.source_runs(connection, source_id=RSS, limit=25)
        assert [(run.source_run_id, run.status_summary) for run in runs_after] == [
            (rss2.source_run_id, "parse_errors"), (rss1.source_run_id, "ok")]
        assert [run.observation_count for run in runs_after] == [rss2.observations, 2 * rss1.observations]
        assert source_queries.source_runs(connection, source_id=RSS, limit=1) == runs_after[:1]
        summary = source_queries.source_summary(connection, source_id=RSS)
        assert (summary.parse_errors, summary.feed_items, summary.latest_source_run_id) == (
            1, 5, rss2.source_run_id)
        assert source_feed_queries.source_feed_items(
            connection, source_id=RSS, source_run_id=rss2.source_run_id, limit=50) == ()
        assert len(source_feed_queries.source_feed_items(
            connection, source_id=RSS, source_run_id=rss1.source_run_id, limit=50)) == 5
        references = source_feed_queries.source_references(
            connection, source_id=RSS, source_run_id=None, target_kind=None, limit=100)
        assert len(references) == 10 and references[0] == references[1]  # one row per publication's evidence


def test_crafted_corpus_reaches_null_and_default_paths(tmp_path: Path) -> None:
    path = _database(tmp_path, "crafted")
    _publish(path, 1, crafted_feed_observations(), name="crafted")
    with _read(path, "crafted") as connection:
        alpha = source_queries.source_summary(connection, source_id="crafted-alpha")
        assert (alpha.link_references, alpha.enclosure_references) == (3, 1)
        assert alpha.latest_source_run_id is None and alpha.latest_acquired_at == "2026-01-03T00:00:00Z"
        assert alpha.source_type == "feed.atom"  # MIN over the group
        beta = source_queries.source_summary(connection, source_id="crafted-beta")
        assert (beta.latest_acquired_at, beta.display_name) == (None, None)
        runs = source_queries.source_runs(connection, source_id="crafted-alpha", limit=25)
        assert [(run.source_run_id, run.artifact_byte_length, run.http_status) for run in runs] == [
            ("r1", 1000, 201), ("r2", None, None)]  # numeric MAX; NULL acquisition last
        assert source_queries.source_runs(connection, source_id="crafted-beta", limit=25) == ()
        allowed = source_queries.ingested_sources(connection, source_type=None, policy_status="allowed", limit=50)
        everything = source_queries.ingested_sources(connection, source_type=None, policy_status=None, limit=50)
        assert [row.feed_observation_count < full.feed_observation_count
                for row, full in zip(allowed, everything, strict=True)] == [True, True]  # filter before GROUP BY
        references = source_feed_queries.source_references(
            connection, source_id="crafted-alpha", source_run_id=None, target_kind=None, limit=50)
        assert {row.not_fetched for row in references} == {True, False}
        items = source_feed_queries.source_feed_items(
            connection, source_id="crafted-alpha", source_run_id=None, limit=50)
        assert {item.duplicate_identity for item in items} == {True, False}
        assert items[2].link_targets == tuple(sorted(items[2].link_targets)) and len(items[2].link_targets) == 2
        explained = source_feed_queries.source_feed_item_explanation(
            connection, item_key=ABSENT_ITEM, source_id=None)
        assert explained["source"]["source_id"] == "crafted-alpha"  # NULL acquisitions rank last
        beta_only = source_feed_queries.source_feed_item_explanation(
            connection, item_key=ABSENT_ITEM, source_id="crafted-beta")
        assert beta_only["source"]["acquired_at"] is None


def test_run_casts_refuse_what_postgresql_rejects(tmp_path: Path) -> None:
    observations = list(crafted_feed_observations())
    first = observations[0]
    observations[0] = replace(first, metadata={**first.metadata, "source_run_id": "r1",
                                               "source_artifact_bytes": "12x"})
    path = _database(tmp_path, "casts")
    _publish(path, 1, tuple(observations), name="casts")
    with _read(path, "casts") as connection:
        assert source_queries.ingested_sources(connection, source_type=None, policy_status=None, limit=5)
        with pytest.raises(StorageSchemaError, match="not a valid integer"):
            source_queries.source_runs(connection, source_id="crafted-alpha", limit=5)


def test_unpublished_graph_refuses_every_operation(tmp_path: Path) -> None:
    path = _database(tmp_path)
    calls = (
        lambda c: source_queries.ingested_sources(c, source_type=None, policy_status=None, limit=5),
        lambda c: source_queries.source_summary(c, source_id=RSS),
        lambda c: source_queries.source_runs(c, source_id=RSS, limit=5),
        lambda c: source_feed_queries.source_feed_items(c, source_id=RSS, source_run_id=None, limit=5),
        lambda c: source_feed_queries.source_references(
            c, source_id=RSS, source_run_id=None, target_kind=None, limit=5),
        lambda c: source_feed_queries.source_feed_item_explanation(c, item_key=ABSENT_ITEM, source_id=None),
    )
    with _read(path) as connection:
        for call in calls:
            with pytest.raises(LocalStoreError) as caught:
                call(connection)
            assert caught.value.code == "graph-publication-absent"
        with pytest.raises(StorageSchemaError, match="limit must be a positive integer"):
            source_queries.ingested_sources(connection, source_type=None, policy_status=None, limit=0)


def test_ordering_and_default_helpers() -> None:
    rows = [("a", None), ("b", "2"), ("c", "10"), ("d", "2"), ("e", None)]
    ordered = source_queries.desc_nulls_last(rows, lambda row: row[1])
    assert [row[0] for row in ordered] == ["b", "d", "c", "a", "e"]  # text DESC, stable ties, NULLs last
    assert [source_queries.not_fetched(value) for value in (None, "true", "off", "Y", "0")] == [
        True, True, False, True, False]
    with pytest.raises(StorageSchemaError):
        source_queries.not_fetched("maybe")
    assert source_queries.max_of([None, "b", "a"]) == "b" and source_queries.min_of([None, None]) is None
