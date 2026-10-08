"""SQLite Local summary operations and their PostgreSQL JSONB predicate semantics.

The ``raw_payload`` table fixes the PostgreSQL meaning of ``->>``, ``::boolean``,
``?``, ``LIKE``, C-locale ``UPPER`` and ``jsonb::text``. Each family is then
read from the crafted public-safe corpus and checked against counters derived
by hand from ``CORPUS_ROWS`` and the maintained PostgreSQL builders, including
the NULL-operand rows that ``<>``/``NOT LIKE`` must not count. Same-input
comparison with the PostgreSQL owners is an integration claim.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage import (
    js_framework_summary_to_jsonable,
    nix_summary_to_jsonable,
    openapi_summary_to_jsonable,
    python_summary_to_jsonable,
    terraform_summary_to_jsonable,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sqlite_local import (
    api_summary_queries,
    nix_summary_queries,
    raw_payload,
    summary_queries,
)
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database, read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.sqlite_local_fixtures import local_binding, publication_for
from repomap_test_support.sqlite_local_read_corpus import read_corpus_bundle

BINDING = local_binding()
ROOT = "graph:portable-fixture"


def test_text_at_follows_postgresql_arrow_operators() -> None:
    payload = raw_payload.load(
        '{"metadata":{"s":"x","t":true,"f":false,"n":7,"big":1e+20,"z":null,"o":{"bb":1,"a":[1,"x"]}},'
        '"list":[1]}'
    )
    assert [raw_payload.meta(payload, key) for key in ("s", "t", "f", "n", "big", "z", "missing")] == [
        "x", "true", "false", "7", "100000000000000000000", None, None]
    assert raw_payload.meta(payload, "o") == '{"a": [1, "x"], "bb": 1}'
    assert raw_payload.text_at(payload, "list", "x") is None  # non-object parent is NULL
    assert raw_payload.text_at(payload, "metadata", "s", "deeper") is None


def test_jsonb_text_renders_like_postgresql() -> None:
    value = raw_payload.load('{"bb":[true,null],"a":"q\\"\\\\\\n\\u0001é","ccc":{},"d":-0.0,"e":1.50}')
    assert raw_payload.jsonb_text(value) == (
        '{"a": "q\\"\\\\\\n\\u0001é", "d": 0.0, "e": 1.50, "bb": [true, null], "ccc": {}}')
    assert raw_payload.jsonb_text(Decimal("1.5E-7")) == "0.00000015"
    assert raw_payload.jsonb_value({"b": 1, "a": 2}) == {"a": 2, "b": 1}
    assert list(raw_payload.jsonb_value({"bb": 1, "c": 2})) == ["c", "bb"]


@pytest.mark.parametrize(("text", "expected"), [
    (None, False), ("true", True), ("TRUE", True), ("t", True), ("tr", True), (" yes ", True),
    ("y", True), ("on", True), ("1", True), ("false", False), ("f", False), ("no", False),
    ("n", False), ("off", False), ("of", False), ("0", False),
])
def test_flag_accepts_postgresql_boolean_spellings(text: str | None, expected: bool) -> None:
    assert raw_payload.flag(text) is expected


@pytest.mark.parametrize("text", ["", "o", "maybe", "2", "truex", "10", "nope"])
def test_flag_refuses_where_the_postgresql_cast_errors(text: str) -> None:
    with pytest.raises(StorageSchemaError):
        raw_payload.flag(text)


def test_predicates_use_where_clause_null_semantics() -> None:
    assert raw_payload.like("repomapXkg/x.py", "%repomap_kg%")  # ``_`` stays a wildcard
    assert not raw_payload.like("Requirements.txt", "requirements%")  # case-sensitive
    assert raw_payload.like("100%", "100\\%") and not raw_payload.like("100x", "100\\%")
    assert raw_payload.like("a\nb/c", "%/c")
    assert (raw_payload.like(None, "%"), raw_payload.not_like(None, "%x%")) == (False, False)
    assert (raw_payload.ne(None, "x"), raw_payload.is_in(None, ("x",))) == (False, False)
    assert raw_payload.not_like("block-limit", "%x%") and raw_payload.ne("a", "b")
    assert raw_payload.has_key({"program": None}, "program")
    assert raw_payload.has_key(["program", 1], "program") and not raw_payload.has_key([1], "1")
    assert not raw_payload.has_key(None, "program")
    assert raw_payload.ascii_upper("get-é") == "GET-é" and raw_payload.basename("a/b/flake.nix") == "flake.nix"


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "corpus.sqlite3"
    initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z")
    bundle = read_corpus_bundle()
    publish_generation(path, publication_for(bundle), bundle.families, expected_generation=0)
    with read_transaction(path, BINDING) as opened:
        yield opened


def _summary(connection: sqlite3.Connection, family: str) -> dict[str, Any]:
    owners: dict[str, tuple[Callable[..., Any], Callable[[Any], Any]]] = {
        "python": (summary_queries.python_summary, python_summary_to_jsonable),
        "terraform": (summary_queries.terraform_summary, terraform_summary_to_jsonable),
        "openapi": (api_summary_queries.openapi_summary, openapi_summary_to_jsonable),
        "js_framework": (api_summary_queries.js_framework_summary, js_framework_summary_to_jsonable),
        "nix": (nix_summary_queries.nix_summary, nix_summary_to_jsonable),
    }
    read, serialize = owners[family]
    payload = serialize(read(connection, root_path=ROOT))
    assert isinstance(payload, dict)
    return payload


def test_python_summary_counts_the_corpus_branches(connection: sqlite3.Connection) -> None:
    summary = _summary(connection, "python")
    assert (summary["root_path"], summary["repository_name"]) == (ROOT, "portable-fixture")
    assert summary["python_observations"] == 18
    assert summary["package_files"] == {"requirements": 2, "pyproject": 1}
    assert summary["tests"]["fixtures"] == 2 and summary["frameworks"]["fastapi_dependencies"] == 1
    assert summary["references"] == {
        "total": 5, "package_refs": 3, "local_file_refs": 2, "direct_urls_not_fetched": 2,
        "index_urls_not_fetched": 1, "framework_refs": 1}
    assert summary["redactions"] == {
        "credentialed_urls": 1, "private_indexes": 1, "secret_like_config": 1, "framework_settings": 1}
    assert summary["diagnostics"] == {"parse_errors": 3, "limit_overflows": 1, "dynamic_constructs": 2}
    assert summary["generic_config"] == {"config_documents": 1, "config_paths": 2, "config_references": 1}
    assert summary["dogfooding"]["repo_map_profile_observed"] is True


def test_terraform_summary_keeps_null_operands_out_of_negations(connection: sqlite3.Connection) -> None:
    summary = _summary(connection, "terraform")
    assert (summary["terraform_observations"], summary["terraform_files"]) == (16, 5)
    assert summary["file_families"] == {"tf": 1, "tfvars": 1, "terraform.tfvars": 2, "auto.tfvars": 1}
    references = summary["references"]
    assert (references["version_constraints"], references["module_sources"]) == (2, 2)
    assert references["remote_refs_not_fetched"] == 1  # a NULL reference_kind is not ``<>``
    assert summary["diagnostics"] == {"parse_errors": 3, "limit_overflows": 1, "malformed_hcl": 1}
    assert summary["tfvars"] == {"files": 4, "variables": 1, "literal_values_exposed": False}
    assert summary["redactions"]["backend_values"] == summary["redactions"]["secret_like_fields"] == 1
    assert summary["generic_config"]["file_nodes"] == 1


def test_openapi_and_js_framework_summaries_count_the_corpus(connection: sqlite3.Connection) -> None:
    openapi = _summary(connection, "openapi")
    assert (openapi["openapi_observations"], openapi["openapi_documents"]) == (11, 2)
    assert openapi["spec_families"] == {"openapi3": 1, "swagger2": 1}
    assert {k: v for k, v in openapi["methods"].items() if v} == {"GET": 1, "POST": 1}
    assert openapi["references"] == {
        "internal_refs": 1, "local_file_refs": 0, "remote_refs_not_fetched": 1,
        "external_docs_not_fetched": 1, "refs_not_fetched": 2}
    assert openapi["redactions"]["credentialed_urls"] == openapi["redactions"]["example_summaries"] == 1
    assert (openapi["diagnostics"]["limit_overflows"], openapi["diagnostics"]["malformed_specs"]) == (1, 1)
    assert openapi["generic_config"]["config_parse_errors"] == 1
    js = _summary(connection, "js_framework")
    assert js["framework_observations"] == 5
    assert js["framework_profiles"] == {
        "node": 0, "express": 2, "nest": 0, "next": 1, "jest": 1, "jquery": 0, "generic_js": 1}
    assert (js["express"]["routes"], js["express"]["dynamic_routes"]) == (2, 1)
    assert js["node"]["env_references"] == 1 and js["next"]["route_handlers"] == 1
    assert js["diagnostics"] == {"framework_observation_limit": 0, "framework_selector_limit": 1}


def test_nix_summary_counts_sections_programs_paths_and_shapes(connection: sqlite3.Connection) -> None:
    summary = _summary(connection, "nix")
    assert summary["root_path"] == "[root-path]"  # the PostgreSQL literal, not the graph root
    assert (summary["nix_observations"], summary["nix_files"], summary["flake_files"]) == (8, 1, 2)
    assert summary["programs"] == {"app_programs_total": 2, "local": 1, "dynamic": 0, "external": 0,
                                   "unknown": 0}
    assert summary["paths"]["repo_escaping_or_rejected"] == 1
    inputs = summary["flake_inputs"]
    assert (inputs["with_url"], inputs["with_follows"], inputs["source_types"]["github"]) == (1, 1, 1)
    assert summary["output_sections"]["by_section"]["packages"] == 1
    assert summary["output_sections"]["by_shape"]["direct_assignment"] == 1
    assert summary["dynamic_output_shapes"]["by_pattern"]["flake-utils"] == 1
    assert summary["unsupported_flake_shapes"]["by_pattern"]["imported_outputs"] == 1
    assert summary["canonical"]["apps"] == 1 and summary["canonical"]["output_sections"] == 1
    assert summary["edges"]["output_defines"] == 2 and summary["edges"]["import_sources"] == 1
    assert summary["generic_config"]["config_redactions"] == 2
    assert summary["diagnostics"] == {
        "missing_output_identity": 1, "dynamic_imports": 1, "unknown_imports": 1,
        "unknown_app_programs": 0, "raw_only_path_refs": 1, "flake_files_without_output_observations": 1}


def test_summaries_refuse_unpublished_graphs_and_invalid_flags(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z")
    with read_transaction(path, BINDING) as opened:
        for family in ("python", "terraform", "openapi", "js_framework", "nix"):
            with pytest.raises(LocalStoreError) as caught:
                _summary(opened, family)
            assert caught.value.code == "graph-publication-absent"
    bad = tmp_path / "bad.sqlite3"
    initialize_graph_database(bad, BINDING, applied_at="2026-09-29T00:00:00Z")
    bundle = read_corpus_bundle(extra_rows=(("express.route", "x.js", {"dynamic": "sometimes"}, {}),))
    publish_generation(bad, publication_for(bundle), bundle.families, expected_generation=0)
    with read_transaction(bad, BINDING) as opened, pytest.raises(StorageSchemaError):
        _summary(opened, "js_framework")
