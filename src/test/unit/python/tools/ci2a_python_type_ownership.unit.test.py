from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ci.python_type_check import (
    TypeCheckToolError,
    _distribution,
    _project_imports,
    _run_checked_mypy,
    architecture_violations,
    grouped_inventory,
    parse_mypy_errors,
    result_exit_code,
)
from ci.python_type_ownership import (
    DEFAULT_MANIFEST,
    OwnershipManifestError,
    classify_modules,
    load_manifest,
    maintained_modules,
    resolve_rule,
)


ROOT = Path(__file__).resolve().parents[5]


def _manifest(entries: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema": "repomap-python-type-ownership-v1",
        "resolution": "longest-component-prefix-wins",
        "entries": entries,
    }


def _entry(
    prefix: str,
    ownership: str = "python_retained",
    tier: str = "T1-future",
    match: str = "subtree",
) -> dict[str, str]:
    return {
        "module_prefix": prefix,
        "match": match,
        "ownership_class": ownership,
        "architecture_box": "python_semantic_engine",
        "enforcement_tier": tier,
        "justification": "Synthetic public-safe ownership fixture.",
        "disposition": "retained_python",
    }


def _write_manifest(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(_manifest(entries), sort_keys=True), encoding="utf-8")


def test_repository_manifest_is_ordered_complete_and_unambiguous() -> None:
    modules = maintained_modules(ROOT)
    manifest = load_manifest(DEFAULT_MANIFEST, modules=modules)
    classified = classify_modules(modules, manifest)

    assert len(modules) >= 400
    assert tuple(rule.module_prefix for rule in manifest.entries) == tuple(
        sorted(rule.module_prefix for rule in manifest.entries)
    )
    assert set(classified) == set(modules)
    assert all(classified[module].module_prefix for module in modules)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda entries: [*entries, entries[0]], "duplicate module prefix"),
        (
            lambda entries: [
                {**entries[0], "ownership_class": "invalid"}, *entries[1:]
            ],
            "ownership class",
        ),
        (lambda entries: list(reversed(entries)), "deterministically ordered"),
    ),
)
def test_manifest_rejects_duplicate_invalid_and_unstable_rules(
    tmp_path: Path, mutation, match: str
) -> None:
    entries = [_entry("repomap_kg.alpha"), _entry("repomap_kg.beta")]
    path = tmp_path / "ownership.json"
    _write_manifest(path, mutation(entries))

    with pytest.raises(OwnershipManifestError, match=match):
        load_manifest(path)


def test_manifest_rejects_omitted_module_and_uses_component_prefixes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ownership.json"
    _write_manifest(path, [_entry("repomap_kg.ops.refresh", match="exact")])
    manifest = load_manifest(path)

    assert resolve_rule("repomap_kg.ops.refresh", manifest) is not None
    assert resolve_rule("repomap_kg.ops.refresh_graphs", manifest) is None
    with pytest.raises(OwnershipManifestError, match="unclassified"):
        classify_modules(
            {
                "repomap_kg.ops.refresh": Path("ops/refresh.py"),
                "repomap_kg.ops.refresh_graphs": Path("ops/refresh_graphs.py"),
            },
            manifest,
        )


def test_blocking_modules_cannot_import_deferred_implementation(tmp_path: Path) -> None:
    source = tmp_path / "src/main/python"
    retained = source / "repomap_kg/retained.py"
    deferred = source / "repomap_kg/deferred.py"
    retained.parent.mkdir(parents=True)
    retained.write_text("from repomap_kg.deferred import value\n", encoding="utf-8")
    deferred.write_text("value = 1\n", encoding="utf-8")
    path = tmp_path / "ownership.json"
    _write_manifest(
        path,
        [
            _entry("repomap_kg.deferred", "planned_go", "T3", match="exact")
            | {
                "architecture_box": "go_control_plane",
                "disposition": "planned_go",
            },
            _entry("repomap_kg.retained", tier="T1-seed", match="exact"),
        ],
    )
    modules = {
        "repomap_kg.deferred": deferred,
        "repomap_kg.retained": retained,
    }
    manifest = load_manifest(path, modules=modules)

    assert architecture_violations(manifest, modules, source) == (
        "repomap_kg.retained imports T3 repomap_kg.deferred",
    )


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    (
        (
            "from repomap_kg.graph import readback\n",
            "repomap_kg.retained",
            ("repomap_kg.graph.readback",),
        ),
        (
            "from repomap_kg.coordinator import contracts\n",
            "repomap_kg.retained",
            ("repomap_kg.coordinator.contracts",),
        ),
        (
            "from repomap_kg.deferred import value\n",
            "repomap_kg.retained",
            ("repomap_kg.deferred",),
        ),
        (
            "from . import deferred\n",
            "repomap_kg",
            ("repomap_kg.deferred",),
        ),
        (
            "import repomap_kg.graph.readback\n",
            "repomap_kg.retained",
            ("repomap_kg.graph.readback",),
        ),
        (
            "from repomap_kg.graph.readback import query\n",
            "repomap_kg.retained",
            ("repomap_kg.graph.readback",),
        ),
        (
            "from repomap_kg.graph import readback, writeback\n",
            "repomap_kg.retained",
            (
                "repomap_kg.graph.readback",
                "repomap_kg.graph.writeback",
            ),
        ),
    ),
)
def test_project_imports_resolve_maintained_modules_without_treating_symbols_as_modules(
    source: str,
    package: str,
    expected: tuple[str, ...],
) -> None:
    maintained = {
        "repomap_kg.coordinator.contracts": Path("coordinator/contracts.py"),
        "repomap_kg.deferred": Path("deferred.py"),
        "repomap_kg.graph.readback": Path("graph/readback.py"),
        "repomap_kg.graph.writeback": Path("graph/writeback.py"),
    }

    assert _project_imports(ast.parse(source), package, maintained) == expected


def test_nested_import_overrides_prevent_false_negatives_and_false_positives(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/main/python"
    retained = source / "repomap_kg/retained.py"
    graph_readback = source / "repomap_kg/graph/readback.py"
    coordinator_contracts = source / "repomap_kg/coordinator/contracts.py"
    retained.parent.mkdir(parents=True)
    graph_readback.parent.mkdir(parents=True)
    coordinator_contracts.parent.mkdir(parents=True)
    retained.write_text(
        "from repomap_kg.graph import readback\n"
        "from repomap_kg.coordinator import contracts\n",
        encoding="utf-8",
    )
    graph_readback.write_text("query = object()\n", encoding="utf-8")
    coordinator_contracts.write_text("Request = object()\n", encoding="utf-8")
    path = tmp_path / "ownership.json"
    _write_manifest(
        path,
        [
            _entry("repomap_kg.coordinator", "planned_go", "T3")
            | {
                "architecture_box": "go_control_plane",
                "disposition": "planned_go",
            },
            _entry(
                "repomap_kg.coordinator.contracts",
                "cross_language_contract",
                "T0",
                match="exact",
            )
            | {
                "architecture_box": "job_contract",
                "disposition": "durable_contract",
            },
            _entry("repomap_kg.graph", tier="T1-future"),
            _entry("repomap_kg.graph.readback", "planned_go", "T3", match="exact")
            | {
                "architecture_box": "go_query_api",
                "disposition": "planned_go",
            },
            _entry("repomap_kg.retained", tier="T1-seed", match="exact"),
        ],
    )
    modules = {
        "repomap_kg.coordinator.contracts": coordinator_contracts,
        "repomap_kg.graph.readback": graph_readback,
        "repomap_kg.retained": retained,
    }
    manifest = load_manifest(path, modules=modules)

    assert architecture_violations(manifest, modules, source) == (
        "repomap_kg.retained imports T3 repomap_kg.graph.readback",
    )


def test_deferred_mypy_errors_are_grouped_but_do_not_fail_blocking_lane(
    tmp_path: Path,
) -> None:
    output = "\n".join(
        (
            "src/main/python/repomap_kg/deferred.py:3: error: Bad value 7  [arg-type]",
            "src/main/python/repomap_kg/deferred.py:9: error: Bad value 8  [arg-type]",
            "Found 2 errors in 1 file (checked 1 source file)",
        )
    )
    errors = parse_mypy_errors(output, ROOT)
    path = tmp_path / "ownership.json"
    _write_manifest(
        path,
        [
            _entry("repomap_kg.deferred", "planned_go", "T3", match="exact")
            | {
                "architecture_box": "go_control_plane",
                "disposition": "planned_go",
            }
        ],
    )
    manifest = load_manifest(path)
    inventory = grouped_inventory(errors, manifest)

    assert len(inventory) == 1
    assert inventory[0]["module"] == "repomap_kg.deferred"
    assert inventory[0]["error_code"] == "arg-type"
    assert inventory[0]["count"] == 2
    assert "message" not in inventory[0]
    assert result_exit_code(blocking_returncode=0, deferred_returncode=1) == 0
    assert result_exit_code(blocking_returncode=1, deferred_returncode=1) == 1
    assert result_exit_code(blocking_returncode=2, deferred_returncode=1) == 2


def test_root_module_finding_is_grouped_and_uses_root_distribution_bucket(
    tmp_path: Path,
) -> None:
    output = (
        "src/main/python/repomap_kg/__init__.py:3: "
        "error: Bad root value 7  [arg-type]"
    )
    errors = parse_mypy_errors(output, ROOT)
    path = tmp_path / "ownership.json"
    _write_manifest(
        path,
        [
            _entry("repomap_kg", "planned_go", "T3", match="exact")
            | {
                "architecture_box": "go_control_plane",
                "disposition": "planned_go",
            }
        ],
    )
    inventory = grouped_inventory(errors, load_manifest(path))

    assert inventory[0]["module"] == "repomap_kg"
    assert _distribution(inventory) == {
        "error_count": 1,
        "file_count": 1,
        "top_level": {"__root__": {"errors": 1, "files": 1}},
    }


def test_newly_admitted_modules_override_parent_subtree_in_manifest() -> None:
    modules = maintained_modules(ROOT)
    manifest = load_manifest(DEFAULT_MANIFEST, modules=modules)
    classified = classify_modules(modules, manifest)

    admitted = (
        "repomap_kg.artifacts.bundle",
        "repomap_kg.artifacts.receipt",
        "repomap_kg.artifacts.references",
        "repomap_kg.storage.staging_checksums",
        "repomap_kg.storage.staging_duplicate_guard",
        "repomap_kg.storage.staging_family_catalog",
        "repomap_kg.storage.staging_family_contracts",
        "repomap_kg.storage.staging_family_rows",
        "repomap_kg.storage.staging_merge_operations",
        "repomap_kg.storage.staging_operation_contracts",
        "repomap_kg.storage.staging_operation_events",
        "repomap_kg.storage.staging_phase_events",
    )
    for mod in admitted:
        assert mod in classified
        assert classified[mod].enforcement_tier == "T1-future"
        assert classified[mod].ownership_class == "python_retained"
        assert classified[mod].disposition == "retained_python_ratcheted"
        assert classified[mod].match == "exact"


def test_run_checked_mypy_empty_targets_does_not_call_mypy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ci.python_type_check._mypy",
        lambda *args, **kwargs: pytest.fail("mypy called on empty targets"),
    )
    rc, errors = _run_checked_mypy(())
    assert rc == 0 and errors == ()


def test_run_checked_mypy_propagates_findings_and_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    target = ROOT / "src/main/python/repomap_kg/cli.py"
    proc = lambda rc, out: lambda *a, **k: subprocess.CompletedProcess([], rc, out, "")
    monkeypatch.setattr("ci.python_type_check._mypy", proc(0, ""))
    assert _run_checked_mypy((target,)) == (0, ())

    finding = "src/main/python/repomap_kg/cli.py:1: error: E  [syntax]\n"
    monkeypatch.setattr("ci.python_type_check._mypy", proc(1, finding))
    rc, errors = _run_checked_mypy((target,))
    assert rc == 1 and len(errors) == 1 and errors[0].error_code == "syntax"

    monkeypatch.setattr("ci.python_type_check._mypy", proc(2, "crash"))
    with pytest.raises(TypeCheckToolError, match="exit=2"):
        _run_checked_mypy((target,))

    monkeypatch.setattr("ci.python_type_check._mypy", proc(1, "unparseable\n"))
    with pytest.raises(TypeCheckToolError, match="without parseable findings"):
        _run_checked_mypy((target,))
