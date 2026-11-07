"""ADR0155 native guest import retention witness; host-side static contract only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from common_lore_index.extractors.rust_pilot.guest import parse_helper, runtime_probe
    assert callable(parse_helper.main)
    assert callable(runtime_probe.main)

from ci.python_retention_dependencies import build_dependency_graph
from ci.python_retention_dynamic import apply_dynamic_boundaries
from ci.python_retention_dynamic_history import SCHEMA, active_boundaries


OWNERS = (
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/parse_helper.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/runtime_probe.py",
)
LOCK = "src/main/python/common_lore_index/extractors/rust_pilot/component_lock.py"
TEST = "src/test/unit/python/tools/ci/python_retention_native_guest_import.unit.test.py"


def _write(root: Path, records: list[dict]) -> None:
    path = root / "tools/ci/python_retention_inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dynamic_schema": SCHEMA, "dynamic_boundaries": records}))


def _fixture(tmp_path: Path) -> tuple[list[str], list[dict]]:
    source_root = Path(__file__).resolve().parents[6]
    inventory = json.loads((source_root / "tools/ci/python_retention_inventory.json").read_bytes())
    records = [copy.deepcopy(item) for item in active_boundaries(inventory)
               if item["recipe"] == "external_native_guest_import"]
    assert len(records) == 2
    paths = [*OWNERS, LOCK, TEST]
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / path).read_bytes())
    return paths, records


def _refresh_owner_digest(tmp_path: Path, records: list[dict], path: str) -> None:
    digest = hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()
    for record in records:
        if record["owner"] == path:
            record["owner_sha256"] = digest
        for owner in record["parameters"]["guest_owners"]:
            if owner["path"] == path:
                owner["sha256"] = digest


def test_native_guest_pair_closes_without_project_edges(tmp_path: Path) -> None:
    paths, records = _fixture(tmp_path)
    graph = build_dependency_graph(tmp_path, paths)
    before = {owner: list(graph["dependencies"].get(owner, ())) for owner in OWNERS}
    _write(tmp_path, records)
    graph = apply_dynamic_boundaries(tmp_path, paths, graph)
    assert graph["resolved_dynamic_dependencies"] == {record["id"]: [] for record in records}
    assert all(owner not in graph["dynamic_uncertainty"] for owner in OWNERS)
    assert all(graph["dependencies"].get(owner, []) == before[owner] for owner in OWNERS)


@pytest.mark.parametrize("fault", [
    "wrong-owner", "wrong-names", "alias", "attribute-mutation", "mutator",
    "extra-site", "stale-lock", "digest-drift",
])
def test_native_guest_pair_refuses_open_or_drifted_declarations(
        tmp_path: Path, fault: str) -> None:
    paths, records = _fixture(tmp_path)
    if fault == "wrong-owner":
        records[1]["owner"] = records[0]["owner"]
        records[1]["owner_sha256"] = records[0]["owner_sha256"]
    elif fault == "wrong-names":
        for record in records:
            record["parameters"]["modules"][1] = "other"
    elif fault == "stale-lock":
        for record in records:
            record["parameters"]["component_lock_sha256"] = "0" * 64
    elif fault in {"alias", "attribute-mutation", "mutator", "extra-site"}:
        path = tmp_path / OWNERS[0]
        suffix = {
            "alias": b"\nimport_module = importlib.import_module\n",
            "attribute-mutation": b"\nimportlib.import_module = object()\n",
            "mutator": b'\nsetattr(importlib, "import_module", object())\n',
            "extra-site": (
                b'\nfor name in ("tree_sitter", "tree_sitter_rust"):\n'
                b"    modules.append(importlib.import_module(name))\n"
            ),
        }[fault]
        path.write_bytes(path.read_bytes() + suffix)
        _refresh_owner_digest(tmp_path, records, OWNERS[0])
    else:
        path = tmp_path / OWNERS[0]
        path.write_bytes(path.read_bytes() + b"\n# drift\n")
    _write(tmp_path, records)
    graph = apply_dynamic_boundaries(tmp_path, paths,
                                     build_dependency_graph(tmp_path, paths))
    assert all(owner in graph["dynamic_uncertainty"] for owner in OWNERS)
    assert not set(record["id"] for record in records) & set(
        graph.get("resolved_dynamic_dependencies", {}))
