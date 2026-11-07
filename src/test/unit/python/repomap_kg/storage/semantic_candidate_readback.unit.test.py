"""Capability refusal and read-only query-owner dispatch without a live DB."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.semantic_candidate_readback import query_semantic_candidates
from repomap_test_support.semantic_candidate_fixtures import candidate_query

FACTS = {"installed_version": "0.8.7", "installation_schema": "repomap_vector",
         "schema_version": "repomap-enrichment-schema:1", "objects_present": True}
OWNER = "common_lore_index.storage.semantic_candidate_readback.execute_json_readback"


def test_disabled_query_performs_no_database_io() -> None:
    with patch(OWNER, side_effect=AssertionError("unexpected IO")):
        result = query_semantic_candidates((), query=replace(candidate_query(), selected=False))
    assert result.status == "capability_unavailable" and result.reason == "disabled"


def test_graph_mismatch_refuses_before_database_io() -> None:
    with patch(OWNER, side_effect=AssertionError("unexpected IO")):
        result = query_semantic_candidates((), query=candidate_query(), repository_identity="repo1:foreign")
    assert result.reason == "graph_scope_mismatch"


@pytest.mark.parametrize("facts, reason", [
    ({**FACTS, "installed_version": None}, "extension_absent"),
    ({**FACTS, "installed_version": "0.8.2"}, "extension_unsupported"),
    ({**FACTS, "installation_schema": "public"}, "extension_unsupported"),
    ({**FACTS, "schema_version": None}, "enrichment_schema_absent_or_unsupported"),
    ({**FACTS, "objects_present": False}, "enrichment_schema_absent_or_unsupported"),
])
def test_optional_capability_unavailable_never_substitutes_text_search(facts, reason) -> None:
    with patch(OWNER, return_value=facts) as read:
        result = query_semantic_candidates((), query=candidate_query())
    assert result.reason == reason and result.candidates == ()
    assert read.call_count == 1


def test_failed_observation_returns_bounded_unavailability() -> None:
    with patch(OWNER, side_effect=StorageSchemaError("private connection detail")):
        result = query_semantic_candidates((), query=candidate_query())
    assert result.reason == "observation_failed"
    assert "private connection detail" not in str(result.to_jsonable())


def test_query_failure_after_successful_probe_is_a_storage_error() -> None:
    with patch(OWNER, side_effect=[FACTS, StorageSchemaError("private query detail")]):
        with pytest.raises(StorageSchemaError, match="semantic candidate query failed") as failure:
            query_semantic_candidates((), query=candidate_query())
    assert "private query detail" not in str(failure.value)
    assert failure.value.__cause__ is None and failure.value.__suppress_context__


@pytest.mark.parametrize("status", ["stale_publication", "enrichment_unavailable"])
def test_stale_publication_and_absent_matching_rebuild_are_unavailable(status) -> None:
    with patch(OWNER, side_effect=[FACTS, {"status": status, "candidates": []}]):
        result = query_semantic_candidates((), query=candidate_query())
    assert result.reason == status and result.candidates == ()


def test_success_returns_provenance_and_explicit_limitations() -> None:
    query = candidate_query()
    with patch(OWNER, side_effect=[FACTS, {"status": "ok", "candidates": []}]) as read:
        result = query_semantic_candidates((), query=query)
    assert result.status == "ok" and result.reason is None
    assert result.provenance is not None
    assert result.provenance["receipt_identity"] == query.publication.receipt_identity
    assert result.provenance["profile_identity"] == query.profile.identity
    assert result.provenance["search"] == "exact"
    assert result.provenance["input_digest_validation"] == "enrichment_principal_assertion"
    assert "at most 500 imported node/source records in one rebuild per query" in result.to_jsonable()["limitations"]
    assert read.call_count == 2


@pytest.mark.parametrize("payload", [{"status": "other"}, {"status": "ok", "candidates": [None]}])
def test_malformed_candidate_readback_is_not_success(payload) -> None:
    with patch(OWNER, side_effect=[FACTS, payload]), pytest.raises(StorageSchemaError):
        query_semantic_candidates((), query=candidate_query())
