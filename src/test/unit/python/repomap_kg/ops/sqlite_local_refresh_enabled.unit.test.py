"""SQLite Local ``refresh-enabled`` aggregation with an injected per-graph refresh (LOCAL6).

Only enabled graphs run, in configuration order (deliberately not
alphabetical); MCP visibility is not an eligibility criterion. A refusal or
failure becomes a bounded, path-free failure row and the loop continues; an
interrupt records ``cancelled`` and stops. The aggregate follows the
PostgreSQL ``success``/``partial``/``failed`` rule. Real per-graph refreshes
are owned by the containerized operator-workflow integration owner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_kg.ops._portable_retention import PortableRefreshError
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.local_refresh import LocalRefreshError, LocalRefreshResult
from repomap_kg.ops.local_refresh_enabled import (
    LocalRefreshFailure,
    format_local_refresh_enabled_table,
    local_refresh_enabled_to_jsonable,
    refresh_enabled_local_graphs,
)
from repomap_kg.storage.sqlite_local.schema import PUBLICATION_IN_PROGRESS, LocalStoreError
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home


def _config(tmp_path: Path) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir()
    home = write_sqlite_home(
        tmp_path / "home",
        graph_toml("zulu", source) + graph_toml("alpha", source, visible=False)
        + graph_toml("mike", source, enabled=False) + graph_toml("bravo", source),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _success(graph_id: str) -> LocalRefreshResult:
    return LocalRefreshResult(graph_id, 3, 7, 6, {"publication_bundle_id": "bundle1:x"}, {"files": 2})


class _Refresh:
    def __init__(self, failures: dict[str, BaseException]) -> None:
        self.failures = failures
        self.calls: list[str] = []

    def __call__(self, _config: LocalSqliteConfig, graph_id: str) -> LocalRefreshResult:
        self.calls.append(graph_id)
        if graph_id in self.failures:
            raise self.failures[graph_id]
        return _success(graph_id)


def test_enabled_graphs_run_in_configuration_order(tmp_path: Path) -> None:
    config = _config(tmp_path)
    refresh = _Refresh({})
    outcomes = refresh_enabled_local_graphs(config, refresh=refresh)
    assert refresh.calls == ["zulu", "alpha", "bravo"], refresh.calls
    payload = local_refresh_enabled_to_jsonable(config, outcomes)
    assert (payload["result"], payload["graph_count"], payload["refreshed_graph_count"]) == ("success", 3, 3)
    assert payload["graphs"][0] == {
        "graph_id": "zulu", "result": "success", "accepted_generation": 3, "run_id": 7,
        "previous_run_id": 6, "publication": {"publication_bundle_id": "bundle1:x"},
        "family_counts": {"files": 2},
    }, payload["graphs"][0]
    assert payload["command"] == "refresh-enabled" and payload["storage_backend"] == "sqlite"


def test_failures_become_bounded_rows_and_the_loop_continues(tmp_path: Path) -> None:
    config = _config(tmp_path)
    private = str(tmp_path / "private" / "secretive")
    refresh = _Refresh(
        {
            "zulu": LocalStoreError(PUBLICATION_IN_PROGRESS),
            "alpha": OSError(13, "Permission denied", private),
            "bravo": PortableRefreshError(f"bundle rejected under {private}", category="contract_validation"),
        }
    )
    outcomes = refresh_enabled_local_graphs(config, refresh=refresh)
    assert refresh.calls == ["zulu", "alpha", "bravo"], "a failure stopped the loop"
    rows = local_refresh_enabled_to_jsonable(config, outcomes)["graphs"]
    assert [(row["graph_id"], row["result"], row["error_category"]) for row in rows] == [
        ("zulu", "failure", "graph-publication-in-progress"),
        ("alpha", "failure", "refresh-failed"),
        ("bravo", "failure", "contract_validation"),
    ], rows
    rendered = repr(rows)
    assert str(tmp_path) not in rendered and "secretive" not in rendered, rendered


@pytest.mark.parametrize("error", (TypeError("bug"), AttributeError("bug"), KeyError("bug")))
def test_programmer_errors_propagate_instead_of_becoming_rows(
    tmp_path: Path, error: BaseException
) -> None:
    refresh = _Refresh({"alpha": error})
    with pytest.raises(type(error)):
        refresh_enabled_local_graphs(_config(tmp_path), refresh=refresh)
    assert refresh.calls == ["zulu", "alpha"]


def test_refusal_keeps_its_path_free_text(tmp_path: Path) -> None:
    config = _config(tmp_path)
    refresh = _Refresh({"alpha": LocalRefreshError("graph 'alpha' source root is unavailable")})
    outcomes = refresh_enabled_local_graphs(config, refresh=refresh)
    payload = local_refresh_enabled_to_jsonable(config, outcomes)
    assert payload["result"] == "partial", payload
    assert payload["graphs"][1] == {
        "graph_id": "alpha", "result": "failure", "error_category": "refresh-rejected",
        "error": "graph 'alpha' source root is unavailable",
    }, payload["graphs"][1]
    table = format_local_refresh_enabled_table(config, outcomes)
    assert "result=partial" in table and "alpha | failure | - | refresh-rejected" in table, table


def test_interrupt_records_cancelled_and_stops(tmp_path: Path) -> None:
    config = _config(tmp_path)
    refresh = _Refresh({"alpha": KeyboardInterrupt()})
    outcomes = refresh_enabled_local_graphs(config, refresh=refresh)
    assert refresh.calls == ["zulu", "alpha"], "the loop continued after an interrupt"
    assert isinstance(outcomes[-1], LocalRefreshFailure) and outcomes[-1].error_category == "cancelled"
    assert local_refresh_enabled_to_jsonable(config, outcomes)["result"] == "partial"


@pytest.mark.parametrize(
    ("failing", "expected"),
    (((), "success"), (("zulu",), "partial"), (("zulu", "alpha", "bravo"), "failed")),
)
def test_aggregate_result_rule(tmp_path: Path, failing: tuple[str, ...], expected: str) -> None:
    config = _config(tmp_path)
    refresh = _Refresh({graph: LocalRefreshError(f"graph {graph!r} is disabled") for graph in failing})
    payload = local_refresh_enabled_to_jsonable(config, refresh_enabled_local_graphs(config, refresh=refresh))
    assert payload["result"] == expected, payload
    assert payload["failed_graph_count"] == len(failing)


def test_no_enabled_graph_is_success(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    home = write_sqlite_home(tmp_path / "home", graph_toml("mike", source, enabled=False))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    payload = local_refresh_enabled_to_jsonable(
        config, refresh_enabled_local_graphs(config, refresh=_Refresh({}))
    )
    assert (payload["result"], payload["graph_count"]) == ("success", 0), payload
