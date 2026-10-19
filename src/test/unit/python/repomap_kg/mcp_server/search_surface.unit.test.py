"""Real static Python publication separates indexed identities from source text.

File observations/manifests use the existing synthetic fixture seam; Python AST
extraction, canonicalization, SQLite publication and public dispatch are real.
The fixture source is read as text only and must never be executed.
"""

from __future__ import annotations

from pathlib import Path
import source_navigation_consumer as consumer_module
import sqlite3
from typing import Any

import pytest

from repomap_kg.server import mcp
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.navigation_search_fixtures import (
    BINDING, GRAPH, navigation_bundle,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, local_binding, publication_for, write_sqlite_home

BODY_SOURCE = '''__all__ = ["normalize_label"]
public_labels = []
# orchard_comment
def normalize_label(value):
    note = "orchard_body_literal"
    if value is None:
        raise ValueError("orchard_error")
    return value.strip()
raise AssertionError("fixture source must never execute")
'''


@pytest.fixture
def source_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, tmp_path / "workspace"))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    config.graph_store_root.mkdir(parents=True)
    database = config.graph_store_root / f"{GRAPH}.sqlite3"
    initialize_graph_database(database, local_binding(GRAPH), applied_at="2026-10-15T00:00:00Z")
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    source = tmp_path / "workspace" / "src" / "subject.py"
    source.parent.mkdir(parents=True)
    source.write_text(BODY_SOURCE, encoding="utf-8")
    publish_source(database, BODY_SOURCE, 1)
    return database, source


def publish_source(database: Path, text: str, generation: int) -> None:
    bundle = navigation_bundle(generation=generation, markdown_sources={},
                               python_sources={"src/subject.py": text})
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families,
                       expected_generation=generation - 1)


def call(name: str, **arguments: Any) -> dict[str, Any]:
    response = mcp.handle_tool_call(name, {"graph_id": GRAPH, **arguments})
    assert not response.get("isError")
    return response["structuredContent"]


@pytest.mark.parametrize("literal", ["__all__", "public_labels", "orchard_body_literal",
                                     "orchard_comment", "orchard_error", "if value is None"])
def test_body_only_literal_is_visible_natively_but_complete_empty_in_node_search(
    source_store: tuple[Path, Path], literal: str,
) -> None:
    database, source = source_store
    assert literal in source.read_text(encoding="utf-8")
    with sqlite3.connect(database) as connection:
        identities = connection.execute("SELECT canonical_key, kind, display_name FROM canonical_nodes").fetchall()
    assert identities and all(literal not in (field or "") for row in identities for field in row)
    raw = call("repomap_search_nodes", query=literal)
    assert raw["results"] == [] and raw["has_more"] is False
    for scope in ("code", "all"):
        navigation = call("repomap_navigation_search", query=literal, scope=scope, grouping="none")
        assert navigation["status"] == "ok" and navigation["scan"]["complete"] is True
        assert navigation["results"] == [] and navigation["has_more"] is False
    # A true extracted identity in the same publication remains reachable.
    hit = call("repomap_search_nodes", query="normalize_label")
    assert [row["display_name"] for row in hit["results"]] == ["normalize_label"]


@pytest.mark.parametrize("name", ["__all__", "orchard_body_literal"])
def test_same_spelling_as_real_indexed_subject_hits_and_consumer_verifies(
    source_store: tuple[Path, Path], name: str,
) -> None:
    database, source = source_store
    text = f'def {name}():\n    return "named subject"\n'
    source.write_text(text, encoding="utf-8")
    publish_source(database, text, 2)
    raw = call("repomap_search_nodes", query=name)
    key = f"python.function:src.subject:{name}"
    assert [row["canonical_key"] for row in raw["results"]] == [key]
    navigation = call("repomap_navigation_search", query=name, scope="code")
    assert navigation["status"] == "ok" and navigation["scan"]["complete"] is True
    assert [member["canonical_key"] for group in navigation["results"] for member in group["members"]] == [key]
    navigate = vars(consumer_module)["navigate"]
    result = navigate(graph_id=GRAPH, repository_identity="repo1:navigation", bindings={BINDING: source.parents[1]},
                      query=name, tool_call=mcp.handle_tool_call, source_check=lambda selected: selected == text)
    assert result["branch"] == "search_locator" and result["outcome"] == "verified"
    assert result["graph_calls"] == 2
    assert [event["tool"] for event in result["trace"] if event["action"] == "tool_call"] == [
        "repomap_search_nodes", "repomap_node_locations",
    ]


def test_file_fields_and_retained_observation_payload_are_distinct_from_source_body(source_store: tuple) -> None:
    for query in ("src/subject.py", "python", "source"):
        files = call("repomap_search_files", query=query, path="root/src/subject.py")
        assert [row["path"] for row in files["results"]] == ["root/src/subject.py"]
    assert call("repomap_search_files", query="orchard_body_literal")["results"] == []
    query = '"async": false'
    assert call("repomap_search_nodes", query=query)["results"] == []
    brief = call("repomap_search_observations", query=query, kind="python.function", path="root/src/subject.py")
    full = call("repomap_search_observations", query=query, kind="python.function", path="root/src/subject.py",
                include_raw=True)
    assert len(brief["results"]) == 1 and "payload" not in brief["results"][0]
    assert brief["results"] == [{key: value for key, value in row.items() if key != "payload"}
                                for row in full["results"]]
    assert full["results"][0]["payload"]["metadata"]["async"] is False
    assert call("repomap_search_observations", query="orchard_body_literal")["results"] == []
