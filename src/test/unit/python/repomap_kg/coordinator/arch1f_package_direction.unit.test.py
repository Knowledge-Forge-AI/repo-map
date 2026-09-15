from __future__ import annotations

import ast
from pathlib import Path


from types import ModuleType


def _coordinator_imports(module: ModuleType) -> set[str]:
    file_path = module.__file__
    assert file_path is not None
    path = Path(file_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_protocol_facade_preserves_launch_and_contract_identities() -> None:
    import repomap_kg.coordinator.protocol as protocol
    import repomap_kg.coordinator._protocol_core as protocol_core
    import repomap_kg.coordinator._worker_launch as worker_launch
    import repomap_kg.coordinator.refresh_adapter as refresh_adapter
    import repomap_kg.coordinator._refresh_contracts as refresh_contracts

    assert getattr(protocol, "ProtocolError") is getattr(protocol_core, "ProtocolError")
    assert (
        getattr(protocol, "SyntheticWorkerResult")
        is getattr(protocol_core, "SyntheticWorkerResult")
    )
    assert getattr(protocol, "ProtocolSession") is getattr(protocol_core, "ProtocolSession")
    assert getattr(protocol, "WorkerLaunchSpec") is getattr(worker_launch, "WorkerLaunchSpec")
    assert getattr(protocol, "run_worker_spec").__module__ == getattr(protocol, "__name__")
    assert callable(getattr(worker_launch, "run_worker_spec"))
    assert getattr(protocol, "run_refresh_worker") is getattr(refresh_adapter, "run_refresh_worker")
    assert (
        getattr(refresh_adapter, "RefreshConfigurationError")
        is getattr(refresh_contracts, "RefreshConfigurationError")
    )
    assert (
        getattr(refresh_adapter, "RefreshGenerationChangedError")
        is getattr(refresh_contracts, "RefreshGenerationChangedError")
    )


def test_coordinator_internal_imports_follow_one_direction() -> None:
    from repomap_kg.coordinator import _protocol_core, _worker_launch, refresh_adapter, _refresh_execution

    assert not (
        _coordinator_imports(_protocol_core)
        & {
            "repomap_kg.coordinator._worker_launch",
            "repomap_kg.coordinator.protocol",
            "repomap_kg.coordinator.refresh_adapter",
        }
    )
    assert "repomap_kg.coordinator.protocol" not in _coordinator_imports(_worker_launch)
    assert "repomap_kg.coordinator.protocol" not in _coordinator_imports(refresh_adapter)
    assert "repomap_kg.coordinator.refresh_adapter" not in _coordinator_imports(_refresh_execution)
    assert "repomap_kg.coordinator._refresh_contracts" in _coordinator_imports(_refresh_execution)
