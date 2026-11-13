"""Actual child artifact-bound refusal preserves accepted Local/Server state."""
from __future__ import annotations
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import pytest
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.coordinator._protocol_core import SyntheticWorkerResult
from common_lore_index.ops import portable_refresh
from repomap_test_support.portable_publication_context import publication_backend, accepted_pin


@contextmanager
def _artifact_bounded_worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[list[PortableExecutionCapability], list[SyntheticWorkerResult]]]:
    original_capability = portable_refresh.create_portable_capability
    original_worker = portable_refresh.run_portable_worker
    capabilities: list[PortableExecutionCapability] = []
    workers: list[SyntheticWorkerResult] = []

    def limited(directory, capability):
        bounded = replace(capability, max_artifact_bytes=capability.manifest_reference.size_bytes)
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
def test_real_child_materialization_refusal_keeps_the_accepted_pin_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], backend: str,
) -> None:
    with publication_backend(tmp_path, backend) as (home, bulk, refresh):
        refresh()
        before = accepted_pin(home, tmp_path / "before.json", capsys)
        bulk.write_text(bulk.read_text(encoding="utf-8") + "AFTER = 1\n", encoding="utf-8")
        with _artifact_bounded_worker(monkeypatch) as (capabilities, workers):
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
        assert worker.terminal["error_category"] == "artifact_bounds"
        assert bulk.stat().st_size > capabilities[0].max_artifact_bytes
        phases = [m["phase"] for m in worker.messages if m.get("message_type") == "progress"]
        assert "discovery" in phases and "extraction" not in phases
        assert accepted_pin(home, tmp_path / "after.json", capsys) == before
        assert not list(capabilities[0].workspace_root.glob("attempt-*"))
        refresh()
        assert accepted_pin(home, tmp_path / "recovered.json", capsys) != before
