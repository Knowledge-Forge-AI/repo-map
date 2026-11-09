"""Frozen census: materialized generations, exclusion, alias constants and input isolation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import pytest

import first_use_workload_census as census
from first_use_workload_census import (
    CENSUS_RELATIVE, FIXTURE_RELATIVE, PYTHON_SOURCES, REPO_ROOT, decode_census, fixture_digest,
    inventory_digest, is_selected, load_census, project, read_bounded, verify_fixture,
)
from first_use_workload_domains import ALIASES, MAX_CENSUS_BYTES, WorkloadError
from first_use_workload_recipe import ALL_ALIASES, SERVER_ALIASES
from repomap_test_support.first_use_workload_driver import StaleInput
from repomap_test_support.first_use_workload_witness import census_facts, materialized_entries
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS, MIXED_V1_FIXTURE_ROOT, materialize_mixed_v1_working_copy,
)

# Frozen-census receipt values recorded when the parent froze the census.
CENSUS_SHA256 = "70abf4ace551d6512d9fa70ca5dd38672ee628c795f6bf25fe36c7fdf86e7ede"
FIXTURE_SHA256 = "9f125b4c08dabab7c8ba24375ad06872f86b73f9e98b1377d8d7b2dcdec86528"
PROJECTIONS = {
    (1, ALL_ALIASES): (1445746, 0, 26), (1, SERVER_ALIASES): (1442700, 0, 22),
    (2, ALL_ALIASES): (1445986, 0, 26), (2, SERVER_ALIASES): (1442940, 0, 22),
}


def _census_bytes() -> bytes:
    return (REPO_ROOT / CENSUS_RELATIVE).read_bytes()


def _mutated(change: Any) -> bytes:
    payload = json.loads(_census_bytes())
    change(payload)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _category(data: bytes) -> str:
    with pytest.raises(WorkloadError) as error:
        decode_census(data)
    return error.value.category


def test_committed_census_matches_its_freeze_receipt() -> None:
    census = load_census()
    assert census.digest == CENSUS_SHA256
    assert census.fixture_digest == FIXTURE_SHA256
    assert [len(item.entries) for item in census.generations] == [27, 27]
    for (generation, aliases), expected in PROJECTIONS.items():
        projection = census.generation(generation).projection(aliases)
        assert (projection.S, projection.C, projection.files) == expected


def test_fixture_digest_recomputes_from_committed_inputs_only() -> None:
    census = load_census()
    assert fixture_digest() == census.fixture_digest
    verify_fixture(census)


@pytest.mark.parametrize("generation", [1, 2])
def test_materialized_generation_equals_the_frozen_census(tmp_path: Path, generation: int) -> None:
    census = load_census()
    working = materialize_mixed_v1_working_copy(tmp_path / "copy", generation=generation)
    assert tuple(materialized_entries(working)) == census.generation(generation).entries
    facts = census_facts(working, census, generation, ALL_ALIASES)
    assert (facts["S"], facts["C"], facts["files"]) == PROJECTIONS[(generation, ALL_ALIASES)]


def test_materialized_drift_is_stale_input(tmp_path: Path) -> None:
    census = load_census()
    working = materialize_mixed_v1_working_copy(tmp_path / "copy", generation=1)
    (working / "core" / "pkg" / "pipeline.py").write_text("drifted\n", encoding="utf-8")
    with pytest.raises(StaleInput):
        census_facts(working, census, 1, ALL_ALIASES)
    with pytest.raises(StaleInput):
        census_facts(working, census, 2, ALL_ALIASES)


def test_only_companion_excluded_cache_is_unselected() -> None:
    census = load_census()
    unselected = {(alias, rel) for item in census.generations for alias, rel, *_r, selected in item.entries
                  if not selected}
    assert unselected == {("companion", "excluded_cache/unselected_scratch.txt")}
    assert not is_selected("companion", "excluded_cache/nested/x.txt")
    assert is_selected("core", "excluded_cache/x.txt")
    assert is_selected("companion", "excluded_cache_like/x.txt")


def test_alias_constants_match_test_support() -> None:
    assert ALIASES == MIXED_V1_BINDINGS == ALL_ALIASES
    assert MIXED_V1_FIXTURE_ROOT == (REPO_ROOT / FIXTURE_RELATIVE).resolve()


@pytest.mark.parametrize("rel", ["../tasks/gold.json", "/abs/path", "core\\pkg.py", "a//b", "./x", "x/../y"])
def test_non_fixture_paths_are_refused(rel: str) -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["generations"][0]["entries"][0][1] = rel

    assert _category(_mutated(change)) == "stale_input"


def test_unknown_alias_and_inconsistent_totals_are_stale() -> None:
    def alias(payload: dict[str, Any]) -> None:
        payload["generations"][0]["entries"][-1][0] = "tasks"

    def total(payload: dict[str, Any]) -> None:
        payload["generations"][1]["bytes_total"] += 1

    def projection(payload: dict[str, Any]) -> None:
        payload["generations"][0]["projections"][1]["S"] -= 1

    def selection(payload: dict[str, Any]) -> None:
        payload["generations"][0]["entries"][3][4] = True

    for change in (alias, total, projection, selection):
        assert _category(_mutated(change)) == "stale_input", change.__name__


def test_noncanonical_and_oversized_census_bytes_are_refused() -> None:
    data = _census_bytes()
    assert _category(data.replace(b'","', b'", "', 1)) == "stale_input"
    assert _category(data[:-1]) == "stale_input"
    assert _category(b" " * (MAX_CENSUS_BYTES + 1)) == "too_large"


def test_projection_counts_duplicate_digests_in_s_and_c() -> None:
    digest_a, digest_b = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    entries = (
        ("companion", "excluded_cache/z", digest_a, 999, False),
        ("companion", "x.txt", digest_a, 100, True),
        ("core", "dup.txt", digest_a, 100, True),
        ("core", "one.txt", digest_b, 40, True),
        ("feeds", "f.xml", digest_a, 100, True),
    )
    both = project(entries, ("core", "companion"))
    assert (both.S, both.C, both.files) == (240, 100, 3)
    every = project(entries, ALL_ALIASES)
    assert (every.S, every.C, every.files) == (340, 200, 4)
    assert project(entries, ("core",)).C == 0


def test_inventory_digest_is_order_independent() -> None:
    rows = [["core", "b", "sha256:" + "1" * 64, 2], ["core", "a", "sha256:" + "2" * 64, 3]]
    assert inventory_digest(rows) == inventory_digest(list(reversed(rows)))
    assert inventory_digest(rows[:1]) != inventory_digest(rows)


def test_fixture_census_opens_only_alias_trees_and_python_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = (REPO_ROOT / FIXTURE_RELATIVE).resolve()
    opened: list[Path] = []
    real_open = census.os.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> int:
        if isinstance(file, (str, os.PathLike)):
            opened.append(Path(file).resolve())
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(census.os, "open", spy)
    fixture_digest()
    monkeypatch.undo()
    assert opened
    allowed_tops = set(ALIASES) | {PYTHON_SOURCES}
    for path in opened:
        relative = path.relative_to(fixture)
        assert relative.parts[0] in allowed_tops, relative
        assert not {"tasks", "golds", "gold", "held-out", "held_out", "trials"} & set(relative.parts)


def test_fixture_tree_symlink_is_unsafe(tmp_path: Path) -> None:
    for alias in ALIASES:
        (tmp_path / alias).mkdir()
    (tmp_path / PYTHON_SOURCES).write_text("{}\n", encoding="utf-8")
    (tmp_path / "core" / "file.txt").write_text("x\n", encoding="utf-8")
    assert len(fixture_digest(tmp_path)) == 64
    (tmp_path / "core" / "link.txt").symlink_to(tmp_path / "core" / "file.txt")
    with pytest.raises(WorkloadError) as error:
        fixture_digest(tmp_path)
    assert error.value.category == "unsafe_input"


def test_census_reader_is_bounded_and_non_following(tmp_path: Path) -> None:
    target = tmp_path / "census.json"
    target.write_bytes(b"{}\n")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(WorkloadError) as error:
        read_bounded(link, 10)
    assert error.value.category == "unsafe_input"
    with pytest.raises(WorkloadError) as error:
        read_bounded(target, 2)
    assert error.value.category == "too_large"
    assert read_bounded(target, 3) == b"{}\n"


def test_fixture_source_missing_is_unreadable(tmp_path: Path) -> None:
    for alias in ALIASES:
        (tmp_path / alias).mkdir()
    with pytest.raises(WorkloadError) as error:
        fixture_digest(tmp_path)
    assert error.value.category == "unreadable"


def test_fixture_member_limit_stops_before_any_body_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for alias in ALIASES:
        (tmp_path / alias).mkdir()
    names = [f"file-{index}.txt" for index in range(2 * census.MAX_CENSUS_ENTRIES + 1)]

    def walk(root: Path, **_kwargs: Any) -> Any:
        yield root, [], names
        raise AssertionError("fixture walk continued after entry limit")

    def forbidden_read(*_args: Any) -> bytes:
        raise AssertionError("fixture bodies read after entry limit")

    monkeypatch.setattr(census.os, "walk", walk)
    monkeypatch.setattr(census, "read_bounded", forbidden_read)
    with pytest.raises(WorkloadError) as error:
        fixture_digest(tmp_path)
    assert error.value.category == "too_large"


def test_fixture_canonical_row_size_refuses_with_a_closed_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for alias in ALIASES:
        (tmp_path / alias).mkdir()
    (tmp_path / PYTHON_SOURCES).write_bytes(b"{}\n")
    monkeypatch.setattr(census, "MAX_CENSUS_BYTES", 8)
    with pytest.raises(WorkloadError) as error:
        fixture_digest(tmp_path)
    assert error.value.category == "too_large"


def test_fixture_walk_oserror_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for alias in ALIASES:
        (tmp_path / alias).mkdir()
    (tmp_path / PYTHON_SOURCES).write_text("{}\n", encoding="utf-8")

    def failing_walk(_root: Path, *, followlinks: bool, onerror: Any) -> Any:
        assert followlinks is False
        onerror(OSError("walk failed"))
        yield from ()

    monkeypatch.setattr(census.os, "walk", failing_walk)
    with pytest.raises(WorkloadError) as error:
        fixture_digest(tmp_path)
    assert error.value.category == "unreadable"


def test_bounded_reader_maps_fstat_and_read_oserrors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "census.json"
    target.write_bytes(b"{}\n")

    def failing_fstat(_descriptor: int) -> Any:
        raise OSError("fstat failed")

    monkeypatch.setattr(census.os, "fstat", failing_fstat)
    with pytest.raises(WorkloadError) as error:
        read_bounded(target, 10)
    assert error.value.category == "unreadable"
    monkeypatch.undo()

    class FailingReader:
        def __enter__(self) -> FailingReader:
            return self

        def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> Literal[False]:
            return False

        def read(self, _limit: int) -> bytes:
            raise OSError("read failed")

    def failing_fdopen(*_args: Any, **kwargs: Any) -> FailingReader:
        assert kwargs == {"closefd": False}
        return FailingReader()

    monkeypatch.setattr(census.os, "fdopen", failing_fdopen)
    with pytest.raises(WorkloadError) as error:
        read_bounded(target, 10)
    assert error.value.category == "unreadable"
