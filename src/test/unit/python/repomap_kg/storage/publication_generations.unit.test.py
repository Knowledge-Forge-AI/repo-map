from collections.abc import Mapping
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch
import json

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage import publication
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_readback import (
    read_latest_publication,
    read_run_publication,
)
from repomap_kg.storage.sql_load import (
    file_load_summary_select_sql,
    repository_run_prefix_sql,
)
from repomap_kg.storage.summary_rows_storage import load_summary_from_payload


def generations(**updates: str) -> RunPublicationGenerations:
    values = {
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
    }
    values.update(updates)
    return RunPublicationGenerations(**values)


def receipt(
    *,
    attempt: RunPublicationAttempt | None = None,
    generations_: RunPublicationGenerations | None = None,
    portable: PortablePublicationBinding | None = None,
    **updates: object,
) -> RunPublicationReceipt:
    eff_attempt = attempt or RunPublicationAttempt(JobId("job-refresh-1"), AttemptNumber(2))
    eff_generations = generations_ or generations()
    if portable is not None:
        return RunPublicationReceipt(eff_attempt, eff_generations, portable)
    return RunPublicationReceipt(eff_attempt, eff_generations)


def portable_binding(
    *,
    route: str = "portable-worker-v1",
    snapshot_manifest_id: str = "snapmanifest1:" + "1" * 64,
    snapshot_vector: tuple[tuple[str, int, str], ...] = (("bind1:" + "2" * 64, 1, "snap1:" + "3" * 64),),
    extraction_receipt_id: str = "receipt1:" + "4" * 64,
    publication_bundle_id: str = "bundle1:" + "5" * 64,
    candidate_id: str = "cand1:" + "6" * 64,
    resolver_identity: str = "resolver1:nix-static-v2",
    canonicalizer_identity: str = "canon1:graph-key-v1-binding-path",
    semantic_contract_identity: str = "semantic1:multi-source-v1",
    quality_rule_identity: str = "quality1:default",
    protocol_version: str = "1.0",
    worker_capability_identity: str = "cap1:portable-worker-v1",
    stage_id: str = "stage-publisher-owned",
    execution_mode: str = "coordinator",
    singleton_fencing_epoch: int = 7,
    graph_lease_fencing_epoch: int = 9,
    family_receipts: Mapping[str, Mapping[str, object]] | None = None,
) -> PortablePublicationBinding:
    if family_receipts is None:
        family_receipts = {
            family: {
                "count": 1,
                "byte_length": 10,
                "digest": "sha256:" + "7" * 64,
            }
            for family in (
                "files", "raw_observations", "canonical_nodes",
                "canonical_edges", "canonical_evidence",
                "canonical_node_evidence", "canonical_edge_evidence",
            )
        }
    return PortablePublicationBinding(
        route=route,
        snapshot_manifest_id=snapshot_manifest_id,
        snapshot_vector=snapshot_vector,
        extraction_receipt_id=extraction_receipt_id,
        publication_bundle_id=publication_bundle_id,
        candidate_id=candidate_id,
        resolver_identity=resolver_identity,
        canonicalizer_identity=canonicalizer_identity,
        semantic_contract_identity=semantic_contract_identity,
        quality_rule_identity=quality_rule_identity,
        protocol_version=protocol_version,
        worker_capability_identity=worker_capability_identity,
        stage_id=stage_id,
        execution_mode=execution_mode,
        singleton_fencing_epoch=singleton_fencing_epoch,
        graph_lease_fencing_epoch=graph_lease_fencing_epoch,
        family_receipts=family_receipts,
    )


def test_run_publication_generations_are_exact_bounded_tokens():
    assert generations().validate() == generations()
    for field, value in (
        ("source_generation", "cg1:wrong"),
        ("config_generation", "cg1:contains/slash"),
        ("extractor_generation", "eg1:"),
        ("canonicalizer_generation", "kg1:" + "x" * 128),
    ):
        with pytest.raises(ValueError, match="invalid publication generations"):
            generations(**{field: value}).validate()


def test_publication_attempt_is_bounded_and_positive():
    assert receipt().validate() == receipt()
    for attempt in (
        RunPublicationAttempt(JobId(""), AttemptNumber(1)),
        RunPublicationAttempt(JobId("command--unsafe"), AttemptNumber(1)),
        RunPublicationAttempt(JobId("job-refresh-1"), AttemptNumber(0)),
        publication.RunPublicationAttempt(JobId("job-refresh-1"), cast(AttemptNumber, True)),
    ):
        with pytest.raises(ValueError, match="invalid publication attempt"):
            attempt.validate()


def test_portable_receipt_binding_is_complete_canonical_and_not_fabricated_for_legacy():
    legacy = receipt().validate()
    assert legacy.portable is None
    assert "snapshot_manifest_id" not in legacy.to_mapping()

    bound = receipt(portable=portable_binding()).validate()
    assert bound.portable is not None
    mapping = bound.to_mapping()
    assert mapping["snapshot_manifest_id"] == bound.portable.snapshot_manifest_id
    assert mapping["publication_bundle_id"] == bound.portable.publication_bundle_id
    assert mapping["portable_stage_id"] == "stage-publisher-owned"
    snapshot_vector_json = mapping["snapshot_vector_json"]
    assert isinstance(snapshot_vector_json, str)
    assert "bind1:" in snapshot_vector_json
    family_receipts_json = mapping["family_receipts_json"]
    assert isinstance(family_receipts_json, str)
    assert family_receipts_json.startswith("{")

    with pytest.raises(ValueError, match="portable publication binding"):
        receipt(
            portable=portable_binding(publication_bundle_id="bundle1:wrong")
        ).validate()


def test_public_portable_projection_redacts_physical_and_artifact_locations():
    bound = receipt(portable=portable_binding()).validate()
    assert bound.portable is not None

    public = bound.public_mapping()

    assert public["execution_route"] == "portable-worker-v1"
    assert public["snapshot_manifest_id"] == bound.portable.snapshot_manifest_id
    assert public["publication_bundle_id"] == bound.portable.publication_bundle_id
    assert "portable_stage_id" not in public
    assert "snapshot_vector_json" not in public


def test_run_insert_and_post_commit_receipt_are_optional_and_atomic():
    legacy = repository_run_prefix_sql(
        repository_name="example",
        root_path="/public/example",
        git_commit=None,
        run_status="complete",
    )
    assert "source_generation" not in legacy[3]

    expected = receipt()
    fenced = repository_run_prefix_sql(
        repository_name="example",
        root_path="/public/example",
        git_commit=None,
        run_status="complete",
        publication_receipt=expected,
    )
    assert (
        "source_generation, config_generation, extractor_generation, "
        "canonicalizer_generation" in fenced[3]
    )
    assert "publication_job_id, publication_attempt" in fenced[3]
    assert expected.attempt.job_id in fenced[3]
    assert str(expected.attempt.attempt) in fenced[3]
    for value in expected.generations.values():
        assert value in fenced[3]

    summary = file_load_summary_select_sql(
        1, include_publication_receipt=True
    )
    for field in expected.field_names():
        assert f"'{field}'" in summary
        assert f"runs.{field}" in summary


def test_load_summary_accepts_legacy_null_and_requires_exact_full_receipt():
    legacy = load_summary_from_payload(
        {"repository_id": 1, "run_id": 2, "files": 3}
    )
    assert legacy.publication_generations is None

    expected = receipt()
    fenced = load_summary_from_payload(
        {
            "repository_id": 1,
            "run_id": 2,
            "files": 3,
            **expected.to_mapping(),
        }
    )
    assert fenced.publication_receipt == expected

    with pytest.raises(StorageSchemaError, match="malformed load summary"):
        load_summary_from_payload(
            {
                "repository_id": 1,
                "run_id": 2,
                "files": 3,
                "source_generation": "sg1:source",
            }
        )


def test_publication_readback_is_exact_bounded_and_absence_is_none():
    expected = receipt()
    completed = SimpleNamespace(
        stdout=json.dumps({"run_id": 9, **expected.to_mapping()}) + "\n"
    )
    with patch(
        "repomap_kg.storage.publication_readback.run_psql", return_value=completed
    ) as run:
        record = read_run_publication(
            ["-d", "postgres"],
            job_id=expected.attempt.job_id,
            attempt=expected.attempt.attempt,
        )
    assert record is not None
    assert record.receipt == expected
    assert record.marker()["latest_run_identity"] == "run-9"
    assert record.publication_authority_marker()[
        "latest_receipt_bearing_publication_identity"
    ] == "run-9"
    command = run.call_args.args[0]
    assert expected.attempt.job_id in command[-1]
    assert "status = 'complete'" in command[-1]

    with patch(
        "repomap_kg.storage.publication_readback.run_psql",
        return_value=SimpleNamespace(stdout="null\n"),
    ):
        assert (
            read_run_publication(
                ["-d", "postgres"], job_id="job-absent", attempt=1
            )
            is None
        )


def test_latest_publication_readback_uses_only_complete_full_receipts():
    expected = receipt()
    completed = SimpleNamespace(
        stdout=json.dumps({"run_id": 11, **expected.to_mapping()}) + "\n"
    )
    with patch(
        "repomap_kg.storage.publication_readback.run_psql", return_value=completed
    ) as run:
        record = read_latest_publication(["-d", "postgres"])

    assert record is not None
    assert record.receipt == expected
    command = run.call_args.args[0]
    sql = command[-1]
    assert "status = 'complete'" in sql
    assert "publication_job_id IS NOT NULL" in sql
    assert "canonicalizer_generation IS NOT NULL" in sql
    assert "ORDER BY id DESC LIMIT 1" in sql


def test_latest_publication_readback_has_explicit_canonical_name():
    from repomap_kg.storage.publication_readback import (
        read_latest_publication,
        read_latest_receipt_bearing_publication,
    )

    assert read_latest_publication is read_latest_receipt_bearing_publication


def test_latest_publication_readback_reads_legacy_receipt_with_null_portable_columns():
    legacy_payload = {
        "run_id": 15,
        "publication_job_id": "job-legacy-1",
        "publication_attempt": 1,
        "source_generation": "sg1:legacy",
        "config_generation": "cg1:legacy",
        "extractor_generation": "eg1:legacy",
        "canonicalizer_generation": "kg1:legacy",
        "execution_route": None,
        "snapshot_manifest_id": None,
        "snapshot_vector_json": None,
        "extraction_receipt_id": None,
        "publication_bundle_id": None,
        "graph_candidate_id": None,
        "resolver_identity": None,
        "portable_canonicalizer_identity": None,
        "semantic_contract_identity": None,
        "quality_rule_identity": None,
        "portable_protocol_version": None,
        "worker_capability_identity": None,
        "portable_stage_id": None,
        "portable_execution_mode": None,
        "portable_singleton_fencing_epoch": None,
        "portable_graph_lease_fencing_epoch": None,
        "family_receipts_json": None,
    }
    completed = SimpleNamespace(stdout=json.dumps(legacy_payload) + "\n")
    with patch(
        "repomap_kg.storage.publication_readback.run_psql", return_value=completed
    ):
        record = read_latest_publication(["-d", "postgres"])

    assert record is not None
    assert record.run_id == 15
    assert record.receipt.portable is None
    assert record.receipt.attempt.job_id == "job-legacy-1"


def test_publication_run_with_portable_binding_enforces_portable_fields():
    from repomap_kg.storage.staged_publication import publication_run

    class MockConnection:
        def __init__(self, row: tuple[object, ...]) -> None:
            self.row = row
            self.executed_query: str = ""
            self.executed_params: tuple[object, ...] = ()

        def execute(self, query: str, params: tuple[object, ...]) -> "MockConnection":
            self.executed_query = query
            self.executed_params = params
            return self

        def fetchone(self):
            return self.row

    rec = receipt(portable=portable_binding())
    conn = MockConnection((123, "complete"))
    result = publication_run(conn, 1, rec, complete_only=True)
    assert result == (123, "complete")
    assert "execution_route = %s" in conn.executed_query
    assert "snapshot_manifest_id = %s" in conn.executed_query
    assert "portable-worker-v1" in conn.executed_params
