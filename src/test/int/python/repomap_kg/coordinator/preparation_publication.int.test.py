"""Actual child preparation refusal preserves Local and Server publications."""
from __future__ import annotations
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import pytest
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.coordinator._protocol_core import SyntheticWorkerResult
from common_lore_index.ops import portable_refresh
from repomap_test_support.portable_publication_context import publication_backend as _backend, accepted_pin as _pin

@contextmanager
def _bounded_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[list[PortableExecutionCapability], list[SyntheticWorkerResult]]]:
    original_capability = portable_refresh.create_portable_capability
    original_worker = portable_refresh.run_portable_worker
    capabilities: list[PortableExecutionCapability] = []
    workers: list[SyntheticWorkerResult] = []

    def limited(directory: Path, capability: PortableExecutionCapability) -> Path:
        bounded = replace(capability, max_bundle_bytes=8192)
        capabilities.append(bounded)
        return original_capability(directory, bounded)

    def run(*args, **kwargs):
        result = original_worker(*args, **kwargs)
        workers.append(result)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(portable_refresh, "create_portable_capability", limited)
        patch.setattr(portable_refresh, "run_portable_worker", run)
        yield capabilities, workers


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_spawned_preparation_refusal_preserves_the_accepted_pin_and_allows_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], backend: str,
) -> None:
    with _backend(tmp_path, backend) as (home, bulk, refresh):
        refresh()
        before = _pin(home, tmp_path / "before.json", capsys)
        original_generation = before["generation"]
        assert isinstance(original_generation, int)
        bulk.write_text(bulk.read_text(encoding="utf-8") + "ADDED = 1\n", encoding="utf-8")
        with _bounded_worker(monkeypatch) as (capabilities, workers):
            if backend == "sqlite":
                with pytest.raises(ValueError):
                    refresh()
            else:
                refused = refresh()
                assert getattr(refused, "result", None) == "failure"
                assert getattr(refused, "publication_state", None) == "not_started"
        assert len(capabilities) == len(workers) == 1
        worker = workers[0]
        assert worker.protocol_error is None and worker.cleanup_error is None
        assert worker.returncode == 0 and worker.terminal["status"] == "failed"
        assert worker.terminal["error_category"] == "contract_validation"
        phases = [message["phase"] for message in worker.messages if message.get("message_type") == "progress"]
        assert "canonicalization" in phases and "storage_prepare" not in phases
        assert _pin(home, tmp_path / "after.json", capsys) == before
        assert not list(tmp_path.rglob("repomap-stage-rows-*.jsonl"))
        refresh()
        recovered = _pin(home, tmp_path / "recovered.json", capsys)
        assert recovered != before
        recovered_generation = recovered["generation"]
        assert isinstance(recovered_generation, int)
        assert recovered_generation > original_generation
