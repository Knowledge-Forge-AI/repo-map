from __future__ import annotations

from pathlib import Path
import tempfile
from typing import cast
from unittest.mock import patch

from common_lore_index.ops.config import load_ops_config_home
from common_lore_index.ops.refresh import _load_file_observations_with_ops_psql
from common_lore_index.runtime.local import setup_local_runtime
from common_lore_index.storage import LoadSummary
from common_lore_index.storage.authority import AttemptNumber, OperationId
from common_lore_index.storage.backend_telemetry import BackendTelemetry
from common_lore_index.storage.staged_ingestion import IngestionAuthority


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
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        setup_local_runtime(home)
        config = load_ops_config_home(home)

        with patch(
            "common_lore_index.ops.refresh.run_staged_full_refresh",
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
