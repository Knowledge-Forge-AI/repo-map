"""Canonical disposable PostgreSQL boundary; extension admission is explicit.

The absence owner exercises core-only behavior. The exact owner requires the
selected extension and fails its presence gate if unavailable. No artifacts are
downloaded, and an absence pass never counts as exact retrieval evidence.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root, query_canonical_node_records
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.authority import GraphRunId
from repomap_kg.storage.psql import run_psql
from repomap_kg.storage.publication_readback import read_latest_publication
from repomap_kg.storage.semantic_candidates import CandidatePublication, CandidateQuery, EmbeddingEntry
from repomap_kg.storage.semantic_candidate_import import build_embedding_import_sql, candidate_schema_sql
from repomap_kg.storage.semantic_candidate_readback import query_semantic_candidates
from repomap_kg.storage.staged_ingestion import run_staged_portable_refresh
from repomap_test_support.portable_publication_fixtures import _authority, _binding
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.semantic_candidate_fixtures import BINDING, PROFILE, candidate_query
from repomap_test_support.semantic_candidate_publication import candidate_bundle
from repomap_test_support.semantic_candidate_restore import (
    execute_candidate_dump_restore,
    record_optional_schema_state,
    teardown_optional_schema_without_cascade,
    verify_reader_privilege_refusals,
    verify_restored_acl_and_principal,
    verify_writer_privilege_refusals,
)

REPOSITORY = "repo1:candidate-fixture"
ROOT = "graph:candidate-fixture"
READER = "candidate_fixture_reader"
WRITER = "candidate_fixture_enrichment"


def _publish(postgres, *, revision: int = 1) -> CandidatePublication:
    bundle = candidate_bundle(job_id=f"candidate-publication-{revision}", revision=revision)
    authority = replace(_authority(bundle), singleton_fencing_epoch=7 + revision,
                        graph_lease_fencing_epoch=9 + revision)
    run_staged_portable_refresh(
        postgres.psql_args, bundle, repository_name="candidate-fixture", root_path=ROOT,
        repository_identity=REPOSITORY, authority=authority, portable_binding=_binding(bundle, authority),
    )
    record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    assert record is not None
    return CandidatePublication(REPOSITORY, record)


def _execute(postgres, sql: str, *, role: str | None = None) -> None:
    text = (f'SET ROLE "{role}";\n' if role else "") + sql
    run_psql([postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=text)


def _read(postgres, query: CandidateQuery):
    # Enforce the SQL transaction and role boundary, not merely a Python promise.
    args = ("-c", f"role={READER}", "-c", "default_transaction_read_only=on")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psql")
        env.setenv("PGOPTIONS", " ".join(args))
        return query_semantic_candidates(postgres.psql_args, query=query, psql_command=postgres.psql_command)


def _entries() -> tuple[EmbeddingEntry, ...]:
    return tuple(EmbeddingEntry(f"file:src/{name}.py", BINDING, vector, "sha256:" + "a" * 64)
        for name, vector in (("a", (1, 0, 0)), ("b", (1, 0, 0)), ("c", (0, 1, 0))))


def _check_principal_restore_boundary(postgres) -> None:
    assert postgres.psql_scalar("SELECT enrichment_principal FROM repomap_enrichment.rebuilds") == WRITER
    saved = run_psql([postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text="COPY repomap_enrichment.rebuilds TO STDOUT;").stdout.rstrip("\n")
    # A complete otherwise-valid row avoids a refusal caused by missing fields.
    spoofed = saved.split("\t")
    spoofed[0], spoofed[-2] = "spoofed-rebuild", "spoofed"
    with pytest.raises(StorageSchemaError):
        _execute(postgres, "COPY repomap_enrichment.rebuilds FROM STDIN;\n"
            + "\t".join(spoofed) + "\n\\.\n", role=WRITER)
    # COPY the saved row under the lifecycle role, preserving the original writer.
    # This proves the session-independent row boundary, not D9 whole-dump restore.
    assert postgres.psql_scalar("SELECT current_user") != WRITER
    _execute(postgres, "BEGIN; DELETE FROM repomap_enrichment.embeddings; "
        "DELETE FROM repomap_enrichment.rebuilds; "
        "COPY repomap_enrichment.rebuilds FROM STDIN;\n" + saved + "\n\\.\n"
        "ROLLBACK;")
    assert postgres.psql_scalar("SELECT enrichment_principal FROM repomap_enrichment.rebuilds") == WRITER


def test_absent_extension_preserves_ordinary_publication_and_reads() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        publication = _publish(postgres)
        query = replace(candidate_query(), publication=publication)
        before = query_canonical_node_records(postgres.psql_args, root_path=ROOT,
            repository_identity=REPOSITORY, psql_command=postgres.psql_command)
        result = query_semantic_candidates(postgres.psql_args, query=query, psql_command=postgres.psql_command)
        after = query_canonical_node_records(postgres.psql_args, root_path=ROOT,
            repository_identity=REPOSITORY, psql_command=postgres.psql_command)
        assert result.reason == "extension_absent" and result.candidates == ()
        assert before == after and len(before) == 3
        assert postgres.psql_scalar("SELECT count(*) FROM pg_extension WHERE extname = 'vector'") == "0"
        assert postgres.psql_scalar("SELECT count(*) FROM pg_namespace WHERE nspname = 'repomap_enrichment'") == "0"


@pytest.mark.requires_pgvector
def test_selected_candidate_capability_boundary() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        available = postgres.psql_scalar("SELECT count(*) FROM pg_available_extension_versions WHERE name = 'vector' AND version = '0.8.7'")
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        assert available == "1", "exact boundary requires an admitted pgvector 0.8.7 test image"
        _execute(postgres, f"CREATE ROLE {READER} NOLOGIN; CREATE ROLE {WRITER} NOLOGIN; "
            "CREATE SCHEMA repomap_vector; CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';")
        try:
            _execute(postgres, candidate_schema_sql(read_principal=READER, enrichment_principal=WRITER))
            publication = _publish(postgres)
            query = replace(candidate_query(), publication=publication)
            _execute(postgres, build_embedding_import_sql(publication, PROFILE, _entries(),
                rebuild_id=query.rebuild_id, enrichment_principal=WRITER, public_safe=True), role=WRITER)

            # Record original schema state (owners, ACLs, principal, receipt) before dump
            original_state = record_optional_schema_state(postgres, reader=READER, writer=WRITER)
            assert original_state["enrichment_principal"] == WRITER

            # Verify session-independent row boundary and COPY spoof refusal
            _check_principal_restore_boundary(postgres)

            # Verify real SELECT-only reader and writer spoof/publish/graph truth refusals
            verify_reader_privilege_refusals(postgres, reader=READER)
            verify_writer_privilege_refusals(postgres, writer=WRITER)

            # Full optional-schema logical pg_dump/restore in second disposable DB
            with tempfile.TemporaryDirectory() as tmpdir:
                backup_path = Path(tmpdir) / "candidate_dump.sql"
                restored_db = execute_candidate_dump_restore(
                    postgres,
                    backup_path=backup_path,
                    second_db_name="repomap_test_candidates_restored",
                    reader=READER,
                    writer=WRITER,
                    restore_role="candidate_fixture_restorer",
                )
                try:
                    # Prove saved original owners, restored ACLs, and principal are preserved
                    verify_restored_acl_and_principal(restored_db, expected=original_state, reader=READER, writer=WRITER)

                    # Preserve candidate readback in restored database
                    restored_found = _read(restored_db, query)
                    assert restored_found.status == "ok", restored_found.reason
                    assert [row["canonical_key"] for row in restored_found.candidates] == [
                        "file:src/a.py", "file:src/b.py", "file:src/c.py"
                    ]
                    assert [row["distance"] for row in restored_found.candidates] == [0, 0, 1]

                    # Optional teardown in restored DB without CASCADE and prove canonical readback unchanged
                    restored_before_nodes = query_canonical_node_records(
                        restored_db.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=restored_db.psql_command
                    )
                    teardown_optional_schema_without_cascade(restored_db, reader=READER, writer=WRITER)
                    restored_after_nodes = query_canonical_node_records(
                        restored_db.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=restored_db.psql_command
                    )
                    assert restored_after_nodes == restored_before_nodes and len(restored_after_nodes) == 3
                finally:
                    # Clean up the second disposable database
                    _execute(postgres, "DROP DATABASE IF EXISTS repomap_test_candidates_restored;")

            before = postgres.psql_scalar("SELECT count(*) FROM canonical_edges")
            found = _read(postgres, query)
            assert found.status == "ok", found.reason
            assert [row["canonical_key"] for row in found.candidates] == ["file:src/a.py", "file:src/b.py", "file:src/c.py"]
            assert [row["distance"] for row in found.candidates] == [0, 0, 1]
            assert all(row["evidence"] for row in found.candidates)
            assert _read(postgres, query) == found
            with pytest.raises(StorageSchemaError, match="semantic candidate query failed"):
                _execute(postgres, f"REVOKE SELECT ON repomap_enrichment.embeddings FROM {READER}")
                try:
                    _read(postgres, query)
                finally:
                    _execute(postgres, f"GRANT SELECT ON repomap_enrichment.embeddings TO {READER}")
            for status in ("running", "failed"):
                unaccepted_id = int(postgres.psql_scalar(
                    "INSERT INTO runs(repository_id, status) SELECT repository_id, "
                    f"'{status}' FROM runs WHERE id = {publication.publication.run_id} RETURNING id"
                ))
                unaccepted = replace(query, publication=replace(publication,
                    publication=replace(publication.publication, run_id=GraphRunId(unaccepted_id))))
                assert _read(postgres, unaccepted).reason == "stale_publication"
                with pytest.raises(StorageSchemaError):
                    _execute(postgres, build_embedding_import_sql(unaccepted.publication, PROFILE, _entries(),
                        rebuild_id=f"unaccepted-{status}", enrichment_principal=WRITER, public_safe=True), role=WRITER)
            assert _read(postgres, query) == found
            filtered = _read(postgres, replace(query, path="src/c.py", limit=1))
            assert [row["canonical_key"] for row in filtered.candidates] == ["file:src/c.py"]
            assert _read(postgres, replace(query, kind="python.module")).candidates == ()
            assert _read(postgres, replace(query, source_binding_id="bind1:foreign")).candidates == ()
            assert _read(postgres, replace(query, rebuild_id="absent")).reason == "enrichment_unavailable"
            assert _read(postgres, replace(query, profile=replace(PROFILE, model_version="2"))).reason == "enrichment_unavailable"
            assert _read(postgres, replace(query, profile=replace(PROFILE, dimensions=4), vector=(1, 0, 0, 0))).reason == "enrichment_unavailable"
            _execute(postgres, f"UPDATE repomap_enrichment.rebuilds SET model_version = 'foreign' WHERE rebuild_id = '{query.rebuild_id}'")
            assert _read(postgres, query).reason == "enrichment_unavailable"
            _execute(postgres, f"UPDATE repomap_enrichment.rebuilds SET model_version = '1' WHERE rebuild_id = '{query.rebuild_id}'")
            foreign = replace(query, publication=replace(publication, repository_identity="repo1:foreign"))
            assert _read(postgres, foreign).reason == "stale_publication"
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_edges") == before
            with pytest.raises(StorageSchemaError):
                _execute(postgres, build_embedding_import_sql(publication, PROFILE, _entries(),
                    rebuild_id=query.rebuild_id, enrichment_principal=WRITER, public_safe=True), role=WRITER)
            assert _read(postgres, query) == found
            _publish(postgres, revision=2)
            assert _read(postgres, query).reason == "stale_publication"
            successor = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
            assert successor is not None
            assert _read(postgres, replace(query, publication=CandidatePublication(REPOSITORY, successor))).reason == "enrichment_unavailable"
            print("pgvector-boundary: extension_present; exact-boundary-executed=true")
        finally:
            # Exact fixture objects only; no foreign extension adoption or cascade.
            canonical_before_teardown = query_canonical_node_records(
                postgres.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=postgres.psql_command
            )
            _execute(postgres, "DROP TABLE IF EXISTS repomap_enrichment.embeddings; "
                "DROP TABLE IF EXISTS repomap_enrichment.rebuilds; DROP SCHEMA IF EXISTS repomap_enrichment; "
                "DROP EXTENSION IF EXISTS vector; DROP SCHEMA IF EXISTS repomap_vector; "
                f"DROP OWNED BY {READER}, {WRITER}; DROP ROLE IF EXISTS {READER}; DROP ROLE IF EXISTS {WRITER}; "
                "DROP ROLE IF EXISTS candidate_fixture_restorer;")
            canonical_after_teardown = query_canonical_node_records(
                postgres.psql_args, root_path=ROOT, repository_identity=REPOSITORY, psql_command=postgres.psql_command
            )
            assert canonical_after_teardown == canonical_before_teardown and len(canonical_after_teardown) == 3
