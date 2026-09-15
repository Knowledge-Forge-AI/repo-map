from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from repomap_kg.ops.config import OpsConfig
from repomap_kg.ops.refresh import _load_file_observations_with_ops_psql
from repomap_kg.storage import LoadSummary
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.staged_ingestion import IngestionAuthority


def _authority() -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("scale9j-direct"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:fixture",
        config_generation="cg1:fixture",
        extractor_generation="eg1:fixture",
        canonicalizer_generation="kg1:fixture",
    )


def test_staged_loader_forwards_opt_in_backend_telemetry() -> None:
    telemetry = cast(BackendTelemetry, object())
    config = cast(
        OpsConfig,
        SimpleNamespace(
            postgres=SimpleNamespace(
                psql_args_for_database=lambda _database: ["-d", "fixture"]
            )
        ),
    )

    with patch(
        "repomap_kg.ops.refresh.run_staged_full_refresh",
        return_value=LoadSummary(repository_id=1, run_id=2, files=3),
    ) as load:
        result = _load_file_observations_with_ops_psql(
            config,
            "fixture",
            (),
            repository_name="fixture",
            root_path="fixture-root",
            repository_identity="repo1:fixture",
            psql_command=None,
            ingestion_mode="staged",
            staged_authority=_authority(),
            backend_telemetry=telemetry,
        )

    assert result.files == 3
    assert load.call_args.kwargs["backend_telemetry"] is telemetry
    assert load.call_args.kwargs["repository_identity"] == "repo1:fixture"
