from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.run_authority import (
    RunStatus,
    build_run_authority_query_sql,
    parse_run_authority,
    read_run_authority,
)


def test_arch1a_authority_contract_is_typed_and_closed() -> None:
    spec = importlib.util.find_spec("repomap_kg.storage.authority")
    assert spec is not None, "ARCH1A requires a neutral authority contract"
    import repomap_kg.storage.authority as authority
    assert authority.RequestId("request-1") == "request-1"
    assert authority.OperationId("operation-1") == "operation-1"
    assert authority.JobId("job-1") == "job-1"
    assert authority.AttemptNumber(1) == 1
    assert authority.GraphRunId(2) == 2
    assert authority.StageId(cast(str, 3)) == cast(str, 3)
    assert tuple(result.value for result in authority.RefreshResult) == (
        "success",
        "failure",
    )
    assert tuple(result.value for result in authority.PublicationResult) == (
        "not_published",
        "published",
        "commit_unknown",
    )


def test_arch1a_generation_tuple_is_the_storage_compatibility_type() -> None:
    spec = importlib.util.find_spec("repomap_kg.storage.authority")
    assert spec is not None, "ARCH1A requires a neutral generation tuple"
    import repomap_kg.storage.authority as authority
    import repomap_kg.storage.publication as publication
    generations = authority.PublicationGenerations(
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
    ).validate()

    assert authority.PublicationGenerations.field_names() == (
        "source_generation",
        "config_generation",
        "extractor_generation",
        "canonicalizer_generation",
    )
    assert publication.RunPublicationGenerations is authority.PublicationGenerations
    assert isinstance(generations, publication.RunPublicationGenerations)


def test_arch1a_direct_and_coordinator_generation_tuples_are_equal() -> None:
    spec = importlib.util.find_spec("repomap_kg.storage.authority")
    assert spec is not None, "ARCH1A requires a neutral generation tuple"
    import repomap_kg.storage.authority as authority
    import repomap_kg.coordinator.refresh_adapter as refresh_adapter
    import repomap_kg.storage.staged_ingestion as staged_ingestion
    generations = authority.PublicationGenerations(
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
    )
    direct = staged_ingestion.IngestionAuthority(
        operation_id=authority.OperationId("operation-1"),
        attempt=authority.AttemptNumber(1),
        execution_mode="direct",
        source_generation=generations.source_generation,
        config_generation=generations.config_generation,
        extractor_generation=generations.extractor_generation,
        canonicalizer_generation=generations.canonicalizer_generation,
    )
    coordinator = refresh_adapter.RefreshCapability(
        schema_version=1,
        job_id="job-1",
        attempt=1,
        graph_id="public",
        config_path=Path("/public/config.toml"),
        psql_path=Path("/public/bin/psql"),
        postgres_user="repomap_refresh_publication",
        postgres_password="public-safe",
        executable_search_path=(Path("/public/bin"),),
        source_generation=generations.source_generation,
        config_generation=generations.config_generation,
        extractor_generation=generations.extractor_generation,
        canonicalizer_generation=generations.canonicalizer_generation,
    )

    assert direct.receipt().generations == generations
    assert coordinator.publication_generations() == generations


def test_arch1a_authority_query_names_each_freshness_concept() -> None:
    sql = build_run_authority_query_sql("public-repository")

    assert "latest_recorded_run" in sql
    assert "latest_successful_import" in sql
    assert "latest_receipt_bearing_publication" in sql
    assert "publication_job_id IS NULL" in sql
    assert "publication_job_id IS NOT NULL" in sql
    assert "'run_authority'" in sql


def test_arch1a_authority_parser_rejects_malformed_payloads() -> None:
    with pytest.raises(StorageSchemaError, match="malformed run authority"):
        parse_run_authority({})

    with pytest.raises(StorageSchemaError, match="malformed run authority"):
        parse_run_authority(
            {
                "run_authority": {
                    "latest_recorded_run": {
                        "run_id": 0,
                        "status": RunStatus.COMPLETE,
                        "started_at": "2026-07-16T00:00:00Z",
                        "finished_at": "2026-07-16T00:00:01Z",
                    },
                    "latest_successful_import": None,
                    "latest_receipt_bearing_publication": None,
                }
            }
        )


def test_arch1a_authority_readback_uses_dedicated_typed_query() -> None:
    completed = SimpleNamespace(
        stdout=json.dumps(
            {
                "run_authority": {
                    "latest_recorded_run": None,
                    "latest_successful_import": None,
                    "latest_receipt_bearing_publication": None,
                }
            }
        )
    )
    with patch(
        "repomap_kg.storage.run_authority.run_psql",
        return_value=completed,
    ) as run:
        snapshot = read_run_authority(
            ["-d", "postgres"],
            "public-repository",
        )

    assert snapshot.latest_recorded_run is None
    assert snapshot.latest_successful_import is None
    assert snapshot.latest_receipt_bearing_publication is None
    assert run.call_args.args[0][0] == "psql"
    assert "latest_receipt_bearing_publication" in run.call_args.args[0][-1]
