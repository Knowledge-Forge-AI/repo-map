"""The v2 path/read-order index: a deterministic planner workload, no semantic change (LOCAL8).

The named workload is exact-path observation search. Its SQL comes from the
product (``observation_search_sql``), so the planner assertion plans exactly
what ``repomap_search_observations`` runs. On the v2 schema SQLite's
``EXPLAIN QUERY PLAN`` searches ``idx_raw_observations_path_run`` with
``path=?`` and needs no temporary B-tree for ``ORDER BY run_id DESC,
ordinal``; on the same data at v1 the index is absent and the order needs a
temporary B-tree. ``(run_id, ordinal)`` is the primary key, so the order is
total and no plan can change a result. Results before and after the upgrade
are compared exactly for every path, the unfiltered search, kind+path
filters, pages and raw payloads, and (as a canary for reads without an ORDER
BY) the summary, source and status reads over ``raw_observations``. No
wall-clock threshold or benchmark gates anything.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.storage.sqlite_local import (
    api_summary_queries,
    investigation_queries,
    migrations,
    nix_summary_queries,
    source_queries,
    summary_queries,
)
from repomap_kg.storage.sqlite_local.connection import (
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.investigation_queries import observation_search_sql
from repomap_kg.storage.sqlite_local.migrations import SchemaState, classify
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.upgrade import upgrade_graph_database
from repomap_test_support.sqlite_local_fixtures import generation_bundle, local_binding, publication_for
from repomap_test_support.sqlite_local_read_corpus import read_corpus_bundle

BINDING = local_binding()
ROOT = BINDING.root_path
INDEX = "idx_raw_observations_path_run"


def _bundles(name: str) -> tuple[PublicationBundle, ...]:
    if name == "corpus":
        return (read_corpus_bundle(),)
    return (generation_bundle(1), generation_bundle(2))


@pytest.fixture(params=("corpus", "two-generations"))
def historical(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A published v1 database built by the preserved v1 catalog prefix."""
    path = tmp_path / "live" / "portable-fixture.sqlite3"
    path.parent.mkdir(mode=0o700, parents=True)
    with monkeypatch.context() as v1:
        v1.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z")
        for generation, bundle in enumerate(_bundles(request.param), start=1):
            publish_generation(path, publication_for(bundle), bundle.families, expected_generation=generation - 1)
    return path


def _plan(connection: Any, *, kind: bool, path: bool) -> list[str]:
    params = ["x"] * (int(kind) + int(path))
    rows = connection.execute("EXPLAIN QUERY PLAN " + observation_search_sql(kind=kind, path=path), params)
    return [str(row[3]) for row in rows]


def _search(connection: Any, **kwargs: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {"query": "", "kind": None, "path": None, "limit": 1000, "offset": 0,
                                 "include_raw": False}
    arguments.update(kwargs)
    return investigation_queries.observation_search(connection, **arguments)


def _semantic_reads(connection: Any) -> dict[str, Any]:
    pairs = connection.execute("SELECT DISTINCT kind, path FROM raw_observations ORDER BY kind, path").fetchall()
    paths = sorted({path for _, path in pairs})
    reads: dict[str, Callable[[], Any]] = {
        "unfiltered": lambda: _search(connection),
        "unfiltered-raw": lambda: _search(connection, include_raw=True),
        "pages": lambda: [_search(connection, limit=2, offset=offset) for offset in range(0, 12, 2)],
        "raw-rows": lambda: list(summary_queries.raw_rows(connection, prefix="")),
        "source-observations": lambda: source_queries.source_observations(connection),
        "status": lambda: investigation_queries.status_fields(connection),
        "python": lambda: summary_queries.python_summary(connection, root_path=ROOT),
        "terraform": lambda: summary_queries.terraform_summary(connection, root_path=ROOT),
        "nix": lambda: nix_summary_queries.nix_summary(connection, root_path=ROOT),
        "openapi": lambda: api_summary_queries.openapi_summary(connection, root_path=ROOT),
    }
    results = {name: read() for name, read in reads.items()}
    for path in paths:
        results[f"path:{path}"] = _search(connection, path=path, include_raw=True)
        results[f"path-page:{path}"] = _search(connection, path=path, limit=1, offset=1)
    for kind, path in pairs:
        results[f"kind+path:{kind}:{path}"] = _search(connection, kind=kind, path=path)
    return results


def test_v2_index_serves_exact_path_search_without_changing_any_result(historical: Path, tmp_path: Path) -> None:
    with read_transaction(historical, BINDING, accept_behind=True) as connection:
        assert classify(connection) == SchemaState("behind", 1)
        before = _semantic_reads(connection)
        v1_path_plan = _plan(connection, kind=False, path=True)
        v1_unfiltered_plan = _plan(connection, kind=False, path=False)
    assert not any(INDEX in row for row in v1_path_plan), v1_path_plan
    assert any("TEMP B-TREE" in row for row in v1_path_plan), f"v1 must sort for ORDER BY: {v1_path_plan}"
    assert any(key.startswith("path:") for key in before) and before["unfiltered"]["results"], sorted(before)

    with publisher_lock(historical):
        result = upgrade_graph_database(
            historical, BINDING, tmp_path / "pre-upgrade", created_at="2026-09-30T00:00:00Z", applied_at="later"
        )
    assert (result.from_version, result.schema_version) == (1, 2)

    with read_transaction(historical, BINDING) as connection:
        assert classify(connection) == SchemaState("current", 2)
        after = _semantic_reads(connection)
        v2_path_plan = _plan(connection, kind=False, path=True)
        v2_unfiltered_plan = _plan(connection, kind=False, path=False)
    assert any(INDEX in row and "path=?" in row for row in v2_path_plan), v2_path_plan
    assert not any("TEMP B-TREE" in row for row in v2_path_plan), v2_path_plan
    assert v2_unfiltered_plan == v1_unfiltered_plan and not any(INDEX in row for row in v2_unfiltered_plan), (
        v1_unfiltered_plan, v2_unfiltered_plan,
    )
    assert sorted(after) == sorted(before)
    changed = [name for name in before if repr(before[name]) != repr(after[name])]
    assert changed == [], f"the v2 index changed read results: {changed}"
