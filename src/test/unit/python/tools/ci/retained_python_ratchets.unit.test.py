from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci.python_type_ownership import load_manifest
from ci.retained_python_ratchets import (
    compare_counted,
    compare_file_lengths,
    file_length_inventory,
    migration_edges,
    mypy_inventory,
    normalize_ruff_inventory,
    select_retained_modules,
)


def ownership_entry(
    prefix: str,
    ownership_class: str,
    tier: str,
    *,
    match: str = "exact",
) -> dict[str, str]:
    return {
        "module_prefix": prefix,
        "match": match,
        "ownership_class": ownership_class,
        "architecture_box": "synthetic_public_fixture",
        "enforcement_tier": tier,
        "justification": "Synthetic public-safe ownership fixture.",
        "disposition": "synthetic_fixture",
    }


def write_manifest(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "repomap-python-type-ownership-v1",
                "resolution": "longest-component-prefix-wins",
                "entries": entries,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def selection_fixture(tmp_path: Path):
    source = tmp_path / "src/main/python/repomap_kg"
    paths = {
        "repomap_kg.contract": source / "contract.py",
        "repomap_kg.future": source / "future.py",
        "repomap_kg.future.override": source / "future/override.py",
        "repomap_kg.transitional": source / "transitional.py",
        "repomap_kg.planned": source / "planned.py",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "ownership.json"
    write_manifest(
        manifest_path,
        [
            ownership_entry("repomap_kg.contract", "cross_language_contract", "T0"),
            ownership_entry("repomap_kg.future", "python_retained", "T1-future", match="subtree"),
            ownership_entry("repomap_kg.future.override", "planned_go", "T3"),
            ownership_entry("repomap_kg.planned", "planned_go_or_rust", "T3"),
            ownership_entry("repomap_kg.transitional", "transitional_python", "T2"),
        ],
    )
    return paths, load_manifest(manifest_path, modules=paths)


def test_retained_selection_uses_ownership_resolution_and_exact_overrides(
    tmp_path: Path,
) -> None:
    source_paths, manifest = selection_fixture(tmp_path)

    selected = select_retained_modules(source_paths, manifest, tmp_path)

    assert [(item["module"], item["tier"]) for item in selected] == [
        ("repomap_kg.contract", "T0"),
        ("repomap_kg.future", "T1-future"),
    ]
    assert all(item["path"].startswith("src/main/python/") for item in selected)


def test_unclassified_maintained_module_is_rejected(tmp_path: Path) -> None:
    module = tmp_path / "src/main/python/repomap_kg/unclassified.py"
    module.parent.mkdir(parents=True)
    module.write_text("value = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "ownership.json"
    write_manifest(
        manifest_path,
        [ownership_entry("repomap_kg.other", "python_retained", "T1-future")],
    )

    with pytest.raises(ValueError, match="unclassified"):
        load_manifest(
            manifest_path,
            modules={"repomap_kg.unclassified": module},
        )


def test_ruff_identity_ignores_line_and_column_but_preserves_semantics(
    tmp_path: Path,
) -> None:
    path = "src/main/python/repomap_kg/future.py"
    common = {"filename": path, "code": "F401", "message": "  `name` imported   but unused "}
    first = normalize_ruff_inventory(
        [{**common, "location": {"row": 2, "column": 1}}],
        frozenset({path}),
        tmp_path,
    )
    moved = normalize_ruff_inventory(
        [{**common, "location": {"row": 200, "column": 17}}],
        frozenset({path}),
        tmp_path,
    )
    changed = normalize_ruff_inventory(
        [{**common, "message": "`other` imported but unused"}],
        frozenset({path}),
        tmp_path,
    )

    assert first == moved
    assert first != changed
    assert first[0]["message"] == "`name` imported but unused"
    assert "row" not in first[0] and "column" not in first[0]


def test_mypy_identity_reuses_line_independent_normalized_fingerprint(
    tmp_path: Path,
) -> None:
    path = "src/main/python/repomap_kg/future.py"
    module_path = tmp_path / path
    module_path.parent.mkdir(parents=True)
    module_path.write_text("value = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "ownership.json"
    write_manifest(
        manifest_path,
        [ownership_entry("repomap_kg.future", "python_retained", "T1-future")],
    )
    manifest = load_manifest(manifest_path)
    selected = frozenset({"repomap_kg.future"})

    first = mypy_inventory(
        f"{path}:3:2: error: Bad value 7  [arg-type]\n",
        manifest,
        selected,
        tmp_path,
    )
    moved = mypy_inventory(
        f"{path}:90:30: error: Bad value 8  [arg-type]\n",
        manifest,
        selected,
        tmp_path,
    )

    assert first == moved
    assert first[0]["count"] == 1
    assert "line" not in first[0]


def test_new_and_removed_findings_are_both_policy_deltas() -> None:
    baseline = ({"path": "a.py", "fingerprint": "old", "count": 1},)
    actual = ({"path": "a.py", "fingerprint": "new", "count": 1},)

    comparison = compare_counted(actual, baseline, ("path", "fingerprint"))

    assert comparison["new"] == list(actual)
    assert comparison["removed"] == list(baseline)
    assert comparison["increased"] == []
    assert comparison["decreased"] == []


def test_count_increase_and_decrease_are_distinct_policy_deltas() -> None:
    baseline = ({"path": "a.py", "fingerprint": "same", "count": 2},)

    increased = compare_counted(
        ({"path": "a.py", "fingerprint": "same", "count": 3},),
        baseline,
        ("path", "fingerprint"),
    )
    decreased = compare_counted(
        ({"path": "a.py", "fingerprint": "same", "count": 1},),
        baseline,
        ("path", "fingerprint"),
    )

    assert increased["increased"][0]["actual_count"] == 3
    assert decreased["decreased"][0]["actual_count"] == 1


def test_t1_future_import_edges_into_t2_and_t3_are_ratcheted(tmp_path: Path) -> None:
    source_paths, manifest = selection_fixture(tmp_path)
    future = source_paths["repomap_kg.future"]
    future.write_text(
        "from repomap_kg import transitional\nimport repomap_kg.planned\n",
        encoding="utf-8",
    )

    edges = migration_edges(manifest, source_paths, tmp_path)

    assert [(edge["target_module"], edge["target_tier"]) for edge in edges] == [
        ("repomap_kg.planned", "T3"),
        ("repomap_kg.transitional", "T2"),
    ]
    assert all(edge["source_module"] == "repomap_kg.future" for edge in edges)


def test_file_length_ratchet_rejects_growth_and_requires_downward_refresh(
    tmp_path: Path,
) -> None:
    relative = "src/main/python/repomap_kg/future.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x\n" * 450)
    selection = (
        {
            "module": "repomap_kg.future",
            "path": relative,
            "ownership_class": "python_retained",
            "tier": "T1-future",
        },
    )
    actual, hard = file_length_inventory(selection, tmp_path)

    assert hard == ()
    assert actual == ({"path": relative, "line_count": 450},)
    assert compare_file_lengths(actual, ())["new"] == list(actual)
    assert compare_file_lengths(actual, ({"path": relative, "line_count": 440},))[
        "increased"
    ][0]["actual_line_count"] == 450
    assert compare_file_lengths(actual, ({"path": relative, "line_count": 460},))[
        "decreased"
    ][0]["actual_line_count"] == 450

    path.write_bytes(b"x\n" * 400)
    below, hard = file_length_inventory(selection, tmp_path)
    assert hard == () and below == ()
    assert compare_file_lengths(below, actual)["removed"] == list(actual)


def test_selected_file_above_one_thousand_is_always_hard_failure(
    tmp_path: Path,
) -> None:
    relative = "src/main/python/repomap_kg/future.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x\n" * 1001)
    selection = (
        {
            "module": "repomap_kg.future",
            "path": relative,
            "ownership_class": "python_retained",
            "tier": "T1-future",
        },
    )

    actual, hard = file_length_inventory(selection, tmp_path)

    assert actual == ()
    assert hard == ({"path": relative, "line_count": 1001},)


def test_compare_counted_debt_reduction_is_permitted() -> None:
    actual = ({"path": "foo.py", "code": "F401", "message": "unused", "fingerprint": "a", "count": 1},)
    baseline = ({"path": "foo.py", "code": "F401", "message": "unused", "fingerprint": "a", "count": 2},)
    comparison = compare_counted(actual, baseline, ("path", "code", "message", "fingerprint"))
    assert len(comparison["decreased"]) == 1
    assert len(comparison["increased"]) == 0
    assert len(comparison["new"]) == 0
