"""Source-blind SQLite Local source/feed reads over real stdio MCP (PRODUCT3-SQLITE-LOCAL5).

Four real offline feed acquisitions run in the parent (no fetch: an offline
fetcher returns the checked-in bodies). ``ops sqlite-init`` creates the feed
graph and an unpublished sibling through the guarded launcher; the fixture
source root, including every retained feed artifact, is then removed. Each
generation's validated bundle is published in-process by the SQLite Local
publisher with the PostgreSQL publishers and psycopg patched to fail.

Every MCP child runs through the guarded launcher: no PostgreSQL environment,
recording shims for PostgreSQL/container/service executables, and denial of
any socket connection, forbidden spawn or psycopg connect. Session A reads
generation 1; session B reads generation 2 (the RSS source's newest run is a
parse-error run); session C restarts after EOF and must equal B. All six
source/feed tools return meaningful data with source, run and target filters,
and absent, validation, hidden-graph and unpublished refusals keep their public
texts. The database bytes and logical dump are unchanged by B and C, no guard
fires, no shim runs, and no response carries a secret marker or a temporary
absolute path.

This is containerized integration evidence (Linux sandbox), not a macOS host,
wheel, store or native-app qualification.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.ingestion.source import FeedIngestionSummary
from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_kg.storage.sqlite_local import source_feed_queries
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.sqlite_local_feed_corpus import (
    ATOM,
    RSS,
    SECRET,
    SECRET_MARKERS,
    acquire_feed_runs,
    feed_bundle,
    generation_observations,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, local_binding, publication_for, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    initialize,
    refusal,
    remove_database,
    structured,
    tool,
)

FEEDS, EMPTY, HIDDEN = "sqlite-feed", "sqlite-feed-empty", "sqlite-feed-hidden"
ABSENT_ITEM = "feed.item:feed.channel%3Aabsent:guid%3Anone"
SOURCE_TOOLS = frozenset({
    "repomap_ingested_sources", "repomap_source_summary", "repomap_source_runs",
    "repomap_source_feed_items", "repomap_explain_source_feed_item", "repomap_source_references",
})


def _pg_fail(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("SQLite publication reached a PostgreSQL publisher or driver")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def _publish(path: Path, runs: dict[str, FeedIngestionSummary], generation: int) -> None:
    bundle = feed_bundle(FEEDS, generation, generation_observations(runs, generation))
    with patch("repomap_kg.storage.staged_ingestion.run_staged_portable_refresh", _pg_fail), \
            patch("repomap_kg.ops.portable_refresh.run_staged_portable_refresh", _pg_fail), \
            patch("psycopg.connect", _pg_fail):
        result = publish_generation(path, publication_for(bundle, FEEDS), bundle.families,
                                    expected_generation=generation - 1)
    assert result.generation == generation, result


def _requests(item_key: str, rss1: str) -> list[dict[str, Any]]:
    p = {"project": FEEDS}
    rss = {**p, "source_id": RSS}
    return [
        initialize(1),
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        tool(10, "repomap_ingested_sources", p),
        tool(11, "repomap_ingested_sources", {**p, "source_type": "feed.atom"}),
        tool(12, "repomap_ingested_sources", {**p, "policy_status": "allowed_with_limits", "limit": 1}),
        tool(13, "repomap_source_summary", rss),
        tool(14, "repomap_source_summary", {**p, "source_id": "no-such-source"}),
        tool(15, "repomap_source_runs", rss),
        tool(16, "repomap_source_runs", {**rss, "limit": 1}),
        tool(17, "repomap_source_feed_items", rss),
        tool(18, "repomap_source_feed_items", {**rss, "source_run_id": rss1}),
        tool(19, "repomap_source_feed_items", {**rss, "source_run_id": "no-such-run"}),
        tool(20, "repomap_source_references", rss),
        tool(21, "repomap_source_references", {**rss, "target_kind": "feed.author"}),
        tool(22, "repomap_source_references", {**rss, "source_run_id": rss1, "target_kind": "file"}),
        tool(23, "repomap_explain_source_feed_item", {**p, "item_key": item_key}),
        tool(24, "repomap_explain_source_feed_item", {**p, "item_key": item_key, "source_id": ATOM}),
        tool(25, "repomap_explain_source_feed_item", {**p, "item_key": ABSENT_ITEM}),
        tool(26, "repomap_source_feed_items", {"project": FEEDS, "source_id": SECRET}),
        tool(30, "repomap_source_summary", {**p, "source_id": "has space"}),
        tool(31, "repomap_explain_source_feed_item", {**p, "item_key": "file:feed.xml"}),
        tool(32, "repomap_source_runs", {"project": HIDDEN, "source_id": RSS}),
        tool(33, "repomap_ingested_sources", {"project": EMPTY}),
        tool(34, "repomap_source_runs", {**rss, "limit": 0}),
        tool(35, "repomap_source_references", {**rss, "target_kind": "https://example.invalid/"}),
    ]


REFUSALS = {
    30: "source_id must not contain whitespace",
    31: "item_key must use the feed.item namespace",
    32: f"graph '{HIDDEN}' is not MCP-visible",
    33: "graph-publication-absent",
    34: "limit must be between 1 and 500",
    35: "target_kind must not be a URL",
}


def _assert_session(
    responses: dict[int, dict[str, Any]], runs: dict[str, FeedIngestionSummary], generation: int, item_key: str
) -> None:
    rss1, rss2 = runs["rss1"].source_run_id, runs["rss2"].source_run_id
    inventory = structured(responses, 10)
    assert [row["source_id"] for row in inventory] == [ATOM, RSS, SECRET], inventory
    latest = {row["source_id"]: row["latest_source_run_id"] for row in inventory}
    assert latest[RSS] == (rss1 if generation == 1 else rss2), latest
    assert all(row["canonical_feed_item_count"] > 0 and row["feed_observation_count"] > 0 for row in inventory)
    assert [row["source_id"] for row in structured(responses, 11)] == [ATOM]
    assert [row["source_id"] for row in structured(responses, 12)] == [RSS]

    summary = structured(responses, 13)
    assert (summary["feed_items"], summary["feed_authors"], summary["feed_categories"]) == (5, 1, 1), summary
    assert summary["parse_errors"] == generation - 1 and summary["latest_source_run_id"] == latest[RSS]
    absent = structured(responses, 14)
    assert (absent["policy_status"], absent["known_limitations"]) == ("unknown", ["source metadata unavailable"])

    source_runs = structured(responses, 15)
    expected_runs = [(rss1, "ok")] if generation == 1 else [(rss2, "parse_errors"), (rss1, "ok")]
    assert [(run["source_run_id"], run["status_summary"]) for run in source_runs] == expected_runs
    assert source_runs[-1]["artifact_byte_length"] == runs["rss1"].artifact_bytes
    assert structured(responses, 16) == source_runs[:1]

    items = structured(responses, 17)
    assert len(items) == 5 and items[0]["title"] == "RSS Weak Fallback", items
    assert [item["published_at"] is None for item in items] == [False, False, False, True, True]
    assert structured(responses, 18) == items and structured(responses, 19) == []
    references = structured(responses, 20)
    assert references and {row["source_run_id"] for row in references} == {rss1}, references
    authors = structured(responses, 21)
    assert len(authors) == generation and {row["target_key"].split(":", 1)[0] for row in authors} == {"feed.author"}
    files = structured(responses, 22)
    assert {row["target_display"] for row in files} == {"media/rss-audio.mp3", "articles/rss-link-fallback.html"}

    explained = structured(responses, 23)
    assert explained["item"]["canonical_key"] == item_key and explained["evidence"], explained
    assert explained["source"]["source_id"] == RSS and explained["references"]
    assert explained["content_policy"] == "full feed bodies are not exposed"
    other = structured(responses, 24)
    assert (other["item"], other["evidence"], other["source"]["source_id"]) == (None, [], ATOM)
    assert other["references"] == explained["references"]
    assert structured(responses, 25)["item"] is None
    (secret,) = structured(responses, 26)  # the extractor withholds the secret-looking item's title
    assert secret["item_key"].endswith(":guid%3Asecret-item") and secret["title"] is None, secret
    for mid, text in REFUSALS.items():
        assert refusal(responses, mid) == text, (mid, refusal(responses, mid))


def test_sqlite_local_source_feed_tools_read_source_blind_over_stdio(tmp_path: Path) -> None:
    root = tmp_path / "feed-root"
    runs = acquire_feed_runs(root)
    graphs = graph_toml(FEEDS, root) + graph_toml(EMPTY, root) + graph_toml(HIDDEN, root, visible=False)
    home = write_sqlite_home(tmp_path / "home", graphs)
    harness = LocalHarness(tmp_path / "harness")
    for graph in (FEEDS, EMPTY):
        init = harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", graph)
        assert init["result"] == "initialized", init
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    path = config.graph_store_root / f"{FEEDS}.sqlite3"
    assert (root / ".repomap" / "source-artifacts").is_dir()
    shutil.rmtree(root)  # source-blind reads: no fixture root and no retained artifact remains

    _publish(path, runs, 1)
    with read_transaction(path, local_binding(FEEDS)) as connection:
        item_key = source_feed_queries.source_feed_items(
            connection, source_id=RSS, source_run_id=None, limit=50)[2].item_key
    requests = _requests(item_key, runs["rss1"].source_run_id)
    first = harness.mcp(home, requests)
    assert first[1]["result"]["protocolVersion"] == "2024-11-05"
    listed = first[2]["result"]["tools"]
    assert listed == tool_definitions() and len(listed) == 27, len(listed)
    assert SOURCE_TOOLS <= {entry["name"] for entry in listed}
    _assert_session(first, runs, 1, item_key)

    _publish(path, runs, 2)
    before = (_digest(path), _dump(path))
    second = harness.mcp(home, requests)
    _assert_session(second, runs, 2, item_key)
    third = harness.mcp(home, requests)  # restart after EOF: identical reads of the same generation
    assert set(third) == set(second) == {request["id"] for request in requests}
    for mid in third:
        assert third[mid] == second[mid], mid
    assert (_digest(path), _dump(path)) == before, "reads changed the main file or a logical row"
    assert structured(first, 10) != structured(second, 10), "the latest run must move between generations"

    text = json.dumps([first, second, third])
    assert not any(marker in text for marker in SECRET_MARKERS)
    assert str(tmp_path) not in text and not root.exists()
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == ""
    for graph in (FEEDS, EMPTY):
        remove_database(config.graph_store_root / f"{graph}.sqlite3")
    assert not any(config.graph_store_root.iterdir())
