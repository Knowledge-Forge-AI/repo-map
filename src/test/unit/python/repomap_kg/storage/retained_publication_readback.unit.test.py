"""Exact read-only query binding and strict retained-publication response types."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from typing import cast
from unittest.mock import patch

import pytest

from common_lore_index.storage import retained_publication_readback as readback
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage.errors import StorageSchemaError
from repomap_test_support.portable_publication_fixtures import authority, binding, seven_family_bundle


def _publication():
    bundle = seven_family_bundle()
    owner = authority(bundle)
    portable = binding(bundle, owner)
    receipt = replace(owner.receipt(), portable=portable)
    return receipt, {"run_id": 41, **receipt.to_mapping()}


def _read(payload):
    receipt, _row = _publication()
    with patch.object(readback, "execute_ops_json_readback", return_value=payload) as execute:
        result = readback.read_retained_publication(
            cast(OpsConfig, object()), database="test-database", repository_identity="repo1:portable-fixture",
            job_id=receipt.attempt.job_id, attempt=receipt.attempt.attempt,
            portable_stage_id=receipt.portable.stage_id, psql_command="test-psql",
        )
    return result, execute.call_args


def test_completed_record_query_binds_repository_stage_job_and_all_receipt_fields():
    expected, row = _publication()
    result, call = _read({"publication": row})
    assert result is not None and result.receipt == expected and result.run_id == 41
    sql = call.kwargs["sql"]
    assert "repo.id = run.repository_id" in sql
    assert "repo.repository_identity = 'repo1:portable-fixture'" in sql
    assert f"run.portable_stage_id = '{expected.portable.stage_id}'" in sql
    assert f"run.publication_job_id = '{expected.attempt.job_id}'" in sql
    assert "run.status = 'complete'" in sql
    assert "ORDER BY run.id DESC LIMIT 1" in sql
    assert call.kwargs["mode"] == "host_then_container"
    assert call.kwargs["psql_command"] == "test-psql"


@pytest.mark.parametrize("case", [
    "extra-envelope", "missing-envelope", "bad-run-id", "boolean-attempt", "boolean-fence",
    "boolean-revision", "boolean-family-count", "duplicate-family-key", "extra-receipt-key", "wrong-job",
])
def test_malformed_or_coerced_proof_cannot_become_an_exact_completed_record(case):
    _expected, row = _publication()
    payload = {"publication": deepcopy(row)}
    if case == "extra-envelope":
        payload["extra"] = "untrusted"
    elif case == "missing-envelope":
        payload = {}
    elif case == "bad-run-id":
        payload["publication"]["run_id"] = True
    elif case == "boolean-attempt":
        payload["publication"]["publication_attempt"] = True
    elif case == "boolean-fence":
        payload["publication"]["portable_graph_lease_fencing_epoch"] = True
    elif case == "boolean-revision":
        vector = json.loads(row["snapshot_vector_json"])
        vector[0][1] = True
        payload["publication"]["snapshot_vector_json"] = json.dumps(vector)
    elif case == "boolean-family-count":
        families = json.loads(row["family_receipts_json"])
        families["files"]["count"] = True
        payload["publication"]["family_receipts_json"] = json.dumps(families)
    elif case == "duplicate-family-key":
        payload["publication"]["family_receipts_json"] = '{"files":{},"files":{}}'
    elif case == "extra-receipt-key":
        payload["publication"]["unknown"] = "untrusted"
    elif case == "wrong-job":
        payload["publication"]["publication_job_id"] = "other-job"
    with pytest.raises(StorageSchemaError, match="malformed"):
        _read(payload)


def test_absent_publication_remains_absent_without_a_failure_inference():
    result, _call = _read({"publication": None})
    assert result is None
