"""``ops sealing-plan`` children for Local and Server homes: metadata-only, no DB.

Counts are compared with an independent walk of the configured source trees,
and the Local child runs with the PostgreSQL driver made unavailable. The
Server child uses a home whose database is never started: the plan must not
connect, lock, launch a worker or write anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from common_lore_index.ops.config_local import load_graph_registry_config_home
from repomap_test_support.resource_report_cli_files import run_cloe
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import LocalHarness

GRAPH = "plan-local"
POSTGRES_IMPLEMENTATION = {"common_lore_index.ops.refresh", "common_lore_index.storage.staged_ingestion", "psycopg"}


def _walk(roots: list[Path]) -> tuple[int, int, int, int]:
    """(files, bytes, entries, listings) of plain trees with no ignored names."""
    files = total = entries = listings = 0
    for root in roots:
        for _current, dirnames, filenames in os.walk(root):
            listings += 1
            entries += len(dirnames) + len(filenames)
            files += len(filenames)
            total += sum((Path(_current) / name).stat().st_size for name in filenames)
    return files, total, entries, listings


def _snapshot(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {
        str(item): (item.stat().st_mtime_ns, item.stat().st_size)
        for root in paths for item in sorted(root.rglob("*"))
    }


def test_local_plan_is_driver_free_metadata_only_and_matches_the_tree(tmp_path: Path) -> None:
    source = write_shell_source(tmp_path / "sources" / "one")
    (source / "nested").mkdir()
    (source / "nested" / "data.txt").write_bytes(b"d" * 4096)
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    before = _snapshot([source, home])
    completed = harness.run("ops", "sealing-plan", "--repo-map-home", str(home), "--graph", GRAPH, "--json")
    assert completed.returncode == 0, completed.stderr
    assert harness.forbidden_events() == []
    assert not harness.imported_modules() & POSTGRES_IMPLEMENTATION
    plan = json.loads(completed.stdout)
    files, total, entries, listings = _walk([source])
    assert plan["schema"] == "cloe-sealing-plan-v1" and plan["refusal"] is None
    assert (plan["inventory_files"], plan["inventory_bytes"]) == (files, total)
    assert (plan["directory_entries"], plan["opens"]) == (entries, listings)
    assert plan["planned_min_read_bytes"] == 4 * total + 1
    assert plan["projected_directory_entries"] == 3 * entries
    assert _snapshot([source, home]) == before, "the plan wrote nothing and changed no source"
    for forbidden in (str(source), str(home), GRAPH, "lib.sh"):
        assert forbidden not in completed.stdout

    refused = harness.run("ops", "sealing-plan", "--repo-map-home", str(home), "--graph", GRAPH,
                          "--sealing-max-entries", "2")
    assert refused.returncode == 1 and "refusal: directory_entries" in refused.stdout
    unknown = harness.run("ops", "sealing-plan", "--repo-map-home", str(home), "--graph", "absent")
    assert unknown.returncode == 1 and unknown.stderr.strip() == "ERROR: sealing-plan-unknown-graph"


def test_server_home_plan_never_connects_to_its_database(tmp_path: Path) -> None:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home", working_copy, host="127.0.0.1", port=59999, database="never_started",
        user="nobody", password=os.urandom(16).hex(), declared_aliases=("core", "companion"),
    )
    config = load_graph_registry_config_home(home)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    roots = [Path(binding.root_path_expanded) for binding in graph.effective_source_bindings]
    completed = run_cloe("ops", "sealing-plan", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
                         "--json", cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["bindings"] == len(roots) >= 2
    assert plan["inventory_files"] > 0 and plan["inventory_bytes"] > 0
    assert plan["effective_max_directory_entries"] == 100_000
    assert plan["planned_min_write_bytes"] == plan["inventory_bytes"]
