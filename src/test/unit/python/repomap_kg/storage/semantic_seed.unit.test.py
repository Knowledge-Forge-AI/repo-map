"""Stored seed query validation, publication fencing and readback contracts."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.semantic_seed import SimilarNodesQuery
from common_lore_index.storage.semantic_seed_readback import query_seed_candidates, query_similar_nodes
from common_lore_index.storage.semantic_seed_sql import build_seed_query_sql
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, candidate_query

OWNER = "common_lore_index.storage.semantic_seed_readback.execute_json_readback"
PROBE = "common_lore_index.storage.semantic_seed_readback.observe_candidate_capability"


def seed_query(**changes) -> SimilarNodesQuery:
    return replace(SimilarNodesQuery("file:src/a.py", "fixture-rebuild", PROFILE.identity,
        PROFILE.dimensions, selected=True), **changes)


def payload() -> dict:
    publication = candidate_query().publication
    portable = publication.publication.receipt.portable
    assert portable is not None
    snapshot = portable.snapshot_vector[0][2]
    return {"status": "ok", "profile": PROFILE.__dict__,
        "seed": {"canonical_key": "file:src/a.py", "source_binding_id": BINDING, "snapshot_id": snapshot},
        "candidates": [{"canonical_key": "file:src/b.py", "source_binding_id": BINDING,
            "snapshot_id": snapshot, "distance": 0, "evidence": [{"evidence_key": "fixture"}]}]}


@pytest.mark.parametrize("change", [
    {"canonical_key": None}, {"canonical_key": ""}, {"canonical_key": "x\x00y"},
    {"source_binding_id": ""}, {"profile_identity": "other"}, {"profile_identity": None},
    {"rebuild_id": "bad'identity"}, {"dimensions": True}, {"dimensions": 0},
    {"dimensions": 2001}, {"selected": "true"}, {"limit": True}, {"limit": 101},
    {"evidence_limit": 0}, {"evidence_limit": 21}, {"path": "x\x00y"},
])
def test_seed_query_refuses_invalid_contract(change) -> None:
    with pytest.raises(ValueError):
        seed_query(**change).validate()


def test_disabled_seed_is_source_blind_and_performs_no_io() -> None:
    with patch(PROBE, side_effect=AssertionError("unexpected IO")), patch(OWNER, side_effect=AssertionError("unexpected IO")):
        assert query_similar_nodes((), query=seed_query(selected=False), repository_identity="repo1:fixture").reason == "disabled"


def test_seed_sql_selects_seed_and_candidates_in_one_snapshot_with_qualified_exclusion() -> None:
    sql = build_seed_query_sql(candidate_query().publication,
        seed_query(source_binding_id=BINDING, path="src/o'reilly.py", limit=2))
    assert "seed_identities AS MATERIALIZED" in sql and "seed AS MATERIALIZED" in sql
    assert "embedding.embedding OPERATOR(repomap_vector.<=>) seed.embedding" in sql
    assert "<> (seed.canonical_key, seed.source_binding_id)" in sql
    assert "count(*) FROM seed_identities) > 1" in sql
    assert "receipt_identity" in sql and "node.last_seen_run_id = accepted.id" in sql
    assert "evidence.run_id = accepted.id" in sql and "src/o''reilly.py" in sql
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "COPY ", "REFRESH "):
        assert verb not in sql


@pytest.mark.parametrize("reason", ["extension_absent", "observation_failed"])
def test_capability_refusal_does_not_read_seed_or_publication(reason) -> None:
    with patch(PROBE, return_value=reason), patch(OWNER, side_effect=AssertionError("unexpected IO")):
        assert query_similar_nodes((), query=seed_query(), repository_identity="repo1:fixture").reason == reason


@pytest.mark.parametrize("status", ["stale_publication", "stale_rebuild", "foreign_publication", "enrichment_unavailable", "profile_mismatch",
    "seed_node_missing", "seed_embedding_missing", "seed_ambiguous"])
def test_seed_outcomes_are_explicit_bounded_and_empty(status) -> None:
    with patch(OWNER, return_value={"status": status}):
        result = query_seed_candidates((), publication=candidate_query().publication, query=seed_query())
    assert result.reason == status and result.candidates == ()


def test_seed_provenance_keeps_exact_receipt_profile_and_qualified_identity() -> None:
    publication = candidate_query().publication
    record = {"run_id": publication.publication.run_id, **publication.publication.receipt.to_mapping()}
    with patch(PROBE, return_value=None), patch(OWNER, side_effect=[{"publication": record}, payload()]) as read:
        result = query_similar_nodes((), query=seed_query(), repository_identity=publication.repository_identity)
    assert result.status == "ok"
    assert result.provenance is not None
    assert result.provenance["receipt_identity"] == publication.receipt_identity
    assert result.provenance["profile_identity"] == PROFILE.identity
    assert result.provenance["seed"]["source_binding_id"] == BINDING
    assert read.call_count == 2
    assert "repo.repository_identity" in read.call_args_list[0].args[0]
    assert "seed_identities AS MATERIALIZED" in read.call_args_list[1].args[0]


@pytest.mark.parametrize("record", [None, {"run_id": 1}])
def test_missing_or_unreceipted_latest_publication_does_not_fall_back(record) -> None:
    with patch(PROBE, return_value=None), patch(OWNER, return_value={"publication": record}) as read:
        assert query_similar_nodes((), query=seed_query(), repository_identity="repo1:fixture").reason == "publication_unaccepted"
    assert read.call_count == 1


def test_real_seed_query_failures_are_sanitized_errors() -> None:
    with patch(OWNER, side_effect=StorageSchemaError("private SQL detail")):
        with pytest.raises(StorageSchemaError, match="semantic seed query failed") as failure:
            query_seed_candidates((), publication=candidate_query().publication, query=seed_query())
    assert "private SQL detail" not in str(failure.value) and failure.value.__suppress_context__


@pytest.mark.parametrize("change", ["seed", "profile", "self", "evidence", "distance", "snapshot", "binding"])
def test_malformed_or_foreign_backend_result_is_not_success(change) -> None:
    found = payload()
    if change == "seed":
        found["seed"]["canonical_key"] = "foreign"
    elif change == "profile":
        found["profile"] = {**PROFILE.__dict__, "model_version": "foreign"}
    elif change == "self":
        found["candidates"][0]["canonical_key"] = "file:src/a.py"
    elif change == "evidence":
        found["candidates"][0]["evidence"] = []
    elif change == "distance":
        found["candidates"][0]["distance"] = float("nan")
    elif change == "binding":
        found["candidates"][0]["source_binding_id"] = []
    else:
        found["candidates"][0]["snapshot_id"] = "foreign"
    with patch(OWNER, return_value=found), pytest.raises(StorageSchemaError):
        query_seed_candidates((), publication=candidate_query().publication, query=seed_query())
