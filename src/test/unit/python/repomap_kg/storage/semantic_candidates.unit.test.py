"""Embedding import/representation and exact query boundary contracts."""

from dataclasses import replace
import math
from typing import Any

import pytest

from repomap_kg.storage.semantic_candidates import EmbeddingEntry, checked_vector
from repomap_kg.storage.semantic_candidate_import import build_embedding_import_sql, candidate_schema_sql
from repomap_kg.storage.semantic_candidate_sql import build_candidate_query_sql
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, candidate_query
from repomap_test_support.semantic_candidate_publication import candidate_bundle


@pytest.mark.parametrize("vector", [
    (), (1, 0), (0, 0, 0), (2, 0, 0), (True, 0, 0),
    (float("nan"), 0, 0), (float("inf"), 0, 0), (1e308, 0, 0), ("1", 0, 0),
])
def test_invalid_vector_is_refused_before_database_io(vector) -> None:
    with pytest.raises(ValueError):
        checked_vector(vector, 3)


def test_unit_vector_validation_is_not_implicit_normalization() -> None:
    vector = (1 / math.sqrt(2), 1 / math.sqrt(2), 0)
    assert checked_vector(vector, 3) == vector


@pytest.mark.parametrize("change", [
    {"dimensions": 0}, {"dimensions": 2001}, {"dimensions": True},
    {"model": "bad\nidentity"}, {"metric": "l2"}, {"normalization": "none"},
    {"representation_version": "unversioned"},
])
def test_unsupported_embedding_profile_refuses(change) -> None:
    with pytest.raises(ValueError):
        replace(PROFILE, **change).validate()


def test_profile_identity_binds_model_generator_version_and_dimensions() -> None:
    for name, value in (("model", "other"), ("model_version", "2"),
                        ("generator", "other"), ("generator_version", "2"), ("dimensions", 4)):
        change: dict[str, Any] = {name: value}
        assert replace(PROFILE, **change).identity != PROFILE.identity


@pytest.mark.parametrize("change", [
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"evidence_limit": 0},
    {"evidence_limit": 21}, {"selected": "true"}, {"path": "x\x00y"},
    {"rebuild_id": "invalid'identity"},
])
def test_query_bounds_and_filters_are_validated(change) -> None:
    with pytest.raises(ValueError):
        replace(candidate_query(), **change).validate()


def test_legacy_receipt_cannot_supply_enrichment_authority() -> None:
    query = candidate_query()
    publication = replace(query.publication.publication, receipt=replace(query.publication.publication.receipt, portable=None))
    with pytest.raises(ValueError, match="portable"):
        replace(query.publication, publication=publication).validate()


def test_exact_query_is_source_blind_and_quotes_filter_literals() -> None:
    query = replace(candidate_query(), path="src/o'reilly.py", kind="file' OR true --", limit=2)
    sql = build_candidate_query_sql(query)
    assert "src/o''reilly.py" in sql and "file'' OR true --" in sql
    assert "distances AS MATERIALIZED" in sql
    assert 'ORDER BY distance, canonical_key COLLATE "C"' in sql
    assert "evidence.run_id = accepted.id" in sql and "snapshot_id" in sql
    assert "publication_bundle_id" in sql and "status = 'complete'" in sql
    assert "node.last_seen_run_id = accepted.id" in sql
    for forbidden in ("CREATE ", "INSERT ", "UPDATE ", "DELETE ", "REFRESH ", "COPY "):
        assert forbidden not in sql


def _entry(**changes) -> EmbeddingEntry:
    return replace(EmbeddingEntry("file:src/a.py", BINDING, (1, 0, 0), "sha256:" + "a" * 64), **changes)


def _import(entries, **changes) -> str:
    query = candidate_query()
    arguments: dict[str, Any] = dict(rebuild_id=query.rebuild_id, enrichment_principal="fixture_enrichment", public_safe=True)
    arguments.update(changes)
    return build_embedding_import_sql(query.publication, query.profile, entries, **arguments)


@pytest.mark.parametrize("entries, changes", [
    ((), {}), ((_entry(),) * 501, {}), ((_entry(), _entry()), {}),
    ((_entry(source_binding_id="bind1:foreign"),), {}),
    ((_entry(input_digest="invalid"),), {}), ((_entry(vector=(1, 0)),), {}),
    ((_entry(),), {"public_safe": False}), ((_entry(),), {"public_safe": "true"}),
    ((_entry(),), {"enrichment_principal": "bad;role"}),
])
def test_import_refuses_invalid_or_unauthorized_batch(entries, changes) -> None:
    with pytest.raises(ValueError):
        _import(entries, **changes)


def test_import_is_separate_immutable_publication_bound_authority() -> None:
    sql = _import((_entry(),))
    assert "current_user <> 'fixture_enrichment'" in sql
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ" in sql
    assert "ON CONFLICT" not in sql
    assert "embedding batch contains a node without accepted source evidence" in sql
    assert "snapshot_id" in sql and "publication_bundle_id" in sql
    assert "UPDATE public." not in sql and "CREATE EXTENSION" not in sql


def test_optional_schema_requires_existing_lifecycle_owned_extension() -> None:
    sql = candidate_schema_sql(read_principal="fixture_reader", enrichment_principal="fixture_enrichment")
    assert "CREATE EXTENSION" not in sql
    assert "ext.extversion = '0.8.7'" in sql
    assert "pg_get_userbyid(ext.extowner) = current_user" in sql
    assert "REVOKE EXECUTE ON ALL FUNCTIONS" in sql
    assert "enrichment_principal TEXT NOT NULL DEFAULT current_user" in sql
    assert "CHECK (enrichment_principal = current_user)" not in sql
    assert "GRANT SELECT ON ALL TABLES" in sql
    grant = sql.split("GRANT INSERT (")[1].split(") ON repomap_enrichment.rebuilds")[0]
    assert "enrichment_principal" not in grant
    assert "GRANT INSERT ON repomap_enrichment.embeddings" in sql
    assert "canonical_nodes ADD" not in sql and "CASCADE" not in sql
    with pytest.raises(ValueError):
        candidate_schema_sql(read_principal="same", enrichment_principal="same")


def test_import_uses_database_recorded_principal_instead_of_supplied_provenance() -> None:
    sql = _import((_entry(),))
    columns = sql.split("INSERT INTO repomap_enrichment.rebuilds (")[1].split(") VALUES")[0]
    assert "enrichment_principal" not in columns
    assert "current_user <> 'fixture_enrichment'" in sql


def test_public_fixture_contains_three_nodes_and_bound_evidence_in_seven_families() -> None:
    bundle = candidate_bundle()
    assert len(bundle.families) == 7
    assert {row["canonical_key"] for row in bundle.families["canonical_nodes"]} == {
        "file:src/a.py", "file:src/b.py", "file:src/c.py",
    }
    assert len(bundle.families["canonical_node_evidence"]) == 3
    for row in bundle.families["canonical_evidence"]:
        metadata = row["metadata_json"]
        assert isinstance(metadata, dict)
        assert metadata["binding_id"] == BINDING
