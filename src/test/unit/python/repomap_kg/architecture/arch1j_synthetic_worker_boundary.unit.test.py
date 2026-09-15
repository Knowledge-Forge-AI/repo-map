from __future__ import annotations

from types import ModuleType
from pathlib import Path


def _source(module: ModuleType) -> str:
    assert module.__file__ is not None
    return Path(module.__file__).read_text(encoding="utf-8")


def test_arch1j_production_has_no_synthetic_test_adapter_ownership() -> None:
    from repomap_kg.coordinator import _protocol_core, _worker_launch, core, protocol

    combined = "\n".join(_source(module) for module in (_protocol_core, _worker_launch, core, protocol))

    assert "repomap_test_support" not in combined
    assert "src/test/support/python" not in combined
    assert "ALLOWED_SYNTHETIC_WORKER_MODES" not in combined
    assert "for_synthetic_worker" not in combined
    assert "def run_synthetic_worker" not in combined


def test_arch1j_test_support_owns_synthetic_worker_adapter() -> None:
    import repomap_test_support.synthetic_worker_adapter as adapter
    import repomap_kg.coordinator.protocol as protocol

    assert callable(adapter.run_synthetic_worker)
    assert callable(adapter.build_synthetic_coordinator)
    assert adapter.WorkerLaunchSpec is protocol.WorkerLaunchSpec
    assert adapter.ALLOWED_SYNTHETIC_WORKER_MODES
