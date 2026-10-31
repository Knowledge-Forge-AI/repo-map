"""Support helpers for PostgreSQL semantic candidate dump/restore and ACL verification.

This fixture targets a second disposable database in the same cluster. Roles
are cluster-global and already exist; the distinct restorer is a superuser.
It does not qualify restricted lifecycle privileges or cross-cluster role restore.
Within the disposable test authorization, lifecycle restore must:
- Prove extension availability (pgvector 0.8.7) before applying dump
- Operate under an isolated test-owned NOLOGIN SUPERUSER lifecycle restorer
- Install the exact extension into repomap_vector with saved original owner
- Restore without CASCADE
- Preserve principal (enrichment_principal == WRITER)
- Preserve receipt and candidate readback
- Enforce real SELECT-only reader and writer spoof/publish/graph truth refusals
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.publication_readback import read_latest_publication
from repomap_test_support.postgres_logical_backup import (
    dump_plain_database,
    restore_plain_database,
)
from repomap_test_support.semantic_candidate_cleanup import (
    ENRICHMENT_CLEANUP_SQL as ENRICHMENT_CLEANUP_SQL,
    KNOWN_CLEANUP_STEPS as KNOWN_CLEANUP_STEPS,
    VECTOR_CLEANUP_SQL as VECTOR_CLEANUP_SQL,
    cleanup_optional_sql_fixture as cleanup_optional_sql_fixture,
    format_optional_cleanup_diagnostic as format_optional_cleanup_diagnostic,
    optional_database_cleanup as optional_database_cleanup,
    optional_sql_fixture_cleanup as optional_sql_fixture_cleanup,
    teardown_optional_schema_without_cascade as teardown_optional_schema_without_cascade,
)

PGVECTOR_VERSION = "0.8.7"
DIAGNOSTIC_ONLY_SAME_CLUSTER_REWRITTEN_SQL = True


def execute_sql(postgres: Any, sql: str, *, role: str | None = None) -> None:
    """Execute SQL with optional role setting and ON_ERROR_STOP=1."""
    text = (f'SET ROLE "{role}";\n' if role else "") + sql
    run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=text,
    )


def _has_public_schema_privilege(postgres: Any, schema: str, priv: str) -> bool:
    """Query ACL grantee=0 (PUBLIC) via aclexplode/coalesce(acldefault)."""
    count = postgres.psql_scalar(
        "SELECT count(*) FROM pg_namespace n, "
        "LATERAL aclexplode(coalesce(n.nspacl, acldefault('n'::\"char\", n.nspowner))) a "
        f"WHERE n.nspname = '{schema}' AND a.grantee = 0 AND a.privilege_type = '{priv}';"
    )
    return count not in ("", "0")


def record_optional_schema_state(
    postgres: Any, *, reader: str, writer: str
) -> dict[str, Any]:
    """Capture table ownership, privilege matrix, and principal state."""
    rebuilds_owner = postgres.psql_scalar(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'repomap_enrichment' AND tablename = 'rebuilds';"
    )
    embeddings_owner = postgres.psql_scalar(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'repomap_enrichment' AND tablename = 'embeddings';"
    )
    enrichment_principal = postgres.psql_scalar(
        "SELECT string_agg(enrichment_principal, ',' ORDER BY rebuild_id) FROM repomap_enrichment.rebuilds;"
    )
    ext_version = postgres.psql_scalar(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
    )
    ext_schema = postgres.psql_scalar(
        "SELECT n.nspname FROM pg_extension ext "
        "JOIN pg_namespace n ON n.oid = ext.extnamespace WHERE ext.extname = 'vector';"
    )
    ext_owner = postgres.psql_scalar(
        "SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname = 'vector';"
    )
    ext_comment = postgres.psql_scalar(
        "SELECT coalesce(obj_description(oid, 'pg_extension'), '') FROM pg_extension WHERE extname = 'vector';"
    )

    def _tp(role: str, table: str, priv: str) -> bool:
        return postgres.psql_scalar(f"SELECT has_table_privilege('{role}', '{table}', '{priv}');") == "t"

    def _sp(role: str, schema: str, priv: str) -> bool:
        return postgres.psql_scalar(f"SELECT has_schema_privilege('{role}', '{schema}', '{priv}');") == "t"

    def _cp(role: str, table: str, column: str, priv: str) -> bool:
        return postgres.psql_scalar(f"SELECT has_column_privilege('{role}', '{table}', '{column}', '{priv}');") == "t"

    privileges = {
        "reader_select_rebuilds": _tp(reader, "repomap_enrichment.rebuilds", "SELECT"),
        "reader_insert_rebuilds": _tp(reader, "repomap_enrichment.rebuilds", "INSERT"),
        "reader_select_embeddings": _tp(reader, "repomap_enrichment.embeddings", "SELECT"),
        "reader_insert_embeddings": _tp(reader, "repomap_enrichment.embeddings", "INSERT"),
        "reader_usage_vector": _sp(reader, "repomap_vector", "USAGE"),
        "reader_usage_enrichment": _sp(reader, "repomap_enrichment", "USAGE"),
        "writer_select_rebuilds": _tp(writer, "repomap_enrichment.rebuilds", "SELECT"),
        "writer_insert_rebuilds": _tp(writer, "repomap_enrichment.rebuilds", "INSERT"),
        "writer_select_embeddings": _tp(writer, "repomap_enrichment.embeddings", "SELECT"),
        "writer_insert_embeddings": _tp(writer, "repomap_enrichment.embeddings", "INSERT"),
        "writer_usage_vector": _sp(writer, "repomap_vector", "USAGE"),
        "writer_usage_enrichment": _sp(writer, "repomap_enrichment", "USAGE"),
        "writer_insert_enrichment_principal_col": _cp(
            writer, "repomap_enrichment.rebuilds", "enrichment_principal", "INSERT"
        ),
        "writer_insert_canonical_nodes": _tp(writer, "public.canonical_nodes", "INSERT"),
        "writer_insert_runs": _tp(writer, "public.runs", "INSERT"),
        "public_usage_vector": _has_public_schema_privilege(postgres, "repomap_vector", "USAGE"),
        "public_usage_enrichment": _has_public_schema_privilege(postgres, "repomap_enrichment", "USAGE"),
    }

    record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    receipt_mapping = record.receipt.public_mapping() if record else None

    return {
        "rebuilds_owner": rebuilds_owner,
        "embeddings_owner": embeddings_owner,
        "enrichment_principal": enrichment_principal,
        "vector_extension_version": ext_version,
        "vector_extension_schema": ext_schema,
        "vector_extension_owner": ext_owner,
        "vector_extension_comment": ext_comment,
        "privileges": privileges,
        "receipt_mapping": receipt_mapping,
        "run_id": record.run_id if record else None,
    }


def verify_restored_acl_and_principal(
    postgres: Any, *, expected: dict[str, Any], reader: str, writer: str
) -> None:
    """Prove saved owners, ACL grants/refusals, and principal are preserved after restore."""
    rebuilds_owner = postgres.psql_scalar(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'repomap_enrichment' AND tablename = 'rebuilds';"
    )
    embeddings_owner = postgres.psql_scalar(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'repomap_enrichment' AND tablename = 'embeddings';"
    )
    assert rebuilds_owner == expected["rebuilds_owner"]
    assert embeddings_owner == expected["embeddings_owner"]

    current_state = record_optional_schema_state(postgres, reader=reader, writer=writer)
    assert current_state["vector_extension_version"] == expected["vector_extension_version"]
    assert current_state["vector_extension_schema"] == expected["vector_extension_schema"]
    assert current_state["vector_extension_owner"] == expected["vector_extension_owner"]
    assert current_state["vector_extension_comment"] == expected["vector_extension_comment"]
    assert current_state["privileges"] == expected["privileges"]
    assert writer in str(current_state["enrichment_principal"]).split(",")
    assert current_state["enrichment_principal"] == expected["enrichment_principal"]

    restored_record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    assert restored_record is not None
    assert restored_record.run_id == expected["run_id"]
    assert restored_record.receipt.public_mapping() == expected["receipt_mapping"]


def verify_reader_privilege_refusals(postgres: Any, *, reader: str) -> None:
    """Enforce real SELECT-only reader boundaries; positive SELECT succeeds and all mutation attempts fail."""
    execute_sql(
        postgres,
        "SELECT count(*) FROM repomap_enrichment.rebuilds; "
        "SELECT count(*) FROM repomap_enrichment.embeddings; "
        "SELECT '[1,0,0]'::repomap_vector.vector OPERATOR(repomap_vector.<=>) '[1,0,0]'::repomap_vector.vector;",
        role=reader,
    )
    cols = (
        "rebuild_id, repository_identity, run_id, receipt_identity, source_generation, "
        "config_generation, extractor_generation, canonicalizer_generation, publication_bundle_id, "
        "snapshot_manifest_id, profile_identity, model, model_version, generator, generator_version, "
        "representation_version, dimensions, normalization, metric, privacy_class, row_count"
    )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            f"INSERT INTO repomap_enrichment.rebuilds ({cols}) "
            f"SELECT 'refused-rebuild', repository_identity, run_id, receipt_identity, source_generation, "
            f"config_generation, extractor_generation, canonicalizer_generation, publication_bundle_id, "
            f"snapshot_manifest_id, profile_identity, model, model_version, generator, generator_version, "
            f"representation_version, dimensions, normalization, metric, privacy_class, row_count "
            f"FROM repomap_enrichment.rebuilds LIMIT 1;",
            role=reader,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "INSERT INTO repomap_enrichment.embeddings "
            "SELECT 'r-denied', canonical_key, source_binding_id, snapshot_id, input_digest, dimensions, embedding "
            "FROM repomap_enrichment.embeddings LIMIT 1;",
            role=reader,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "UPDATE repomap_enrichment.rebuilds SET model = 'mutated' "
            "WHERE rebuild_id = (SELECT rebuild_id FROM repomap_enrichment.rebuilds LIMIT 1);",
            role=reader,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "DELETE FROM repomap_enrichment.embeddings "
            "WHERE rebuild_id = (SELECT rebuild_id FROM repomap_enrichment.embeddings LIMIT 1);",
            role=reader,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(postgres, "TRUNCATE TABLE repomap_enrichment.embeddings;", role=reader)
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "UPDATE public.canonical_nodes SET display_name = 'mutated' "
            "WHERE id = (SELECT id FROM public.canonical_nodes LIMIT 1);",
            role=reader,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "DELETE FROM public.canonical_nodes WHERE id = (SELECT id FROM public.canonical_nodes LIMIT 1);",
            role=reader,
        )


def verify_writer_privilege_refusals(postgres: Any, *, writer: str) -> None:
    """Enforce writer boundaries: positive SELECT/INSERT succeeds; spoofing, UPDATE/DELETE/TRUNCATE, and canonical mutation fail."""
    allowed_cols = (
        "rebuild_id, repository_identity, run_id, receipt_identity, source_generation, "
        "config_generation, extractor_generation, canonicalizer_generation, publication_bundle_id, "
        "snapshot_manifest_id, profile_identity, model, model_version, generator, generator_version, "
        "representation_version, dimensions, normalization, metric, privacy_class, row_count"
    )
    execute_sql(
        postgres,
        f"BEGIN; "
        f"INSERT INTO repomap_enrichment.rebuilds ({allowed_cols}) "
        f"SELECT 'allowed-writer-rebuild', {allowed_cols.split(', ', 1)[1]} "
        f"FROM repomap_enrichment.rebuilds LIMIT 1; "
        f"INSERT INTO repomap_enrichment.embeddings "
        f"SELECT 'allowed-writer-rebuild', canonical_key, source_binding_id, snapshot_id, input_digest, dimensions, embedding "
        f"FROM repomap_enrichment.embeddings LIMIT 1; "
        f"ROLLBACK;",
        role=writer,
    )
    cols = f"{allowed_cols}, enrichment_principal"
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            f"INSERT INTO repomap_enrichment.rebuilds ({cols}) "
            f"SELECT 'spoofed-rebuild', {allowed_cols.split(', ', 1)[1]}, 'spoofed_role' "
            f"FROM repomap_enrichment.rebuilds LIMIT 1;",
            role=writer,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(postgres, "UPDATE repomap_enrichment.rebuilds SET model = 'mutated';", role=writer)
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(postgres, "DELETE FROM repomap_enrichment.embeddings;", role=writer)
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(postgres, "TRUNCATE TABLE repomap_enrichment.embeddings;", role=writer)
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "UPDATE public.canonical_nodes SET display_name = 'mutated' "
            "WHERE id = (SELECT id FROM public.canonical_nodes LIMIT 1);",
            role=writer,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "DELETE FROM public.canonical_nodes WHERE id = (SELECT id FROM public.canonical_nodes LIMIT 1);",
            role=writer,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "UPDATE public.runs SET status = 'failed' WHERE id = (SELECT id FROM public.runs LIMIT 1);",
            role=writer,
        )
    with pytest.raises(StorageSchemaError, match="permission denied"):
        execute_sql(
            postgres,
            "DELETE FROM public.runs WHERE id = (SELECT id FROM public.runs LIMIT 1);",
            role=writer,
        )


def prepare_dump_for_lifecycle_restore(backup_path: Path, restore_role: str) -> Path:
    """Adapt dump text so pre-installed extension schema does not fail on restore."""
    text = backup_path.read_text(encoding="utf-8")
    lines = [
        f'SET ROLE "{restore_role}";',
        "CREATE TABLE public._restore_observation AS SELECT current_user AS observed_user;",
    ]
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed == "CREATE SCHEMA repomap_vector;":
            lines.append("CREATE SCHEMA IF NOT EXISTS repomap_vector;")
        elif trimmed == "CREATE EXTENSION vector WITH SCHEMA repomap_vector;":
            lines.append("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA repomap_vector;")
        else:
            lines.append(line)
    restore_path = backup_path.with_name(backup_path.stem + ".restore.sql")
    restore_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return restore_path


def execute_candidate_dump_restore(
    postgres: Any,
    *,
    backup_path: Path,
    second_db_name: str,
    reader: str,
    writer: str,
    restore_role: str = "candidate_fixture_restorer",
) -> Any:
    """Execute complete logical dump, second DB creation, extension pre-install and restore."""
    original_owner = postgres.psql_scalar(
        "SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname = 'vector';"
    )
    dump_plain_database(postgres, postgres.psql_args, backup_path)
    restored_db = postgres.create_database(second_db_name)

    execute_sql(
        postgres,
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{restore_role}') "
        f"THEN CREATE ROLE {restore_role} NOLOGIN SUPERUSER; END IF; END $$;",
    )
    execute_sql(postgres, f'GRANT {restore_role} TO "{postgres.user}";')

    available = restored_db.psql_scalar(
        f"SELECT count(*) FROM pg_available_extension_versions WHERE name = 'vector' AND version = '{PGVECTOR_VERSION}';"
    )
    assert available == "1", "exact boundary requires an admitted pgvector 0.8.7 test image"

    execute_sql(
        restored_db,
        f"CREATE SCHEMA repomap_vector; CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '{PGVECTOR_VERSION}';",
        role=original_owner,
    )

    restore_path = prepare_dump_for_lifecycle_restore(backup_path, restore_role)
    restore_plain_database(restored_db, restored_db.psql_args, restore_path)

    observed_user = restored_db.psql_scalar("SELECT observed_user FROM public._restore_observation;")
    assert observed_user == restore_role
    execute_sql(restored_db, "DROP TABLE public._restore_observation;")
    assert restored_db.psql_scalar("SELECT current_user;") != restore_role

    return restored_db
