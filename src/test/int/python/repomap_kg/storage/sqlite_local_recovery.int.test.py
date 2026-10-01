"""SQLite Local accepted-generation recovery on real captured bundles.

Covers two accepted generations with lineage, a tampered candidate rejected by
parent validation (first and later candidates), a fault after partial inserts,
a test-owned SIGKILL of a writer paused before commit, writer contention and a
coherent multi-query read across a concurrent commit.

LOCAL2 adds: a failure inside the real publisher transaction (first and later
publication) that keeps the accepted generation, then a valid retry read over
MCP; a SIGINT to a writer paused after COMMIT that propagates and keeps the
committed generation; and a SIGKILLed initializer that never leaves a partial
final database. Pauses use ready/release barrier files (hang-guarded) rather
than timing thresholds. No durability claim is made about power loss or
hardware faults.

LOCAL3 changes the post-COMMIT proof. A writer interrupted (SIGINT) or killed
(SIGKILL) after COMMIT leaves generation 2 accepted and its retained attempt
armed and unsettled. With the source roots removed, the next refresh
reconciles that attempt as accepted and replays generation 2: no capture, no
new attempt and no generation 3. A writer killed before COMMIT leaves its
attempt to be settled failed by the next refresh, which then publishes.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.ops import local_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.storage.sqlite_local import investigation_queries, publisher
from repomap_kg.storage.sqlite_local.connection import read_transaction, sidecar_paths
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    CHILD_DEADLINE_SECONDS,
    LocalHarness,
    await_ready,
    init_orphans,
    initialize,
    release,
    remove_database,
    structured,
    tool,
)

GRAPH, FRESH = "sqlite-recovery", "sqlite-fresh"


def _setup(tmp_path: Path) -> tuple[Path, LocalHarness, LocalSqliteConfig]:
    source = write_shell_source(tmp_path / "sources" / "one")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source) + graph_toml(FRESH, source))
    harness = LocalHarness(tmp_path / "harness")
    for graph in (GRAPH, FRESH):
        assert harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", graph)[
            "result"] == "initialized"
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return home, harness, config


def _path(config: LocalSqliteConfig, graph: str) -> Path:
    return config.graph_store_root / f"{graph}.sqlite3"


def _state(config: LocalSqliteConfig, graph: str) -> dict[str, Any]:
    binding = local_graph_binding(next(item for item in config.graphs if item.id == graph))
    with read_transaction(_path(config, graph), binding) as connection:
        return investigation_queries.status_fields(connection)


def _dump(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def _refresh(harness: LocalHarness, home: Path, graph: str) -> dict[str, Any]:
    return harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", graph)


def _attempts(home: Path, graph: str) -> dict[str, dict[str, Any]]:
    """Every retained Local attempt record of ``graph``, keyed by attempt directory."""
    parent = home / "state" / "portable-publication" / "sqlite-local" / graph / "attempts"
    return {
        record.parent.name: json.loads(record.read_text(encoding="utf-8"))
        for record in sorted(parent.glob("*/portable-result.json"))
    }


def _unsettled(home: Path, graph: str) -> dict[str, dict[str, Any]]:
    return {
        name: payload for name, payload in _attempts(home, graph).items()
        if payload["retention_class"] == "publication-reconciliation"
    }


def test_rejected_candidates_and_partial_faults_keep_the_accepted_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, harness, config = _setup(tmp_path)
    first = _refresh(harness, home, GRAPH)
    second = _refresh(harness, home, GRAPH)
    assert (first["accepted_generation"], second["accepted_generation"], second["previous_run_id"]) == (1, 2, 1)
    path = _path(config, GRAPH)
    accepted = _dump(path)
    real_capture = local_refresh.capture_portable_candidate

    def tampered(*args: Any, **kwargs: Any) -> Any:
        capture = real_capture(*args, **kwargs)
        target = capture.store.object_path(capture.bundle_reference)
        target.chmod(0o600)
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0x01
        target.write_bytes(bytes(data))
        return capture

    monkeypatch.setattr(local_refresh, "capture_portable_candidate", tampered)
    with pytest.raises((OSError, ValueError)):
        local_refresh.refresh_local_graph(config, GRAPH)
    assert _dump(path) == accepted and _state(config, GRAPH)["latest_run_id"] == 2
    with pytest.raises((OSError, ValueError)):
        local_refresh.refresh_local_graph(config, FRESH)  # a tampered first candidate rejected by parent validation
    assert _state(config, FRESH) == {
        "repository_exists": False, "raw_observations": 0, "raw_observations_total": 0,
        "latest_run_raw_observations": 0, "canonical_nodes": 0, "canonical_edges": 0,
    }
    monkeypatch.setattr(local_refresh, "capture_portable_candidate", real_capture)

    def fault(name: str) -> None:
        if name == "after_family:canonical_evidence":
            raise RuntimeError("injected fault after partial inserts")

    monkeypatch.setattr(publisher, "_fault_point", fault)
    with pytest.raises(RuntimeError):
        local_refresh.refresh_local_graph(config, GRAPH)
    assert _dump(path) == accepted
    monkeypatch.setattr(publisher, "_fault_point", lambda _name: None)
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, local_graph_binding(config.graphs[0])) as connection:
            connection.execute("UPDATE runs SET status = 'complete'")
    assert caught.value.code == "graph-database-read-only"
    assert _dump(path) == accepted
    assert harness.forbidden_events() == []
    for graph in (GRAPH, FRESH):
        remove_database(_path(config, graph))


def test_killed_writer_leaves_previous_generation_readable_and_recoverable(tmp_path: Path) -> None:
    home, harness, config = _setup(tmp_path)
    gen1 = _refresh(harness, home, GRAPH)
    barrier = tmp_path / "kill-barrier"
    writer = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH,
        extra_env=harness.paused_env("after_family:canonical_edges", barrier),
    )
    try:
        await_ready(barrier, writer)
        os.kill(writer.pid, signal.SIGKILL)
    finally:
        writer.communicate()
    assert writer.returncode == -signal.SIGKILL
    reopened = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": GRAPH})])
    storage = structured(reopened, 2)["storage"]
    assert storage["latest_run_id"] == 1
    assert storage["publication"] == gen1["publication"]
    killed = _unsettled(home, GRAPH)
    assert len(killed) == 1 and next(iter(killed.values()))["sqlite_local_publication"]["expected_generation"] == 1
    recovered = _refresh(harness, home, GRAPH)
    assert (recovered["accepted_generation"], recovered["previous_run_id"]) == (2, 1)
    settled = _attempts(home, GRAPH)
    assert {name: settled[name]["retention_class"] for name in killed} == dict.fromkeys(killed, "terminal-failed")
    assert _unsettled(home, GRAPH) == {}
    assert harness.forbidden_events() == []
    for graph in (GRAPH, FRESH):
        remove_database(_path(config, graph))


def test_writer_contention_is_refused_and_reads_stay_coherent(tmp_path: Path) -> None:
    home, harness, config = _setup(tmp_path)
    _refresh(harness, home, GRAPH)
    path = _path(config, GRAPH)
    accepted = _dump(path)
    barrier = tmp_path / "hold-barrier"
    holder = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH,
        extra_env=harness.paused_env("before_commit", barrier),
    )
    try:
        await_ready(barrier, holder)
        contender = harness.run("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH)
        assert contender.returncode == 1 and "graph-publication-in-progress" in contender.stderr, contender.stderr
        assert _dump(path) == accepted
        binding = local_graph_binding(config.graphs[0])
        with read_transaction(path, binding) as connection:
            before = investigation_queries.status_fields(connection)
            release(barrier)
            stdout, stderr = holder.communicate(timeout=240)
            assert holder.returncode == 0, stderr
            assert investigation_queries.status_fields(connection) == before  # one operation, one snapshot
        assert before["latest_run_id"] == 1
        assert _state(config, GRAPH)["latest_run_id"] == 2  # the next operation sees the commit
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()
    assert harness.forbidden_events() == []
    for graph in (GRAPH, FRESH):
        remove_database(_path(config, graph))


_TABLES = (
    "runs", "files", "raw_observations", "canonical_nodes", "canonical_edges",
    "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
)


def _accepted(config: LocalSqliteConfig, graph: str) -> tuple[Any, dict[str, int]]:
    """Accepted identity (generation, run, bundle) and every family row count."""
    binding = local_graph_binding(next(item for item in config.graphs if item.id == graph))
    with read_transaction(_path(config, graph), binding) as connection:
        identity = connection.execute(
            "SELECT a.generation, a.run_id, r.publication_bundle_id FROM accepted_publication a "
            "JOIN runs r ON r.id = a.run_id"
        ).fetchone()
        counts = {
            table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in _TABLES
        }
    return identity, counts


def test_publisher_internal_failure_keeps_the_accepted_generation_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, harness, config = _setup(tmp_path)
    reached: list[str] = []

    def fail_at(point: str) -> Any:
        def fault(name: str) -> None:
            reached.append(name)
            if name == point:
                raise RuntimeError(f"injected publisher fault at {name}")

        return fault

    # A first publication fails inside the real transaction after its run row
    # and earlier families were written.
    monkeypatch.setattr(publisher, "_fault_point", fail_at("after_family:canonical_evidence"))
    with pytest.raises(RuntimeError):
        local_refresh.refresh_local_graph(config, FRESH)
    assert reached[:3] == ["after_run_insert", "after_family:files", "after_family:raw_observations"], reached
    assert _accepted(config, FRESH) == (None, dict.fromkeys(_TABLES, 0))

    monkeypatch.setattr(publisher, "_fault_point", lambda _name: None)
    assert _refresh(harness, home, GRAPH)["accepted_generation"] == 1
    path = _path(config, GRAPH)
    accepted, identity = _dump(path), _accepted(config, GRAPH)
    reached.clear()
    monkeypatch.setattr(publisher, "_fault_point", fail_at("after_family:canonical_edges"))
    with pytest.raises(RuntimeError):
        local_refresh.refresh_local_graph(config, GRAPH)
    assert "after_family:canonical_nodes" in reached, reached
    assert _dump(path) == accepted and _accepted(config, GRAPH) == identity
    monkeypatch.setattr(publisher, "_fault_point", lambda _name: None)
    status = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": GRAPH})])
    assert structured(status, 2)["storage"]["latest_run_id"] == 1

    later, first = _refresh(harness, home, GRAPH), _refresh(harness, home, FRESH)
    assert (later["accepted_generation"], later["previous_run_id"]) == (2, 1), later
    assert (first["accepted_generation"], first["previous_run_id"]) == (1, None), first
    reads = harness.mcp(home, [
        initialize(1),
        tool(2, "repomap_canonical_nodes", {"project": FRESH, "limit": 2}),
        tool(3, "repomap_graph_status", {"graph_id": GRAPH}),
    ])
    assert structured(reads, 2)["items"], structured(reads, 2)
    assert structured(reads, 3)["storage"]["latest_run_id"] == 2
    assert harness.forbidden_events() == []
    for graph in (GRAPH, FRESH):
        remove_database(_path(config, graph))


@pytest.mark.parametrize("stop", (signal.SIGINT, signal.SIGKILL), ids=("sigint", "sigkill"))
def test_post_commit_uncertainty_is_reconciled_without_sources_or_a_new_generation(
    tmp_path: Path, stop: signal.Signals
) -> None:
    home, harness, config = _setup(tmp_path)
    _refresh(harness, home, GRAPH)
    barrier = tmp_path / "after-commit-barrier"
    writer = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json",
        extra_env=harness.paused_env("after_commit", barrier),
    )
    try:
        await_ready(barrier, writer)
        assert _state(config, GRAPH)["latest_run_id"] == 2  # the pause is past COMMIT
        os.kill(writer.pid, stop)
        stdout, stderr = writer.communicate(timeout=CHILD_DEADLINE_SECONDS)
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.communicate()
    assert writer.returncode != 0, (writer.returncode, stdout)
    assert '"result"' not in stdout and "accepted generation" not in stdout, stdout
    pending = _unsettled(home, GRAPH)
    assert len(pending) == 1, pending
    armed = next(iter(pending.values()))["sqlite_local_publication"]
    assert (armed["graph_id"], armed["expected_generation"]) == (GRAPH, 1), armed
    attempt_names = set(_attempts(home, GRAPH))

    sources = tmp_path / "sources"
    sources.rename(tmp_path / "sources-away")  # reconciliation must not need the source roots
    replay = harness.run("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json")
    assert replay.returncode == 0, replay.stderr
    replayed = json.loads(replay.stdout)
    assert (replayed["accepted_generation"], replayed["run_id"], replayed["previous_run_id"]) == (2, 2, 1)
    assert "reconciled" not in replayed and replayed["publication"]["publication_bundle_id"] == armed[
        "publication_bundle_id"]
    assert "NOTE: sqlite-local-attempt-reconciled: accepted generation 2" in replay.stderr, replay.stderr
    assert set(_attempts(home, GRAPH)) == attempt_names, "reconciliation must not capture a new attempt"
    assert _unsettled(home, GRAPH) == {}
    assert {_attempts(home, GRAPH)[name]["retention_class"] for name in pending} == {"terminal-accepted"}
    status = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": GRAPH})])
    storage = structured(status, 2)["storage"]
    assert storage["latest_run_id"] == 2 and storage["publication"] == replayed["publication"], storage
    assert _state(config, GRAPH)["latest_run_id"] == 2 and _accepted(config, GRAPH)[1]["runs"] == 2

    (tmp_path / "sources-away").rename(sources)
    after = _refresh(harness, home, GRAPH)
    assert (after["accepted_generation"], after["previous_run_id"]) == (3, 2), after
    assert harness.forbidden_events() == []
    for graph in (GRAPH, FRESH):
        remove_database(_path(config, graph))


@pytest.mark.parametrize(
    ("point", "installed"),
    (("init:schema-applied", False), ("init:before-install", False), ("init:after-install", True)),
)
def test_killed_initializer_never_poisons_the_final_path(tmp_path: Path, point: str, installed: bool) -> None:
    source = write_shell_source(tmp_path / "sources" / "one")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    harness = LocalHarness(tmp_path / "harness")
    path = home / "state" / "sqlite-local" / "graphs" / f"{GRAPH}.sqlite3"
    barrier = tmp_path / "init-barrier"
    initializer = harness.start(
        "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH,
        extra_env=harness.paused_env(point, barrier),
    )
    try:
        await_ready(barrier, initializer)
        os.kill(initializer.pid, signal.SIGKILL)
    finally:
        initializer.communicate()
    assert initializer.returncode == -signal.SIGKILL
    assert init_orphans(path), sorted(item.name for item in path.parent.iterdir())
    assert not any(os.path.lexists(sidecar) for sidecar in sidecar_paths(path))
    if installed:
        assert path.stat().st_nlink == 2  # the orphan is a second link to the complete database
    else:
        assert not os.path.lexists(path)
    retry = harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH)
    assert retry["result"] == ("already-current" if installed else "initialized"), retry
    assert _refresh(harness, home, GRAPH)["accepted_generation"] == 1
    status = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": GRAPH})])
    assert structured(status, 2)["storage"]["latest_run_id"] == 1
    assert harness.forbidden_events() == []
    remove_database(path)
