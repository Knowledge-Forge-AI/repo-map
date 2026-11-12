"""Real pgvector study SQL: creation, child fences, import rollback, v1 parity, observed ANN, staleness, cleanup.

Synthetic axis vectors prove SQL, catalog and lifecycle mechanics only; they
never prove model origin, learned relevance or ANN acceleration. The fixture is
the unchanged mixed-v1 PostgreSQL publication (generation 1, then 2). The
positive ANN case uses the default planner only (no forcing, ANALYZE or warm-up)
and must observe the owned index; a separate unindexed batch is the genuine
unavailable case.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.semantic_candidate_import import build_embedding_import_sql
from common_lore_index.storage.semantic_candidates import CandidateQuery, EmbeddingEntry, EmbeddingProfile
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.semantic_candidate_restore import cleanup_optional_sql_fixture
from repomap_test_support.w5_experiment_postgres import (
    HNSW_OWNER_ROLE, READ_ROLE, WRITE_ROLE, _query, exact_candidates, execute_sql, install_candidate_schema,
)
from repomap_test_support.w5_experiment_support import candidate_publication, prepare_postgres_generation
from repomap_test_support.w5_public_text_postgres import (
    cleanup_study, create_batch_index, create_study_relations, exact_read, import_batch, observe_ann,
    read_relation_state, run_study_sql,
)
from repomap_test_support.w5_semantic_support import make_w5_calibration_task
from retrieval_public_text_fusion import study_arm_id, v1_vector_arm
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_study_catalog import RelationIdentity, StudyCatalog, parse_relation_state
from retrieval_public_text_study_queries import StudyBatch, StudyEntry, StudyQuery, exact_sql
from retrieval_public_text_study_schema import StudyEmbeddingProfile, StudyNames, qualified
from retrieval_semantic_generator_inputs import prepare_public_generation_input

V1_PROFILE = EmbeddingProfile("synthetic-axis-384", "1", "public-fixture-author", "1", 384)
PTX_PROFILE = StudyEmbeddingProfile("synthetic-axis-384", "1", "public-fixture-author", "1")
CATALOG = """SELECT json_build_object(
    'roles', (SELECT json_agg(rolname ORDER BY rolname) FROM pg_catalog.pg_roles),
    'members', (SELECT count(*) FROM pg_catalog.pg_auth_members),
    'namespaces', (SELECT json_agg(json_build_array(nspname, nspacl::text) ORDER BY nspname) FROM pg_catalog.pg_namespace),
    'extensions', (SELECT json_agg(extname ORDER BY extname) FROM pg_catalog.pg_extension),
    'database_acl', (SELECT json_agg(a ORDER BY a::text) FROM pg_catalog.pg_database d,
        aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a WHERE d.datname = current_database()),
    'default_acls', (SELECT count(*) FROM pg_catalog.pg_default_acl),
    'acls', (SELECT json_agg(json_build_array(c.relname, c.relacl::text) ORDER BY c.relname)
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('repomap_enrichment', 'repomap_vector') AND c.relkind IN ('r', 'v', 'm', 'i')
          AND c.relname NOT LIKE 'ptx\\_%'))::text;"""


def _axis(index: int) -> tuple[float, ...]:
    return tuple(1.0 if position == index % 384 else 0.0 for position in range(384))


def _catalog(database: Any) -> dict[str, Any]:
    return json.loads(run_study_sql(database, CATALOG))


def _generation(root: Path, database: Any, generation: int) -> tuple[Any, Any, Any, str, list[Any]]:
    _published, reader = prepare_postgres_generation(root, database=database, generation=generation)
    pin, publication = reader.read_pin(), candidate_publication(reader)
    inputs = prepare_public_generation_input(reader.read_representations(), (), read_current=reader.read_pin,
                                             read_representations=reader.read_representations)
    by_binding: dict[str, list[Any]] = {}
    for document in inputs.documents:
        by_binding.setdefault(document.representation.source_binding_id, []).append(document.representation)
    binding = max(sorted(by_binding), key=lambda b: len(by_binding[b]))
    assert len(by_binding[binding]) >= 3
    return pin, publication, inputs, binding, by_binding[binding]


def _entries(reps: list[Any], *, ptx: bool) -> tuple[StudyEntry, ...]:
    return tuple(StudyEntry(rep.canonical_key, rep.source_binding_id, rep.snapshot_id, rep.input_digest,
                            ("sha256:" + f"{i:064x}") if ptx else None, ptx and i == 0, _axis(i % 3))
                 for i, rep in enumerate(reps))


def _batch(names: StudyNames, arm: str, entries: tuple[StudyEntry, ...]) -> StudyBatch:
    partial = any(entry.truncated for entry in entries)
    return StudyBatch(names.batch_id(1, arm), 1, arm, PTX_PROFILE if arm == ARM_PTX else V1_PROFILE,
                      "sha256:" + "a" * 64, "sha256:" + "c" * 64, "token_partial" if partial else "complete", entries)


def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["canonical_key"], row["source_binding_id"], row["distance"])


@pytest.mark.requires_pgvector
def test_public_text_study_sql_lifecycle_against_real_pgvector(tmp_path: Path) -> None:
    with temporary_postgres() as database:
        available = database.psql_scalar(
            "SELECT count(*) FROM pg_available_extension_versions WHERE name = 'vector' AND version = '0.8.7'")
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
        assert available == "1", "study SQL proof requires the admitted pgvector 0.8.7 profile"
        try:
            install_candidate_schema(database)
            _lifecycle(tmp_path, database)
        finally:
            try:
                execute_sql(database, f'DROP OWNED BY "{HNSW_OWNER_ROLE}";')
            finally:
                cleanup_optional_sql_fixture(database, reader=READ_ROLE, writer=WRITE_ROLE,
                                             extra_roles=(HNSW_OWNER_ROLE,), execute_fn=execute_sql)


def _lifecycle(root: Path, database: Any) -> None:
    pin, publication, inputs, binding, reps = _generation(root, database, 1)
    installed = _catalog(database)
    names = StudyNames("sha256:" + "7" * 64)
    catalog = create_study_relations(database, names)
    record = catalog.record
    assert parse_relation_state(read_relation_state(database, names), names) == record
    assert len(record.children) == 4 and {c.relation for c in record.children} == {"batch", "entry"}
    with pytest.raises(StorageSchemaError):
        create_study_relations(database, names)
    assert parse_relation_state(read_relation_state(database, names), names) == record
    assert database.psql_scalar(
        f"SELECT count(*) FROM pg_catalog.pg_class WHERE oid IN ({record.batch.oid}, {record.entry.oid}) "
        "AND relacl IS NULL") == "2"
    assert _catalog(database) == installed
    with pytest.raises(StorageSchemaError):
        execute_sql(database, f"SELECT count(*) FROM {qualified(names.batch_table)};", role=READ_ROLE)
    with pytest.raises(StorageSchemaError):
        execute_sql(database, f"SELECT count(*) FROM {qualified(names.entry_table)};", role=WRITE_ROLE)

    v1_entries, ptx_entries = _entries(reps, ptx=False), _entries(reps, ptx=True)
    unknown = (*ptx_entries[:1], replace(ptx_entries[1], canonical_key="python.function:absent:node"))
    with pytest.raises(StorageSchemaError):
        import_batch(database, catalog, _batch(names, ARM_PTX, unknown), publication, pin)
    assert database.psql_scalar(f"SELECT count(*) FROM {qualified(names.batch_table)}") == "0"
    forged = StudyCatalog(replace(record, entry=RelationIdentity(record.entry.name, record.entry.oid, "0" * 64)))
    with pytest.raises(StorageSchemaError):
        import_batch(database, forged, _batch(names, ARM_V1, v1_entries), publication, pin)
    import_batch(database, catalog, _batch(names, ARM_V1, v1_entries), publication, pin)
    import_batch(database, catalog, _batch(names, ARM_PTX, ptx_entries), publication, pin)
    assert database.psql_scalar(f"SELECT count(*) FROM {qualified(names.entry_table)}") == str(2 * len(reps))
    _null_descriptor_rolls_back(database, names)

    _v1_parity(database, catalog, names, publication, pin, binding, v1_entries, inputs)
    catalog = create_batch_index(database, catalog, names.batch_id(1, ARM_PTX))
    _observed_ann(database, catalog, names, publication, pin, binding)

    _published_g2, _reader_g2 = prepare_postgres_generation(root, database=database, generation=2)
    installed = _catalog(database)
    stale = exact_read(database, StudyQuery(catalog, names.batch_id(1, ARM_V1), ARM_V1, V1_PROFILE, publication,
                                            binding, _axis(0)), pin)
    assert stale.state == "refused" and stale.rows == ()
    assert database.psql_scalar(
        f"SELECT count(*) FROM {qualified(names.batch_table)} b WHERE b.run_id = (SELECT max(id) FROM public.runs "
        "WHERE status = 'complete')") == "0"
    query = StudyQuery(catalog, names.batch_id(1, ARM_V1), ARM_V1, V1_PROFILE, publication, binding, _axis(0))
    assert json.loads(run_study_sql(database, exact_sql(query)).strip())["status"] == "stale_publication"
    production = _query(database, CandidateQuery(publication, V1_PROFILE, "ptx-parity-1", _axis(0), selected=True,
                                                 source_binding_id=binding))
    assert (production.status, production.reason) == ("capability_unavailable", "stale_publication")

    result = cleanup_study(database, names, catalog)
    assert result.to_dict() == {"status": "clean", "reason": None, "objects": [
        {"kind": kind, "absent": True} for kind in ["batch", "entry"] + ["constraint_index"] * 4 + ["index"]]}
    assert _catalog(database) == installed
    _unknown_or_replaced_children_refuse_every_drop(database, installed)


def _null_descriptor_rolls_back(database: Any, names: StudyNames) -> None:
    """Section 18.1: the explicit IS NOT NULL check rejects a NULL v2 descriptor and the update rolls back."""
    entry = qualified(names.entry_table)
    with pytest.raises(StorageSchemaError):
        execute_sql(database, f"UPDATE {entry} SET descriptor_identity = NULL WHERE arm = '{ARM_PTX}';",
                    role=HNSW_OWNER_ROLE)
    assert database.psql_scalar(
        f"SELECT count(*) FROM {entry} WHERE arm = '{ARM_PTX}' AND descriptor_identity IS NULL") == "0"


def _v1_parity(database: Any, catalog: StudyCatalog, names: StudyNames, publication: Any, pin: Any, binding: str,
               entries: tuple[StudyEntry, ...], inputs: Any) -> None:
    production_entries = tuple(EmbeddingEntry(e.canonical_key, e.source_binding_id, e.vector, e.input_digest)
                               for e in entries)
    execute_sql(database, build_embedding_import_sql(publication, V1_PROFILE, production_entries,
                                                     rebuild_id="ptx-parity-1", enrichment_principal=WRITE_ROLE,
                                                     public_safe=True), role=WRITE_ROLE)
    cell, expected = exact_candidates(database, publication, V1_PROFILE, rebuild_id="ptx-parity-1", vector=_axis(0),
                                      task_id="parity", publication_pin=pin, source_binding_id=binding)
    observed = exact_read(database, StudyQuery(catalog, names.batch_id(1, ARM_V1), ARM_V1, V1_PROFILE, publication,
                                               binding, _axis(0)), pin)
    assert cell.execution_state.value == "completed" and observed.state == "completed" and len(expected) >= 3
    assert [{k: v for k, v in row.items() if k != "descriptor_identity"} for row in observed.rows] == list(expected)
    assert all(row["descriptor_identity"] is None for row in observed.rows)
    ties = [row["canonical_key"] for row in expected if row["distance"] == 0]
    assert len(ties) >= 1 and ties == sorted(ties, key=lambda key: key.encode("utf-8"))
    task = make_w5_calibration_task(task_id="cal-01", graph_id=pin.graph_id, selected_bindings=(binding,))
    arm = v1_vector_arm("exact_vector", observed.rows, task=task, pin=pin, inputs=inputs)
    assert arm.arm_id == study_arm_id("exact_vector", ARM_V1)
    candidates = arm.vector_candidates
    assert candidates is not None
    assert [c.input_digest for c in candidates] == [row["input_digest"] for row in observed.rows]
    absent = exact_read(database, StudyQuery(catalog, names.batch_id(2, ARM_V1), ARM_V1, V1_PROFILE, publication,
                                             binding, _axis(0)), pin)
    production_absent, _rows = exact_candidates(database, publication, V1_PROFILE, rebuild_id="ptx-absent",
                                                vector=_axis(0), task_id="parity", publication_pin=pin,
                                                source_binding_id=binding)
    assert (absent.state, absent.reason) == ("unavailable", "enrichment_unavailable")
    assert production_absent.reason == "enrichment_unavailable"
    execute_sql(database, "DELETE FROM repomap_enrichment.embeddings; DELETE FROM repomap_enrichment.rebuilds;")


def _observed_ann(database: Any, catalog: StudyCatalog, names: StudyNames, publication: Any, pin: Any,
                  binding: str) -> None:
    query = StudyQuery(catalog, names.batch_id(1, ARM_PTX), ARM_PTX, PTX_PROFILE, publication, binding, _axis(0),
                       limit=3)
    outcome = observe_ann(database, query, pin, task_id="cal-01", repetition=1)
    print(f"public-text-ann: state={outcome.state} reason={outcome.reason} index_selected={outcome.index_selected}")
    # F3: the default planner must select the registered owned index, and the credited rows must be the rows the
    # same execution produced, equal to an exact recomputation over the same data.
    assert (outcome.state, outcome.reason, outcome.index_selected) == ("completed", None, True)
    assert outcome.records is not None and outcome.records.temp_dropped is True
    assert outcome.records.postflight["temp_persistence"] == "t" and outcome.plan_sha256 and outcome.result_sha256
    exact = exact_read(database, replace(query, limit=3), pin)
    assert exact.state == "completed" and len(exact.rows) >= 1
    assert [_row_key(row) for row in outcome.records.result["candidates"]] == [_row_key(row) for row in exact.rows]
    assert [_row_key(row) for row in outcome.rows] == [_row_key(row) for row in exact.rows]
    assert database.psql_scalar("SELECT count(*) FROM pg_catalog.pg_class WHERE relname LIKE 'ptx\\_ann\\_%'") == "0"
    unindexed = observe_ann(database, replace(query, batch_id=names.batch_id(1, ARM_V1), arm=ARM_V1,
                                              profile=V1_PROFILE), pin, task_id="cal-01", repetition=2)
    assert (unindexed.state, unindexed.reason, unindexed.index_selected, unindexed.rows) == (
        "unavailable", "index_not_selected", False, ())
    assert unindexed.plan_sha256 is not None and unindexed.records is not None
    second = database.create_database("ptx_temp_absent")
    try:
        execute_sql(database, "REVOKE TEMPORARY ON DATABASE ptx_temp_absent FROM PUBLIC;")
        absent = observe_ann(second, query, pin, task_id="cal-01", repetition=3)
        assert (absent.state, absent.reason, absent.records) == ("unavailable", "temp_privilege_absent", None)
    finally:
        execute_sql(database, "DROP DATABASE ptx_temp_absent;")


def _relations(database: Any, names: StudyNames) -> int:
    return int(database.psql_scalar(
        "SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE n.nspname = 'repomap_enrichment' AND (c.relname LIKE 'ptx\\_%\\_{names.h}%' "
        f"OR c.relname = '{names.index_name(names.batch_id(1, ARM_PTX))}' OR c.relname LIKE 'ptx\\_foreign%' "
        f"OR c.oid IN (SELECT indexrelid FROM pg_catalog.pg_index WHERE indrelid = to_regclass("
        f"'{qualified(names.entry_table)}') OR indrelid = to_regclass('{qualified(names.batch_table)}')))"))


def _unknown_or_replaced_children_refuse_every_drop(database: Any, installed: dict[str, Any]) -> None:
    """F5: an unknown, replaced or in-place-altered child refuses every relevant use and cleanup; nothing is dropped."""
    owner = {"role": HNSW_OWNER_ROLE}
    for number, alteration in enumerate((
        "CREATE INDEX ptx_foreign_{n} ON {entry} (batch_id);",
        "ALTER INDEX repomap_enrichment.{index} RENAME TO ptx_foreign_{n}; CREATE INDEX {index} ON {entry} USING hnsw "
        "((embedding::repomap_vector.vector(384)) repomap_vector.vector_cosine_ops) WHERE batch_id = '{batch}' "
        "AND dimensions = 384; COMMENT ON INDEX repomap_enrichment.{index} IS '{comment}';",
        "COMMENT ON INDEX repomap_enrichment.{index} IS 'foreign';",
        "ALTER TABLE {entry} ENABLE ROW LEVEL SECURITY;",
    ), 1):
        names = StudyNames("sha256:" + f"{number:x}" * 64)
        catalog = create_study_relations(database, names)
        batch_id = names.batch_id(1, ARM_PTX)
        catalog = create_batch_index(database, catalog, batch_id)
        index = names.index_name(batch_id)
        execute_sql(database, alteration.format(
            n=number, entry=qualified(names.entry_table), index=f'"{index}"', batch=batch_id,
            comment=f"cloe-public-text-study:v1:{names.study_identity}:hnsw:{batch_id}"), **owner)
        before = _relations(database, names)
        refused = cleanup_study(database, names, catalog)
        assert (refused.status, refused.reason) == ("failed", "cleanup_failed:relation_identity_changed")
        assert _relations(database, names) == before and before >= 7
        objects = cast(list[dict[str, object]], refused.to_dict()["objects"])
        assert [o["kind"] for o in objects] == (
            ["batch", "entry"] + ["constraint_index"] * 4 + ["index"])
        assert objects[0]["absent"] is False
        with pytest.raises(StorageSchemaError):
            create_batch_index(database, catalog, names.batch_id(1, ARM_V1))
        execute_sql(database, f"DROP TABLE {qualified(names.entry_table)} RESTRICT; "
                    f"DROP TABLE {qualified(names.batch_table)} RESTRICT;", **owner)
    never = StudyNames("sha256:" + "6" * 64)
    assert cleanup_study(database, never, None).to_dict() == {"status": "clean", "reason": None, "objects": [
        {"kind": "batch", "absent": True}, {"kind": "entry", "absent": True}]}
    assert _catalog(database) == installed
