"""Actual child preparation refusal preserves Local and Server publications."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.coordinator._protocol_core import SyntheticWorkerResult
from common_lore_index.ops import portable_refresh
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import LocalHarness


@contextmanager
def _backend(root: Path, backend: str) -> Iterator[tuple[Path, Path, Callable[[], object]]]:
    source = root / "source"
    materialize_mixed_v1_working_copy(source, generation=1)
    bulk = source / "core" / "pkg" / "bulk.py"
    bulk.write_text("".join(f"def function_{i}():\n    return {i}\n\n" for i in range(4201)), encoding="utf-8")
    home = root / "home"
    if backend == "sqlite":
        write_mixed_v1_sqlite_home(home, source)
        initialized = LocalHarness(root / "guarded", block_psycopg=True).run(
            "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json",
        )
        assert initialized.returncode == 0, initialized.stderr
        local = load_graph_registry_config_home(home)
        assert isinstance(local, LocalSqliteConfig)
        yield home, bulk, lambda: refresh_local_graph(local, MIXED_V1_GRAPH_ID)
        return
    with temporary_postgres() as postgres:
        write_mixed_v1_postgres_home(
            home, source, host=postgres.host, port=postgres.port, database=postgres.database,
            user=postgres.user, password=postgres.password, declared_aliases=("core", "companion"),
        )
        server = load_graph_registry_config_home(home)
        assert isinstance(server, OpsConfig)
        apply_migrations(
            default_rdbms_root(), server.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        yield home, bulk, lambda: refresh_graph(server, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command)


def _pin(home: Path, output: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    result = cli_main([
        "ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--binding", binding_id_for_alias("core"), "--binding", binding_id_for_alias("companion"),
        "--pin-publication", "--output", str(output),
    ])
    captured = capsys.readouterr()
    assert result == 0 and captured.err == "", captured.err
    record = json.loads(captured.out)
    pin = record["expected_publication"]
    assert isinstance(pin, dict) and type(pin["generation"]) is int
    return pin


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
