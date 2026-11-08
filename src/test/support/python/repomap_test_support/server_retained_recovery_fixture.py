"""Real portable-worker Server attempts for explicit metadata recovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.artifacts import FileSystemArtifactStore
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.coordinator.local_lifecycle import initialize_coordinator_control
from common_lore_index.ops import portable_refresh
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig, OpsGraphConfig
from common_lore_index.ops.generations import canonicalizer_generation, extractor_generation
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.authority import AttemptNumber, OperationId
from common_lore_index.storage.staged_ingestion import IngestionAuthority
from repomap_test_support.retrieval_evaluation_fixture import (
    materialize_mixed_v1_working_copy, write_mixed_v1_postgres_home,
)


@dataclass(frozen=True)
class RetainedServerFixture:
    home: Path
    working: Path
    config: OpsConfig
    graph: OpsGraphConfig
    postgres: Any


def prepare_retained_server(root: Path, postgres: Any) -> RetainedServerFixture:
    working = materialize_mixed_v1_working_copy(root / "working")
    home = write_mixed_v1_postgres_home(
        root / "home", working, host=postgres.host, port=postgres.port,
        database=postgres.database, user=postgres.user, password=postgres.password,
        declared_aliases=("core", "companion"),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    apply_migrations(
        default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
        psql_command=postgres.psql_command,
    )
    assert initialize_coordinator_control(home)["result"] == "ready"
    return RetainedServerFixture(home, working, config, config.graphs[0], postgres)


def direct_authority(fixture: RetainedServerFixture, operation: str) -> IngestionAuthority:
    store = FileSystemArtifactStore(fixture.home / ("authority-" + operation))
    manifest, _reference, _candidate = seal_configured_sources(
        fixture.graph, store, extractor_generation=extractor_generation(fixture.graph),
        canonicalizer_generation=canonicalizer_generation(),
    )
    return IngestionAuthority(
        operation_id=OperationId(operation), attempt=AttemptNumber(1), execution_mode="direct",
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
    ).validate()


def publish_unsettled(
    fixture: RetainedServerFixture, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> portable_refresh.PortableCapture:
    authority = direct_authority(fixture, operation)
    captured: list[portable_refresh.PortableCapture] = []
    original_capture = portable_refresh.capture_portable_candidate
    original_terminal = portable_refresh.PortableCapture.mark_terminal
    primary = RuntimeError("injected post-return settlement failure")

    def capture(*args: Any, **kwargs: Any) -> portable_refresh.PortableCapture:
        result = original_capture(*args, **kwargs)
        captured.append(result)
        return result

    def terminal(
        item: portable_refresh.PortableCapture, *, accepted: bool, sync_directory: bool = False,
    ) -> None:
        if accepted:
            raise primary
        original_terminal(item, accepted=accepted, sync_directory=sync_directory)

    with monkeypatch.context() as patch:
        patch.setattr(portable_refresh, "capture_portable_candidate", capture)
        patch.setattr(portable_refresh.PortableCapture, "mark_terminal", terminal)
        with pytest.raises(RuntimeError) as caught:
            portable_refresh.execute_portable_refresh(
                fixture.config, fixture.graph, fixture.postgres.database, authority=authority,
            )
        assert caught.value is primary
    assert len(captured) == 1
    return captured[0]


def home_files(home: Path) -> dict[str, tuple[int, bytes]]:
    """Compare owned test state without dumping its private contents."""
    import hashlib

    return {
        item.relative_to(home).as_posix(): (item.stat().st_mode & 0o777, hashlib.sha256(item.read_bytes()).digest())
        for item in home.rglob("*") if item.is_file()
    }


__all__ = ("RetainedServerFixture", "direct_authority", "home_files", "prepare_retained_server", "publish_unsettled")
