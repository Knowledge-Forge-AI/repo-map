"""Generation owner: topology arguments, refusals before any publication, PostgreSQL-only preparation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import repomap_test_support.w5_public_text_generation as generation
from repomap_test_support.w5_experiment_support import PUBLIC_ALIASES
from repomap_test_support.w5_public_text_generation import (
    DECLARED_ALIASES, GenerationRefusal, GenerationResources, materialize_generation, prepare_generation_inputs,
)
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_tasks import SelectedTaskSet

DATABASE = SimpleNamespace(host="h", port=5432, database="d", user="u", password=None, psql_command="psql")


def test_invalid_generation_or_workspace_refuses_before_any_fixture_work(tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no fixture may be materialized")

    monkeypatch.setattr(generation, "materialize_mixed_v1_working_copy", forbidden)
    for value, root in ((3, tmp_path), (True, tmp_path), (1, Path("relative"))):
        with pytest.raises(GenerationRefusal):
            materialize_generation(root, DATABASE, value)


def test_publication_topology_matches_the_retained_optional_experiment(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def record(name: str, result: Any = None):
        def call(*args: Any, **kwargs: Any) -> Any:
            calls[name] = (args, kwargs)
            return result
        return call

    state = SimpleNamespace(projection_inputs=lambda: "inputs", policy="policy", home_root=tmp_path / "home",
                            manifest="manifest", bundle="bundle", store="store")
    monkeypatch.setattr(generation, "materialize_mixed_v1_working_copy", record("working", tmp_path / "wc"))
    monkeypatch.setattr(generation, "write_mixed_v1_sqlite_home", record("sqlite_home", tmp_path / "sqlite"))
    monkeypatch.setattr(generation, "write_mixed_v1_postgres_home", record("postgres_home", tmp_path / "pg"))
    monkeypatch.setattr(generation, "publish_and_load_sqlite_corpus", record("sqlite_publish", state))
    monkeypatch.setattr(generation, "publish_and_load_postgres_corpus", record("postgres_publish", state))
    monkeypatch.setattr(generation, "build_captured_text_projection", record("projection", "projection"))
    monkeypatch.setattr(generation, "materialize_native_search_view", record("native", "view"))
    monkeypatch.setattr(generation, "generation_aliases_for", record("aliases", ("core",)))
    monkeypatch.setattr(generation, "load_graph_registry_config_home", record("config", object()))
    with pytest.raises(GenerationRefusal, match="generation_postgres_config"):
        materialize_generation(tmp_path.resolve(), DATABASE, 2)
    assert calls["working"][1] == {"generation": 2} and calls["working"][0][0].name == "working-shared"
    assert calls["sqlite_home"][0][0].name == "sqlite-shared" and calls["sqlite_home"][1]["declared_aliases"] == \
        DECLARED_ALIASES
    assert calls["postgres_home"][0][0].name == "postgres-g2" and calls["postgres_home"][1]["database"] == "d"
    assert calls["sqlite_publish"][1] == {"selected_aliases": PUBLIC_ALIASES}
    assert calls["postgres_publish"][1] == {"selected_aliases": PUBLIC_ALIASES, "psql_command": "psql"}


def test_learned_inputs_are_prepared_against_postgresql_only_and_refresh_rebuilds(
        monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[int] = []

    def build(resources: Any, selected: Any, scope: Any, **values: Any) -> tuple[Any, ...]:
        built.append(1)
        dual = SimpleNamespace(generation=1, attempt="w5-semantic-g1", identity=len(built))
        return "pin", "preparation", "census", "v1", dual

    monkeypatch.setattr(generation, "_build", build)
    monkeypatch.setattr(generation, "encode_dual_arm_request", lambda dual: b"request")
    sqlite = SimpleNamespace(postgres_reader=SimpleNamespace(backend="sqlite"))
    with pytest.raises(GenerationRefusal, match="learned_backend"):
        prepare_generation_inputs(
            cast(GenerationResources, sqlite), cast(SelectedTaskSet, None),
            scope=cast(PrivateMarkerScope, None), study_identity="s", artifact_profile_identity="p")
    postgres = SimpleNamespace(postgres_reader=SimpleNamespace(backend="postgresql"))
    prepared = prepare_generation_inputs(
        cast(GenerationResources, postgres), cast(SelectedTaskSet, None),
        scope=cast(PrivateMarkerScope, None), study_identity="s", artifact_profile_identity="p")
    dual = cast(SimpleNamespace, prepared.dual)
    assert prepared.request_raw == b"request" and dual.identity == 1
    assert cast(SimpleNamespace, prepared.refresh()).identity == 2 and len(built) == 2
    assert "pin" not in repr(prepared) and repr(prepared) == "PreparedGeneration(generation=1)"
