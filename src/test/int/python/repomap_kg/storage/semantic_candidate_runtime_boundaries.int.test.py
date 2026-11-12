"""Real pgvector product boundaries for the unchanged optional candidate schema, import and readers.

Every case runs the maintained product SQL against a disposable PostgreSQL with
the admitted extension available. No product guard, driver or parser is mocked
or changed; synthetic axis vectors prove boundaries, never semantic quality.
"""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from common_lore_index.storage import apply_migrations, default_rdbms_root, query_canonical_node_records
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.publication_readback import read_latest_publication
from common_lore_index.storage.semantic_candidate_import import build_embedding_import_sql, candidate_schema_sql
from common_lore_index.storage.semantic_candidate_readback import query_embedding_profiles, query_semantic_candidates
from common_lore_index.storage.semantic_candidates import CandidatePublication, EmbeddingEntry, EmbeddingProfilesQuery
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.staged_ingestion import run_staged_portable_refresh
from repomap_test_support.portable_publication_fixtures import _authority, _binding
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, SNAPSHOT, candidate_query
from repomap_test_support.semantic_candidate_publication import candidate_bundle
from repomap_test_support.semantic_candidate_restore import optional_sql_fixture_cleanup

REPOSITORY = "repo1:candidate-fixture"
ROOT = "graph:candidate-fixture"
READER = "candidate_boundary_reader"
WRITER = "candidate_boundary_enrichment"


def _execute(postgres, sql: str, *, role: str | None = None) -> None:
    text = (f'SET ROLE "{role}";\n' if role else "") + sql
    run_psql([postgres.psql_command, *postgres.psql_args, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=text)


def _publish(postgres, *, revision: int) -> CandidatePublication:
    bundle = candidate_bundle(job_id=f"candidate-boundary-{revision}", revision=revision)
    authority = replace(_authority(bundle), singleton_fencing_epoch=7 + revision, graph_lease_fencing_epoch=9 + revision)
    run_staged_portable_refresh(
        postgres.psql_args, bundle, repository_name="candidate-fixture", root_path=ROOT,
        repository_identity=REPOSITORY, authority=authority, portable_binding=_binding(bundle, authority))
    record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    assert record is not None
    return CandidatePublication(REPOSITORY, record)


def _as_reader(postgres, monkeypatch: pytest.MonkeyPatch, call, **kwargs):
    with monkeypatch.context() as env:
        env.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psql")
        env.setenv("PGOPTIONS", f"-c role={READER} -c default_transaction_read_only=on")
        return call(postgres.psql_args, psql_command=postgres.psql_command, **kwargs)


def _entries(*names: str) -> tuple[EmbeddingEntry, ...]:
    axes = {"a": (1.0, 0.0, 0.0), "b": (0.0, 1.0, 0.0), "c": (0.0, 0.0, 1.0)}
    return tuple(EmbeddingEntry(f"file:src/{name}.py", BINDING, axes.get(name, (1.0, 0.0, 0.0)),
                                "sha256:" + "a" * 64) for name in names)


def _rebuild_count(postgres) -> str:
    return postgres.psql_scalar("SELECT count(*) FROM repomap_enrichment.rebuilds")


def _nodes(postgres):
    return query_canonical_node_records(postgres.psql_args, root_path=ROOT, repository_identity=REPOSITORY,
                                        psql_command=postgres.psql_command)


def _start(postgres) -> None:
    require_postgres_binaries()
    available = postgres.psql_scalar(
        "SELECT count(*) FROM pg_available_extension_versions WHERE name = 'vector' AND version = '0.8.7'")
    apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
    assert available == "1", "runtime boundary owner requires the admitted pgvector 0.8.7 profile"
    _execute(postgres, f"CREATE ROLE {READER} NOLOGIN; CREATE ROLE {WRITER} NOLOGIN;")


@pytest.mark.requires_pgvector
def test_no_vector_schema_guard_then_extension_without_enrichment_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    with temporary_postgres() as postgres:
        _start(postgres)
        with optional_sql_fixture_cleanup(postgres, reader=READER, writer=WRITER, execute_fn=_execute,
                                          canonical_nodes_fn=lambda: _nodes(postgres), expected_canonical_count=3):
            publication = _publish(postgres, revision=1)
            with pytest.raises(StorageSchemaError):
                _execute(postgres, candidate_schema_sql(read_principal=READER, enrichment_principal=WRITER))
            assert postgres.psql_scalar(
                "SELECT count(*) FROM pg_namespace WHERE nspname = 'repomap_enrichment'") == "0"
            _execute(postgres, "CREATE SCHEMA repomap_vector; "
                     "CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';")
            query = replace(candidate_query(), publication=publication, source_binding_id=BINDING)
            found = _as_reader(postgres, monkeypatch, query_semantic_candidates, query=query)
            assert (found.status, found.reason, found.candidates) == (
                "capability_unavailable", "enrichment_schema_absent_or_unsupported", ())
            profiles = _as_reader(postgres, monkeypatch, query_embedding_profiles,
                                  query=EmbeddingProfilesQuery(selected=True), repository_identity=REPOSITORY)
            assert (profiles.status, profiles.reason, profiles.profiles) == (
                "capability_unavailable", "enrichment_schema_absent_or_unsupported", ())


@pytest.mark.requires_pgvector
def test_publication_principal_rollback_and_malformed_latest_receipt_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_postgres() as postgres:
        _start(postgres)
        _execute(postgres, "CREATE SCHEMA repomap_vector; "
                 "CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';")
        with optional_sql_fixture_cleanup(postgres, reader=READER, writer=WRITER, execute_fn=_execute,
                                          canonical_nodes_fn=lambda: _nodes(postgres), expected_canonical_count=3):
            _execute(postgres, candidate_schema_sql(read_principal=READER, enrichment_principal=WRITER))
            absent = _as_reader(postgres, monkeypatch, query_embedding_profiles,
                                query=EmbeddingProfilesQuery(selected=True), repository_identity=REPOSITORY)
            assert (absent.status, absent.reason) == ("capability_unavailable", "publication_unaccepted")
            publication = _publish(postgres, revision=1)
            sql = build_embedding_import_sql(publication, PROFILE, _entries("a", "b"), rebuild_id="boundary-1",
                                             enrichment_principal=WRITER, public_safe=True)
            with pytest.raises(StorageSchemaError):
                _execute(postgres, sql, role=READER)
            assert _rebuild_count(postgres) == "0"
            spoofed = build_embedding_import_sql(publication, PROFILE, _entries("a", "b"), rebuild_id="boundary-1",
                                                 enrichment_principal=READER, public_safe=True)
            with pytest.raises(StorageSchemaError):
                _execute(postgres, spoofed, role=WRITER)
            assert _rebuild_count(postgres) == "0"
            unknown = build_embedding_import_sql(publication, PROFILE, _entries("a", "zz-unknown"),
                                                 rebuild_id="boundary-2", enrichment_principal=WRITER, public_safe=True)
            with pytest.raises(StorageSchemaError):
                _execute(postgres, unknown, role=WRITER)
            assert _rebuild_count(postgres) == "0"
            assert postgres.psql_scalar("SELECT count(*) FROM repomap_enrichment.embeddings") == "0"
            _execute(postgres, sql, role=WRITER)
            assert _rebuild_count(postgres) == "1"
            ok = _as_reader(postgres, monkeypatch, query_embedding_profiles,
                            query=EmbeddingProfilesQuery(selected=True), repository_identity=REPOSITORY)
            assert ok.status == "ok" and [p["rebuild_id"] for p in ok.profiles] == ["boundary-1"]
            foreign = replace(candidate_query(), publication=replace(publication, repository_identity="repo1:foreign"))
            assert _as_reader(postgres, monkeypatch, query_semantic_candidates, query=foreign).reason == \
                "stale_publication"

            successor = _publish(postgres, revision=2)
            run_id = successor.publication.run_id
            original = postgres.psql_scalar(f"SELECT snapshot_vector_json FROM public.runs WHERE id = {run_id}")
            for malformed in (
                [[BINDING, 2, SNAPSHOT], [BINDING, 2, SNAPSHOT]],
                [["not-a-binding", 2, SNAPSHOT]],
            ):
                _execute(postgres, "UPDATE public.runs SET snapshot_vector_json = "
                         f"'{json.dumps(malformed, separators=(',', ':'))}' WHERE id = {run_id};")
                latest = _as_reader(postgres, monkeypatch, query_embedding_profiles,
                                    query=EmbeddingProfilesQuery(selected=True), repository_identity=REPOSITORY)
                assert (latest.status, latest.reason, latest.profiles) == (
                    "capability_unavailable", "publication_unaccepted", ())
                historical = replace(candidate_query(), publication=publication, rebuild_id="boundary-1")
                stale = _as_reader(postgres, monkeypatch, query_semantic_candidates, query=historical)
                assert (stale.reason, stale.candidates) == ("stale_publication", ())
            assert int(postgres.psql_scalar("SELECT max(id) FROM public.runs WHERE status = 'complete'")) == run_id
            _execute(postgres, f"UPDATE public.runs SET snapshot_vector_json = {sql_literal(original)} WHERE id = {run_id};")
            restored = _as_reader(postgres, monkeypatch, query_embedding_profiles,
                                  query=EmbeddingProfilesQuery(selected=True), repository_identity=REPOSITORY)
            assert (restored.status, restored.reason) == ("capability_unavailable", "stale_rebuild")
            _execute(postgres, "DELETE FROM repomap_enrichment.embeddings; DELETE FROM repomap_enrichment.rebuilds;")
