"""MULTISOURCE-STATUS-FIX1: native fixture publication tuple and status-versus-stored-facts checks.

The HOST1 native run reported ``repository_exists: false`` for the populated
``host-multi`` graph because the fixture stored it under the name
``host-multi`` while the name-selected status family looks up the configured
``[multi-source]`` token. No database is started here: the publishers are
recorders on the fixture module object, and ``status_checks`` is pure.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_kg.ops import portable_refresh
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.refresh import refresh_graph
from smoke import host_mcp_native_fixture as fixture
from smoke.host_mcp_native_checks import NativePlan, status_checks

MULTI, FEED = "host-multi", "host-feed"


def _databases() -> dict[str, Any]:
    return {graph_id: SimpleNamespace(database=f"native_{graph_id.split('-')[1]}_unit", psql_args=["-d", "unused"],
                                      psql_command="psql") for graph_id in (MULTI, FEED)}


def test_fixture_publishes_host_multi_under_its_configured_repository_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: dict[str, dict[str, Any]] = {}

    def publish(psql_args: list[str], observations: Any, **kwargs: Any) -> None:
        published[kwargs["repository_identity"]] = {**kwargs, "paths": {item.path for item in observations}}

    monkeypatch.setattr(fixture, "apply_migrations", lambda *args, **kwargs: None)
    monkeypatch.setattr(fixture, "provision_roles", lambda *args, **kwargs: None)
    monkeypatch.setattr(fixture, "publish_observation_generation", publish)
    work = tmp_path / "work"
    work.mkdir()
    result = fixture.publish_native_fixture(work, "fixture_admin", _databases(), 55432)

    graphs = {graph.id: graph for graph in load_ops_config_home(result.home).graphs}
    multi, feed = published["repo1:host-multi"], published["repo1:host-feed"]
    assert graphs[MULTI].repository_name == "[multi-source]"
    assert multi["repository_name"] == graphs[MULTI].repository_name, multi["repository_name"]
    assert multi["root_path"] == result.roots[MULTI] == "graph:host-multi"
    assert {path.split("/", 1)[0] for path in multi["paths"] if "/" in path} == {"alpha", "beta"}
    assert feed["repository_name"] == graphs[FEED].repository_name == FEED
    assert set(published) == {"repo1:host-multi", "repo1:host-feed"} and not result.sources.exists()


@pytest.mark.parametrize("graph_id", [MULTI, FEED])
def test_configured_publication_is_the_tuple_supported_refresh_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, graph_id: str,
) -> None:
    home, _, graphs = fixture.stage_native_config(tmp_path, 55432, "native_multi_unit", "native_feed_unit")
    (tmp_path / "sources" / "feed" / "notes.sh").write_text("echo feed\n", encoding="utf-8")
    calls: list[dict[str, Any]] = []

    def publish(psql_args: Any, bundle: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(repository_id=1, run_id=2, files=1)

    monkeypatch.setattr(portable_refresh, "run_staged_portable_refresh", publish)
    result = refresh_graph(load_ops_config_home(home), graph_id)

    assert result.result == "success", result.to_jsonable()
    expected = fixture.configured_publication(graphs[graph_id])
    assert expected["root_path"] == f"graph:{graph_id}" and expected["repository_identity"] == f"repo1:{graph_id}"
    assert len(calls) == 1 and {name: calls[0][name] for name in expected} == expected


STORED = {
    MULTI: {"repository_rows": 1, "name": "[multi-source]", "latest_run_id": 1, "latest_run_status": "complete",
            "raw_observations": 14, "canonical_nodes": 9, "canonical_edges": 9},
    FEED: {"repository_rows": 1, "name": FEED, "latest_run_id": 1, "latest_run_status": "complete",
           "raw_observations": 15, "canonical_nodes": 14, "canonical_edges": 15},
}
NAMES = {MULTI: "[multi-source]", FEED: FEED}


def _entry(graph_id: str, **overrides: Any) -> dict[str, Any]:
    facts = STORED[graph_id]
    return {"graph_id": graph_id, "repository_name": NAMES[graph_id], "repository_exists": True, "error": None,
            "latest_run_id": facts["latest_run_id"], "latest_run_status": "complete",
            "raw_observations": facts["raw_observations"], "canonical_nodes": facts["canonical_nodes"],
            "canonical_edges": facts["canonical_edges"], "publication": None, **overrides}


def _responses(multi: dict[str, Any], *, visible: list[dict[str, Any]] | None = None) -> dict[int, Any]:
    def result(content: Any) -> dict[str, Any]:
        return {"result": {"structuredContent": content}}

    summary = {"latest_run_id": 1, "repository_name": "[multi-source]",
               "counts": {"canonical_nodes": 9, "canonical_edges": 9, "canonical_evidence": 14, "files": 3,
                          "raw_observations": 14, "runs": 1}}
    return {32: result({"summary": summary}), 35: result({"graphs": [multi, _entry(FEED)] if visible is None
                                                          else visible}),
            36: result({"storage": multi}), 37: result({"graphs": [multi]})}


def _plan(stored: dict[str, Any] | None = None) -> NativePlan:
    return NativePlan(chain={"stored_status": stored or STORED, "configured_repository_names": NAMES})


def test_status_checks_accept_only_status_matching_stored_facts() -> None:
    assert status_checks(_plan(), _responses(_entry(MULTI))) == dict.fromkeys((
        "multi_graph_status_matches_stored", "multi_refresh_status_matches_stored",
        "all_visible_status_matches_stored", "multi_status_agrees_with_summary",
        "multi_stored_name_is_configured"), True)

    # The HOST1-observed shape: parity with the maintained owner, but absent against populated stored facts.
    host1 = _entry(MULTI, repository_exists=False, latest_run_id=None, latest_run_status=None,
                   raw_observations=0, canonical_nodes=0, canonical_edges=0)
    host1_stored = {**STORED, MULTI: {**STORED[MULTI], "name": "host-multi"}}
    assert not any(status_checks(_plan(host1_stored), _responses(host1)).values())

    # A decoy selection: exists, but its run and counts belong to another repository.
    decoy = _entry(MULTI, latest_run_id=2, raw_observations=15, canonical_nodes=14, canonical_edges=15)
    checks = status_checks(_plan(), _responses(decoy))
    assert checks.pop("multi_stored_name_is_configured") and not any(checks.values())


def test_status_checks_are_false_on_ordering_ambiguity_or_missing_messages() -> None:
    reordered = status_checks(_plan(), _responses(_entry(MULTI), visible=[_entry(FEED), _entry(MULTI)]))
    assert reordered["all_visible_status_matches_stored"] is False
    assert reordered["multi_graph_status_matches_stored"] is True

    ambiguous = {**STORED, MULTI: {**STORED[MULTI], "repository_rows": 2}}
    assert status_checks(_plan(ambiguous), _responses(_entry(MULTI)))["multi_graph_status_matches_stored"] is False

    missing = status_checks(_plan(), {32: {"result": {"structuredContent": {"summary": None}}}})
    assert missing.pop("multi_stored_name_is_configured") and not any(missing.values())
    assert not any(status_checks(NativePlan(), {}).values())
