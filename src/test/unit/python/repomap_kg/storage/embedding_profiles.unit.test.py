"""Identity discovery bounds, receipt fences and source-blind negative paths."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from repomap_kg.storage.semantic_candidates import EmbeddingProfilesQuery
from repomap_kg.storage.semantic_candidate_readback import query_embedding_profiles
from repomap_kg.storage.semantic_candidate_sql import build_embedding_profiles_sql
from repomap_kg.storage.errors import StorageSchemaError
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, SNAPSHOT, candidate_query

OWNER = "repomap_kg.storage.semantic_candidate_readback.execute_json_readback"
PROBE = "repomap_kg.storage.semantic_candidate_readback.observe_candidate_capability"
PUBLICATION = candidate_query().publication
RECORD = {"run_id": PUBLICATION.publication.run_id, **PUBLICATION.publication.receipt.to_mapping()}


def entry(rebuild_id="fixture-a", **changes):
    return {"rebuild_id": rebuild_id, "profile_identity": PROFILE.identity,
            **PROFILE.__dict__, "row_count": 5,
            "source_scope": [{"source_binding_id": BINDING, "snapshot_id": SNAPSHOT}], **changes}


def read(payload, **changes):
    if isinstance(payload, dict):
        payload = {"has_excluded_rebuilds": False, **payload}
    with patch(PROBE, return_value=None), patch(OWNER, side_effect=[{"publication": RECORD}, payload]):
        return query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True, **changes),
                                        repository_identity=PUBLICATION.repository_identity)


@pytest.mark.parametrize("changes", [{"selected": "true"}, {"selected": 1}, {"selected": None},
                                    {"limit": True}, {"limit": 0}, {"limit": 101}, {"limit": 2.5}])
def test_query_validation_precedes_io(changes):
    with patch(OWNER, side_effect=AssertionError("IO")), patch(PROBE, side_effect=AssertionError("IO")):
        with pytest.raises(ValueError):
            query_embedding_profiles((), query=EmbeddingProfilesQuery(**changes),
                                     repository_identity=PUBLICATION.repository_identity)


def test_disabled_query_performs_no_capability_publication_or_store_io():
    with patch(OWNER, side_effect=AssertionError("IO")), patch(PROBE, side_effect=AssertionError("IO")):
        result = query_embedding_profiles((), query=EmbeddingProfilesQuery(), repository_identity="unused")
    assert result.reason == "disabled" and not result.profiles and result.provenance is None


@pytest.mark.parametrize("identity", [None, "", "repo1:bad'identity", "x\x00y"])
def test_repository_identity_validation_precedes_observation(identity):
    with patch(PROBE, side_effect=AssertionError("IO")), pytest.raises(ValueError):
        query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True), repository_identity=identity)


@pytest.mark.parametrize("facts,reason", [
    ({"installed_version": None}, "extension_absent"),
    ({"installed_version": "0.8.6", "installation_schema": "repomap_vector"}, "extension_unsupported"),
    ({"installed_version": "0.8.7", "installation_schema": "public"}, "extension_unsupported"),
    ({"installed_version": "0.8.7", "installation_schema": "repomap_vector", "objects_present": False},
     "enrichment_schema_absent_or_unsupported"),
    ({"installed_version": "0.8.7", "installation_schema": "repomap_vector", "objects_present": True,
      "schema_version": "unexpected"}, "enrichment_schema_absent_or_unsupported"),
])
def test_optional_observation_is_separate_and_stops_before_metadata(facts, reason):
    with patch(OWNER, return_value=facts) as io:
        result = query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True),
                                         repository_identity=PUBLICATION.repository_identity)
    assert result.reason == reason and not result.profiles and io.call_count == 1


def test_probe_failure_is_unavailable_but_post_probe_query_failure_is_error():
    with patch(OWNER, side_effect=StorageSchemaError("private probe detail")) as io:
        assert query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True),
               repository_identity=PUBLICATION.repository_identity).reason == "observation_failed"
        assert io.call_count == 1
    with patch(PROBE, return_value=None), patch(OWNER, side_effect=StorageSchemaError("private SQL detail")):
        with pytest.raises(StorageSchemaError, match="embedding profile query failed") as failure:
            query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True),
                                     repository_identity=PUBLICATION.repository_identity)
    assert "private SQL detail" not in str(failure.value) and failure.value.__suppress_context__


@pytest.mark.parametrize("record", [None, {}, {"run_id": True}, {"run_id": 1},
                                    {**RECORD, "snapshot_vector_json": "malformed"},
                                    {**RECORD, "publication_attempt": True}])
def test_unaccepted_latest_receipt_never_falls_back(record):
    with patch(PROBE, return_value=None), patch(OWNER, return_value={"publication": record}) as io:
        result = query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True),
                                         repository_identity=PUBLICATION.repository_identity)
    assert result.reason == "publication_unaccepted" and io.call_count == 1


@pytest.mark.parametrize("reason", ["stale_publication", "stale_rebuild", "no_import", "invalid_rebuild",
                                  "extension_unsupported", "enrichment_schema_absent_or_unsupported"])
def test_refusals_do_not_adopt_any_rows(reason):
    result = read({"status": reason, "profiles": [entry()]})
    assert result.reason == reason and not result.profiles and result.provenance is None


def test_distinct_rebuilds_are_ordered_bounded_with_no_preference():
    result = read({"status": "ok", "profiles": [entry("z"), entry("a"), entry("b")]}, limit=2)
    assert result.status == "ok" and [item["rebuild_id"] for item in result.profiles] == ["a", "b"]
    assert result.has_more and "best" not in result.to_jsonable()
    assert result.provenance["receipt_identity"] == PUBLICATION.receipt_identity
    assert result.provenance["publication"]["publication_bundle_id"].startswith("bundle1:")
    assert result.provenance["generations"]["source_generation"] == "sg1:fixture"


def test_projection_discards_raw_vectors_and_principals():
    result = read({"status": "ok", "profiles": [entry(embedding=[1, 0, 0], enrichment_principal="secret-role",
                                                       raw_source="private source")]})
    assert result.status == "ok" and not result.has_more
    assert not {"embedding", "enrichment_principal", "raw_source"} & result.profiles[0].keys()
    assert result.profiles[0]["profile_identity"] == PROFILE.identity


def test_partial_sql_exclusions_are_visible_without_adopting_excluded_rows():
    result = read({"status": "ok", "profiles": [entry()], "has_excluded_rebuilds": True})
    assert result.status == "ok" and result.to_jsonable()["has_excluded_rebuilds"] is True
    assert len(result.profiles) == 1 and not result.has_more


@pytest.mark.parametrize("excluded", [None, "false", 0, [], {}])
def test_malformed_exclusion_observation_is_not_accepted(excluded):
    with pytest.raises(StorageSchemaError, match="malformed embedding profile readback"):
        read({"status": "ok", "profiles": [entry()], "has_excluded_rebuilds": excluded})


def test_invalid_identity_on_the_extra_page_row_refuses_instead_of_returning_a_tuple():
    result = read({"status": "ok", "profiles": [entry("a"), entry("b", model_version="corrupt")]}, limit=1)
    assert result.reason == "invalid_identity" and not result.profiles


def test_missing_exclusion_observation_is_not_assumed_false():
    with patch(PROBE, return_value=None), patch(OWNER, side_effect=[
        {"publication": RECORD}, {"status": "ok", "profiles": [entry()]},
    ]), pytest.raises(StorageSchemaError, match="malformed embedding profile readback"):
        query_embedding_profiles((), query=EmbeddingProfilesQuery(selected=True),
                                 repository_identity=PUBLICATION.repository_identity)


@pytest.mark.parametrize("changes", [
    {"rebuild_id": "bad'identity"}, {"profile_identity": "sha256:" + "f" * 64},
    {"model_version": "different"}, {"dimensions": True}, {"dimensions": 0}, {"dimensions": 2001},
    {"representation_version": "source-v1"}, {"metric": "euclidean"}, {"normalization": "none"},
    {"row_count": True}, {"row_count": 0}, {"row_count": 501}, {"source_scope": []},
    {"source_scope": [{"source_binding_id": "foreign", "snapshot_id": SNAPSHOT}]},
    {"source_scope": [{"source_binding_id": BINDING, "snapshot_id": "foreign"}]},
    {"source_scope": [{"source_binding_id": [], "snapshot_id": SNAPSHOT}]},
    {"source_scope": [{"source_binding_id": BINDING, "snapshot_id": SNAPSHOT}] * 2},
])
def test_invalid_metadata_never_yields_an_eligible_tuple(changes):
    result = read({"status": "ok", "profiles": [entry(**changes)]})
    assert result.reason == "invalid_identity" and not result.profiles


def test_duplicate_rebuild_and_missing_profile_field_refuse():
    assert read({"status": "ok", "profiles": [entry(), entry()]}).reason == "ambiguous_identity"
    row = deepcopy(entry())
    del row["model"]
    assert read({"status": "ok", "profiles": [row]}).reason == "invalid_identity"


@pytest.mark.parametrize("payload", [[], {"status": []}, {"status": "ok", "profiles": []},
                                     {"status": "ok", "profiles": [entry()] * 22}])
def test_malformed_backend_shape_is_a_query_error(payload):
    with pytest.raises(StorageSchemaError, match="malformed embedding profile readback"):
        read(payload)


def test_sql_binds_full_receipt_and_every_imported_source_without_vector_projection():
    sql = build_embedding_profiles_sql(PUBLICATION, EmbeddingProfilesQuery(selected=True, limit=2))
    assert "ORDER BY runs.id DESC LIMIT 1" in sql and "LIMIT 3" in sql
    for field in PUBLICATION.publication.receipt.field_names():
        assert field in sql
    for guard in ("receipt_identity", "rebuild.row_count", "evidence.run_id = accepted.id",
                  "node.last_seen_run_id = accepted.id", "snapshots.snapshot_id = e.snapshot_id",
                  "rebuild.repository_identity", "COLLATE \"C\"", "0.8.7", "has_excluded_rebuilds"):
        assert guard in sql
    for forbidden in ("embedding.embedding", "e.embedding", "enrichment_principal", "raw_payload",
                      "INSERT ", "UPDATE ", "DELETE ", "CREATE ", "COPY ", "REFRESH "):
        assert forbidden not in sql
