from __future__ import annotations

import ast
from src.test.unit.python.repomap_kg.architecture.import_graph_support import (
    _import_graph, _strongly_connected_components,
)


TRANSITIONAL_COMPONENTS: set[frozenset[str]] = set()

ALLOWED_TEST_SUPPORT_REFERENCES: set[tuple[str, str]] = set()


def test_production_import_graph_has_only_accepted_transitional_cycles() -> None:
    graph, _ = _import_graph()

    assert _strongly_connected_components(graph) == TRANSITIONAL_COMPONENTS


def test_production_does_not_import_test_support() -> None:
    _, trees = _import_graph()
    imported_test_modules: set[tuple[str, str]] = set()
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                targets = (node.module or "",)
            else:
                continue
            imported_test_modules.update(
                (module, target)
                for target in targets
                if target == "repomap_test_support"
                or target.startswith("repomap_test_support.")
            )

    assert imported_test_modules == set()


def test_production_does_not_reference_test_support() -> None:
    _, trees = _import_graph()
    references = {
        (module, node.value)
        for module, tree in trees.items()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (
            "repomap_test_support" in node.value
            or "src/test/support" in node.value
        )
    }

    assert references == ALLOWED_TEST_SUPPORT_REFERENCES


def test_telemetry_contract_and_compatibility_facades_share_objects() -> None:
    import repomap_kg.storage.backend_telemetry_contracts as contracts
    import repomap_kg.storage.backend_telemetry_events as events
    import repomap_kg.storage.backend_connection_telemetry as connection
    import repomap_kg.storage.backend_telemetry as facade
    for name in (
        "ConnectionTelemetryError",
        "ConnectionTelemetryEvent",
        "TelemetryEventKind",
    ):
        assert getattr(events, name) is getattr(contracts, name)
        assert getattr(facade, name) is getattr(contracts, name)
    assert facade.BackendTelemetry is connection.BackendTelemetry
