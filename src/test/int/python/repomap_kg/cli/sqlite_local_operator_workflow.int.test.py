"""SQLite Local ordinary operator workflow without PostgreSQL or its driver (LOCAL6).

One disposable SQLite Local home, graphs in configuration order ``zulu``
(one source, visible), ``alpha`` (two sources, MCP-hidden) and ``mike``
(disabled). Every SQLite child runs through the guarded launcher with the
Psycopg family made genuinely unavailable, recording shims for PostgreSQL,
container and service executables, and socket/spawn denial. The real CLI
walks config-check and graphs (with and without ``--check-db``) before and
after ``sqlite-init``, preflight, direct refresh, ``refresh-enabled`` over the
two enabled graphs, the coordinator-mode refusal, a source-blind stdio MCP
read, and a mixed ``refresh-enabled`` whose real source-root refusal leaves
the successful graph and the refused graph's accepted generation intact. The
disabled graph is never touched. A PostgreSQL-home canary proves the blocker
engages on the real PostgreSQL path.

This is containerized integration evidence (Linux sandbox), not a macOS host
or installed-wheel qualification.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from repomap_test_support.host_read_store_config import setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    graph_toml,
    multi_graph_toml,
    write_shell_source,
    write_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    initialize,
    refusal,
    structured,
    tool,
)

POSTGRES_IMPLEMENTATION = {
    "repomap_kg.coordinator.local_mode",
    "repomap_kg.coordinator.local_lifecycle",
    "repomap_kg.service_package.api",
    "repomap_kg.storage.staged_ingestion",
    "repomap_kg.runtime.maintenance",
    "repomap_kg.runtime.release_cluster",
    "repomap_kg.ops.refresh",
    "psycopg",
}


def _home(tmp_path: Path) -> tuple[Path, Path]:
    sources = tmp_path / "sources"
    for name in ("zulu", "left", "right"):
        write_shell_source(sources / name)
    graphs = (
        graph_toml("zulu", sources / "zulu")
        + multi_graph_toml("alpha", (("left", sources / "left"), ("right", sources / "right"))).replace(
            "mcp_visible = true", "mcp_visible = false"
        )
        + graph_toml("mike", sources / "zulu", enabled=False)
    )
    return write_sqlite_home(tmp_path / "home", graphs), sources


def _database(home: Path, graph: str) -> Path:
    return home / "state" / "sqlite-local" / "graphs" / f"{graph}.sqlite3"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(home: Path) -> dict[str, str]:
    """Every file under the home's private state with its digest."""
    state = home / "state"
    if not state.exists():
        return {}
    return {
        str(path.relative_to(home)): _digest(path)
        for path in sorted(state.rglob("*"))
        if path.is_file()
    }


def _ok(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert completed.returncode == 0, completed.stderr
    return completed


def _json(harness: LocalHarness, home: Path, *args: str) -> dict[str, Any]:
    payload = json.loads(_ok(harness.run(*args, "--repo-map-home", str(home), "--json")).stdout)
    assert isinstance(payload, dict)
    return payload


def _states(payload: dict[str, Any]) -> dict[str, tuple[str, int | None]]:
    return {
        item["graph_id"]: (item["state"], item["accepted_generation"])
        for item in payload["storage_status"]["graphs"]
    }


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def test_sqlite_local_operator_workflow_without_postgres(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    home, sources = _home(tmp_path)
    _ok(harness.run("--help"))

    # 1-3: base forms and --check-db before init; nothing is created.
    base = _json(harness, home, "ops", "config-check")
    assert base["storage"] == {"backend": "sqlite"} and base["storage_status"]["db_checked"] is False
    assert not {"postgres", "runtime", "postgres_status"} & set(base), sorted(base)
    graphs = _json(harness, home, "ops", "graphs")
    assert [row["id"] for row in graphs["graphs"]] == ["zulu", "alpha", "mike"]
    assert {row["database"] for row in graphs["graphs"]} == {"[graph-database]"}
    checked = _json(harness, home, "ops", "config-check", "--check-db")
    assert set(_states(checked).values()) == {("not-initialized", None)}, checked
    listed = _json(harness, home, "ops", "graphs", "--check-db")
    assert {row["storage_status"]["state"] for row in listed["graphs"]} == {"not-initialized"}
    assert not (home / "state").exists(), "a readiness command created the store"

    # 4-5: init, then current-but-unpublished is distinct from absent.
    for graph in ("zulu", "alpha"):
        assert _json(harness, home, "ops", "sqlite-init", "--graph", graph)["result"] == "initialized"
    assert _states(_json(harness, home, "ops", "config-check", "--check-db")) == {
        "zulu": ("current", None), "alpha": ("current", None), "mike": ("not-initialized", None),
    }

    # 6: preflight reads sources only.
    before = _tree(home)
    for graph, files in (("zulu", 2), ("alpha", 4)):
        preflight = _json(harness, home, "ops", "refresh-preflight", "--graph", graph)
        assert preflight["result"] == "success" and preflight["graph"]["files_included"] == files, preflight
    assert _tree(home) == before, "preflight changed the private store"

    # 7-8: direct refresh, then refresh-enabled over the two enabled graphs.
    direct = _json(harness, home, "ops", "refresh-graph", "--graph", "zulu")
    assert direct["accepted_generation"] == 1, direct
    enabled = _json(harness, home, "ops", "refresh-enabled")
    assert enabled["result"] == "success", enabled
    assert [(row["graph_id"], row["accepted_generation"]) for row in enabled["graphs"]] == [
        ("zulu", 2), ("alpha", 1),
    ], enabled["graphs"]

    # 9: the disabled graph is untouched.
    assert not [path for path in (home / "state").rglob("*") if "mike" in path.name], "mike was touched"

    # 10: coordinator mode is refused before any side effect.
    before = _tree(home)
    for key in ((), ("--idempotency-key", "local6-key")):
        refused = harness.run(
            "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "zulu", "--mode", "coordinator", *key
        )
        assert refused.returncode == 1, refused.stderr
        assert "sqlite-local-refresh-rejects-coordinator-mode" in refused.stderr, refused.stderr
    assert _tree(home) == before, "coordinator refusal changed the private store"
    assert "repomap_kg.coordinator.local_mode" not in harness.imported_modules()

    # 11: source-blind MCP read after publication; the hidden graph stays hidden.
    databases = {graph: _digest(_database(home, graph)) for graph in ("zulu", "alpha")}
    shutil.move(sources / "zulu", tmp_path / "zulu-away")
    responses = harness.mcp(
        home,
        [
            initialize(),
            tool(2, "repomap_graph_status", {"graph_id": "zulu"}),
            tool(3, "repomap_canonical_nodes", {"project": "zulu", "limit": 2}),
            tool(4, "repomap_graph_status", {"graph_id": "alpha"}),
        ],
    )
    assert structured(responses, 3)["items"], responses[3]
    assert structured(responses, 2), responses[2]
    assert refusal(responses, 4), responses[4]
    assert {graph: _digest(_database(home, graph)) for graph in databases} == databases
    shutil.move(tmp_path / "zulu-away", sources / "zulu")

    # 12: a real source-root refusal yields partial without harming the success.
    shutil.rmtree(sources / "right")
    mixed = harness.run("ops", "refresh-enabled", "--repo-map-home", str(home), "--json")
    assert mixed.returncode == 1, mixed.stderr
    payload = json.loads(mixed.stdout)
    assert payload["result"] == "partial", payload
    rows = {row["graph_id"]: row for row in payload["graphs"]}
    assert rows["zulu"]["accepted_generation"] == 3, rows
    assert (rows["alpha"]["error_category"], rows["alpha"]["error"]) == (
        "refresh-rejected", "graph 'alpha' source root is unavailable",
    ), rows["alpha"]
    assert _states(_json(harness, home, "ops", "config-check", "--check-db"))["alpha"] == ("current", 1)
    assert _integrity(_database(home, "zulu")) == "ok"

    # Every SQLite child: no PostgreSQL, container, service or driver import.
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite children loaded PostgreSQL implementation modules: {sorted(loaded)}"


def test_blocker_engages_on_the_real_postgres_path(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    completed = harness.run("ops", "graphs", "--repo-map-home", str(home))
    assert completed.returncode == 1, completed.stderr
    assert "postgresql-driver-unavailable" in completed.stderr, completed.stderr
    assert any(event["kind"] == "import-blocked" for event in harness.guard_events())
    assert harness.shim_invocations() == "", harness.shim_invocations()
