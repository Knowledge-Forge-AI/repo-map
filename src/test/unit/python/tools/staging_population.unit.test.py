from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_test_support.build_profile_debt import DEFERRED_BUILD_PROFILE_NODE_IDS
from runner_integration_obligations import AbruptDeclaration
from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
from runner_integration_population import (
    DuplicatePopulationNodeError,
    EmptyRequiredLegError,
    ItemCollectorPlugin,
    LegPartitionPytestPlugin,
    PopulationPartitionError,
    partition_population,
)


MEASURED = "src/test/int/python/pkg/sample.int.test.py::test_measured"
ABRUPT = "src/test/int/python/pkg/sample.int.test.py::test_abrupt"
DEFERRED = "src/test/int/python/pkg/deferred.int.test.py::test_build"
DECLARATION = AbruptDeclaration(
    ABRUPT,
    "fixture-abrupt",
    17,
    "checkpoint",
    "sample.launcher",
)
REPO_ROOT = Path(__file__).resolve().parents[5]


def _config(**options):
    deselected: list[object] = []
    hook = SimpleNamespace(
        pytest_deselected=lambda *, items: deselected.extend(items),
    )
    config = SimpleNamespace(option=SimpleNamespace(**options), hook=hook)
    config.deselected = deselected
    return config


def _item(nodeid: str, *, deferred: bool = False):
    return SimpleNamespace(
        nodeid=nodeid,
        path=Path(nodeid.split("::", 1)[0]),
        get_closest_marker=lambda name: object()
        if deferred and name == "requires_build_profile"
        else None,
    )


def test_maintained_abrupt_ids_resolve_exact_current_ast_owners() -> None:
    """Keep the closed manifest tied to real, unparameterized owner nodes."""
    node_types = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for declaration in MAINTAINED_ABRUPT_DECLARATIONS:
        path_text, *symbols = declaration.nodeid.split("::")
        source_path = REPO_ROOT / path_text
        assert source_path.is_file(), declaration.nodeid
        current: ast.AST = ast.parse(source_path.read_text(encoding="utf-8"))
        for symbol in symbols:
            matches = [
                child for child in ast.iter_child_nodes(current)
                if isinstance(child, node_types) and child.name == symbol
            ]
            assert len(matches) == 1, (declaration.nodeid, symbol)
            current = matches[0]
        assert isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef))
        assert not any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "parametrize"
            for decorator in current.decorator_list
        ), declaration.nodeid


def test_partition_preserves_raw_order_and_seals_disjoint_legs() -> None:
    raw = (DEFERRED, MEASURED, ABRUPT)
    partition = partition_population(
        (MEASURED, ABRUPT),
        declarations=(DECLARATION,),
        deferred_nodes=(DEFERRED,),
        collected_nodes=raw,
    )

    assert partition.collected_nodes == raw
    assert partition.deferred_nodes == (DEFERRED,)
    assert partition.all_nodes == (MEASURED, ABRUPT)
    assert partition.m_nodes == (MEASURED,)
    assert partition.a_nodes == (ABRUPT,)
    with pytest.raises(FrozenInstanceError):
        setattr(partition, "m_nodes", ())


def test_partition_rejects_duplicate_unknown_and_missing_population_entries() -> None:
    with pytest.raises(DuplicatePopulationNodeError):
        partition_population((MEASURED, MEASURED), declarations=(), scoped=True)
    with pytest.raises(PopulationPartitionError, match="absent from collection"):
        partition_population(
            (MEASURED,),
            declarations=(),
            deferred_nodes=(DEFERRED,),
            collected_nodes=(MEASURED,),
            scoped=True,
        )
    with pytest.raises(PopulationPartitionError, match="unknown or unresolved"):
        partition_population(
            (MEASURED, ABRUPT + "[other]"),
            declarations=(AbruptDeclaration(ABRUPT + "[exact]", "role", 17, "cp", "owner"),),
            scoped=True,
        )
    with pytest.raises(PopulationPartitionError, match="stale or missing"):
        partition_population((MEASURED,), declarations=(DECLARATION,))


def test_scoped_partition_allows_an_unselected_required_leg() -> None:
    partition = partition_population(
        (MEASURED,), declarations=(DECLARATION,), scoped=True
    )
    assert partition.m_nodes == (MEASURED,)
    assert partition.a_nodes == ()


def test_full_partition_rejects_empty_required_leg() -> None:
    with pytest.raises(EmptyRequiredLegError, match="abrupt leg"):
        partition_population((MEASURED,), declarations=())


def test_item_collector_records_raw_eligible_and_deferred_build_debt() -> None:
    deferred = tuple(DEFERRED_BUILD_PROFILE_NODE_IDS)
    raw_items = [_item(node, deferred=True) for node in deferred]
    raw_items.append(_item(MEASURED))
    config = _config()
    plugin = ItemCollectorPlugin(suite="int", full_population=True)

    plugin.pytest_collection_modifyitems(None, config, raw_items)
    plugin.pytest_collection_finish(SimpleNamespace(items=raw_items))

    assert plugin.collected_nodeids == deferred + (MEASURED,)
    assert plugin.eligible_nodeids == (MEASURED,)
    assert plugin.deferred_nodeids == deferred
    assert [item.nodeid for item in raw_items] == [MEASURED]


def test_item_collector_rejects_selector_and_post_collection_drift() -> None:
    plugin = ItemCollectorPlugin(suite="int", full_population=True)
    with pytest.raises(PopulationPartitionError, match="selectors"):
        plugin.pytest_collection_modifyitems(
            None, _config(keyword="sample"), [_item(MEASURED)]
        )

    plugin = ItemCollectorPlugin(suite="int", full_population=False)
    items = [_item(MEASURED)]
    config = _config()
    plugin.pytest_collection_modifyitems(None, config, items)
    items.append(_item(ABRUPT))
    with pytest.raises(PopulationPartitionError, match="changed"):
        plugin.pytest_collection_finish(SimpleNamespace(items=items))


def test_leg_plugin_selects_exact_nodes_and_records_lifecycle() -> None:
    partition = partition_population(
        (MEASURED, ABRUPT), declarations=(DECLARATION,), scoped=True
    )

    class Context:
        def __init__(self):
            self.selected: list[str] = []

        def select_test(self, nodeid: str) -> None:
            self.selected.append(nodeid)

    context = Context()
    items = [_item(MEASURED), _item(ABRUPT)]
    config = _config()
    plugin = LegPartitionPytestPlugin(
        partition, "A", abrupt_context=context, full_population=False
    )
    plugin.pytest_collection_modifyitems(None, config, items)
    plugin.pytest_collection_finish(SimpleNamespace(items=items))
    plugin.pytest_runtest_protocol(items[0], None)
    plugin.pytest_runtest_logreport(
        SimpleNamespace(
            when="teardown",
            nodeid=ABRUPT,
            failed=True,
            passed=False,
            skipped=False,
            longreprtext="cleanup failed",
            duration=0.0,
            location=("sample.py", 1, "test_abrupt"),
        )
    )

    assert [item.nodeid for item in items] == [ABRUPT]
    assert plugin.executed_nodeids == [ABRUPT]
    assert plugin.completed_nodeids == [ABRUPT]
    assert plugin.teardown_failed is True
    assert context.selected == [ABRUPT]
