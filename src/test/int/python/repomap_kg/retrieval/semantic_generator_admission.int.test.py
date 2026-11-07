"""Real current-store admission mechanics; no model or optional vector execution."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import pytest

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.sql_core import sql_literal
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT, MIXED_V1_GRAPH_ID, binding_id_for_alias,
    build_mixed_v1_projection_policy, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from repomap_test_support.semantic_candidate_cleanup import cleanup_optional_sql_fixture
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from repomap_test_support.w5_experiment_postgres import _json_array
from repomap_test_support.w5_experiment_vector import baseline_file_metrics
from retrieval_evaluation_schema import load_task_catalog
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_ann import parse_hnsw_candidates
from retrieval_semantic_ann_models import JsonObject
from retrieval_semantic_fusion import AdmittedArmObservation, fuse_arm_observations_rrf
from retrieval_semantic_generator_inputs import build_worker_request, prepare_public_generation_input
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_provenance import RepresentationValidationError

ALIASES = ('core', 'companion', 'feeds')
DECLARED_PROFILE_IDENTITY = 'sha256:033cf41ffc5ca108b6e26638573554bac64b84be744903809904ef3364722180'
# This is the actual frozen artifact identity. Core tests still exercise only
# request/admission mechanics; they do not mount or execute the model.


def _prepare(reader: GeneratorFixtureReader):
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / 'tasks/catalog-v1.json')
    report = reader.read_representations()
    tasks = tuple(task for task in catalog.calibration_tasks() if task.generation == report.provenance.generation)
    inputs = prepare_public_generation_input(report, tasks, read_current=reader.read_pin,
                                             read_representations=reader.read_representations)
    request = build_worker_request(inputs, attempt_id='integration-admission-only',
                                   artifact_profile_identity=DECLARED_PROFILE_IDENTITY)
    return report, inputs, request, tasks


def test_generator_requests_use_actual_public_fields_and_preserve_privacy_across_backends(tmp_path: Path):
    working = materialize_mixed_v1_working_copy(tmp_path / 'working', generation=1)
    sqlite_home = write_mixed_v1_sqlite_home(tmp_path / 'sqlite-home', working, declared_aliases=ALIASES)
    sqlite_published = publish_and_load_sqlite_corpus(sqlite_home, selected_aliases=ALIASES)
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID, selected_aliases=ALIASES)
    sqlite_reader = GeneratorFixtureReader(sqlite_published, policy, 'sqlite')
    sqlite_report, sqlite_inputs, sqlite_request, tasks = _prepare(sqlite_reader)
    with temporary_postgres() as database:
        pg_home = write_mixed_v1_postgres_home(tmp_path / 'pg-home', working, host=database.host,
                                             port=database.port, database=database.database,
                                             user=database.user, password=database.password, declared_aliases=ALIASES)
        pg_published = publish_and_load_postgres_corpus(pg_home, selected_aliases=ALIASES,
                                                       psql_command=database.psql_command)
        pg_reader = GeneratorFixtureReader(pg_published, policy, 'postgresql', database.psql_command)
        pg_report, pg_inputs, pg_request, pg_tasks = _prepare(pg_reader)
        sq_documents = [(doc.representation.canonical_key, doc.representation.source_binding_id,
                         doc.representation.input_digest) for doc in sqlite_inputs.documents]
        pg_documents = [(doc.representation.canonical_key, doc.representation.source_binding_id,
                         doc.representation.input_digest) for doc in pg_inputs.documents]
        assert sq_documents == pg_documents
        assert sq_documents
        assert all(binding != binding_id_for_alias('mailbox') for _key, binding, _digest in sq_documents)
        assert sqlite_inputs.input_identity != pg_inputs.input_identity
        assert [decision.task_id for decision in sqlite_inputs.query_decisions] == [task.task_id for task in tasks]
        assert [task.task_id for task in tasks] == [task.task_id for task in pg_tasks]
        assert len(sqlite_inputs.records) == len(pg_inputs.records)
        assert sqlite_report.provenance.backend == 'sqlite'
        assert pg_report.provenance.backend == 'postgresql'
        assert_canary_free(sqlite_request)
        assert_canary_free(pg_request)
        refused = [decision for decision in pg_inputs.query_decisions if decision.state == 'refused']
        assert refused  # Existing mailbox safety task remains visible without an inference record.
        assert all(decision.record_id is None for decision in refused)
        # Build the existing lexical owner in THIS accepted PostgreSQL graph.
        # A separate historical lexical database cannot be repinned to this
        # publication for fusion merely because its fixture bytes match.
        before_lexical = pg_reader.read_pin().to_dict()
        pg_config = load_graph_registry_config_home(pg_home)
        assert isinstance(pg_config, OpsConfig)
        lexical = build_graph_lexical_generation(
            pg_config, MIXED_V1_GRAPH_ID,
            selected_binding_ids=(binding_id_for_alias('core'), binding_id_for_alias('companion')),
            authorize_body=True)
        assert lexical.result == 'published', {'result': lexical.result, 'refusal_code': lexical.refusal_code}
        metadata_task = next(task for task in pg_tasks if task.requested_mode == 'ranked_discovery'
                             and task.comparability_stratum == 'metadata'
                             and set(task.selected_bindings).issubset({'core', 'companion'}))
        state, envelope, _elapsed, _bytes = execute_postgres_native_fts_task(metadata_task, pg_home)
        assert state == ExecutionState.COMPLETED
        assert envelope.scope.publication_bundle_id == pg_report.provenance.publication_bundle_id
        assert envelope.scope.snapshot_manifest_id == pg_report.provenance.snapshot_manifest_id
        pg_pin = pg_reader.read_pin()
        file_metrics, metrics_status, metrics_reason = baseline_file_metrics(
            metadata_task,
            'postgres_native_fts:postgresql',
            state,
            envelope,
            pg_pin,
        )
        assert metrics_status == 'verified', (metrics_status, metrics_reason)
        assert file_metrics is not None
        fusion = fuse_arm_observations_rrf(
            (
                AdmittedArmObservation(
                    arm_id='postgres_native_fts:postgresql',
                    mode=metadata_task.requested_mode,
                    verified_pin=pg_pin,
                    execution_state=state,
                    envelope=envelope,
                    selected_binding_ids=envelope.scope.selected_binding_ids,
                ),
            ),
            expected_pin=pg_pin,
        )
        assert fusion.execution_state == ExecutionState.COMPLETED
        assert fusion.refusal_code is None
        assert fusion.credited_as_fused is False
        assert pg_reader.read_pin().to_dict() == before_lexical
        assert_canary_free(envelope.to_dict())
        # This source-level integration never starts the worker or supplies
        # vectors. The separate isolated native component owns actual inference.


def test_generation_two_public_catalog_admission_is_document_only(tmp_path: Path):
    working = materialize_mixed_v1_working_copy(tmp_path / 'working-g2', generation=1)
    sqlite_home = write_mixed_v1_sqlite_home(
        tmp_path / 'sqlite-g2', working, declared_aliases=ALIASES
    )
    publish_and_load_sqlite_corpus(
        sqlite_home, selected_aliases=ALIASES
    )
    materialize_mixed_v1_working_copy(working, generation=2)
    sqlite_published = publish_and_load_sqlite_corpus(
        sqlite_home, selected_aliases=ALIASES
    )
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID, selected_aliases=ALIASES)
    reader = GeneratorFixtureReader(sqlite_published, policy, 'sqlite')

    report, inputs, request, tasks = _prepare(reader)

    assert report.provenance.generation == 2
    assert [task.task_id for task in tasks] == ['cal-23']
    assert len(inputs.documents) > 0
    assert len(inputs.records) == len(inputs.documents)
    assert all(record.mode == SemanticMode.DOCUMENT for record in inputs.records)
    assert [decision.task_id for decision in inputs.query_decisions] == ['cal-23']
    decision = inputs.query_decisions[0]
    assert decision.state == 'unavailable'
    assert decision.reason == 'unsupported_semantic_query_mode'
    assert decision.record_id is None
    assert request['records'] == [
        {'record_id': record.record_id, 'text': record.text, 'mode': 'document'}
        for record in inputs.records
    ]


def test_public_postgres_confidence_enums_round_trip_through_ann_parser(tmp_path: Path):
    working = materialize_mixed_v1_working_copy(tmp_path / 'working', generation=1)
    with temporary_postgres() as database:
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / 'pg-home', working, host=database.host, port=database.port,
            database=database.database, user=database.user, password=database.password,
            declared_aliases=ALIASES,
        )
        published = publish_and_load_postgres_corpus(
            pg_home, selected_aliases=ALIASES, psql_command=database.psql_command
        )
        binding_id, _revision, snapshot_id = published.manifest.snapshot_vector[0]
        digest = 'sha256:' + 'a' * 64
        payload = cast(JsonObject, json.loads(database.psql_scalar(
            "SELECT json_build_object("
            "'status', 'ok', "
            "'candidates', json_build_array(json_build_object("
            "'node_id', node.id, 'canonical_key', node.canonical_key, "
            "'kind', node.kind, 'display_name', node.display_name, "
            "'confidence', node.confidence, 'conflict', node.conflict, "
            f"'source_binding_id', {sql_literal(binding_id)}, "
            f"'input_digest', {sql_literal(digest)}, "
            f"'snapshot_id', {sql_literal(snapshot_id)}, "
            "'distance', 0.25, 'evidence', json_build_array(json_build_object("
            "'evidence_key', evidence.evidence_key, 'path', evidence.path, "
            "'start_line', evidence.start_line, 'end_line', evidence.end_line, "
            "'raw_kind', evidence.raw_kind, 'extractor', evidence.extractor, "
            "'extractor_version', evidence.extractor_version, "
            "'confidence', evidence.confidence))))) "
            "FROM public.canonical_nodes AS node "
            "JOIN public.canonical_node_evidence AS link "
            "ON link.canonical_node_id = node.id "
            "JOIN public.canonical_evidence AS evidence "
            "ON evidence.id = link.canonical_evidence_id "
            "ORDER BY node.id, evidence.id LIMIT 1;"
        )))
        parsed = parse_hnsw_candidates(
            payload, snapshot_by_binding={binding_id: snapshot_id},
            requested_limit=1, evidence_limit=1,
        )
        assert len(parsed) == 1
        assert parsed[0].evidence[0]['confidence'] in {
            'manual', 'extracted', 'heuristic', 'unknown'
        }


def test_generation_input_is_invalidated_by_actual_accepted_publication_advance(tmp_path: Path):
    working = materialize_mixed_v1_working_copy(tmp_path / 'working', generation=1)
    home = write_mixed_v1_sqlite_home(tmp_path / 'home', working, declared_aliases=ALIASES)
    published = publish_and_load_sqlite_corpus(home, selected_aliases=ALIASES)
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID, selected_aliases=ALIASES)
    reader = GeneratorFixtureReader(published, policy, 'sqlite')
    _report, inputs, _request, tasks = _prepare(reader)
    materialize_mixed_v1_working_copy(working, generation=2)
    refreshed_config = load_graph_registry_config_home(home)
    assert isinstance(refreshed_config, LocalSqliteConfig)
    refresh_local_graph(refreshed_config, MIXED_V1_GRAPH_ID)
    with pytest.raises(RepresentationValidationError):
        inputs.require_current()
    fresh_report = reader.read_representations()
    assert fresh_report.provenance.generation > inputs.provenance.generation
    with pytest.raises(RepresentationValidationError, match='held_out_execution_forbidden'):
        # A synthetic split mutation tests the boundary without selecting any
        # actual held-out task or reading held-out gold for an experiment.
        prepare_public_generation_input(fresh_report, (replace(tasks[0], generation=2, split='held_out'),),
                                        read_current=reader.read_pin, read_representations=reader.read_representations)


def test_private_or_inherited_fixture_graph_cannot_be_relabelled_by_a_public_policy(tmp_path: Path):
    working = materialize_mixed_v1_working_copy(tmp_path / 'working', generation=1)
    home = write_mixed_v1_sqlite_home(tmp_path / 'home', working)
    published = publish_and_load_sqlite_corpus(home, selected_aliases=ALIASES)
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID, selected_aliases=ALIASES)
    reader = GeneratorFixtureReader(published, policy, 'sqlite')
    with pytest.raises(RepresentationValidationError, match='graph_privacy_not_authorized'):
        reader.read_pin()


def test_postgres_explain_readback_preserves_multiline_json():
    with temporary_postgres() as database:
        payload = _json_array(
            database,
            'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT 1 AS probe;',
            role=database.user,
            label='core explain',
        )
        assert len(payload) == 1
        row = payload[0]
        assert isinstance(row, dict)
        plan = row.get('Plan')
        assert isinstance(plan, dict)
        assert plan.get('Node Type') == 'Result'

        with pytest.raises(StorageSchemaError, match='core explain refusal did not return an array'):
            _json_array(
                database,
                "SELECT '{}'::json;",
                role=database.user,
                label='core explain refusal',
            )


def test_optional_cleanup_revokes_extra_role_grants_before_role_drop():
    reader = 'w5_cleanup_reader'
    writer = 'w5_cleanup_writer'
    extra = 'w5_cleanup_extra'
    with temporary_postgres() as database:
        database.psql_scalar(
            f"CREATE ROLE {reader} NOLOGIN; CREATE ROLE {writer} NOLOGIN; "
            f"CREATE ROLE {extra} NOLOGIN; "
            "CREATE TABLE public.w5_cleanup_probe (id integer); "
            f"GRANT SELECT ON public.w5_cleanup_probe TO {reader}, {writer}, {extra};"
        )
        assert database.psql_scalar(
            f"SELECT has_table_privilege('{extra}', 'public.w5_cleanup_probe', 'SELECT');"
        ) == 't'
        oid_types = json.loads(database.psql_scalar(
            "SELECT json_build_object("
            "'raw_oid_type', json_typeof(json_build_object('oid', c.oid)->'oid'), "
            "'bigint_oid_type', json_typeof(json_build_object('oid', c.oid::bigint)->'oid')) "
            "FROM pg_catalog.pg_class AS c "
            "WHERE c.relname = 'w5_cleanup_probe' "
            "AND c.relnamespace = 'public'::regnamespace LIMIT 1;"
        ))
        assert set(oid_types) == {'raw_oid_type', 'bigint_oid_type'}
        assert oid_types['bigint_oid_type'] == 'number'
        assert oid_types['raw_oid_type'] in {'number', 'string'}
        print('catalog-json-types: ' + json.dumps(oid_types, sort_keys=True))
        cleanup_optional_sql_fixture(
            database, reader=reader, writer=writer, extra_roles=(extra,)
        )
        assert database.psql_scalar(
            "SELECT count(*) FROM pg_roles "
            f"WHERE rolname IN ('{reader}', '{writer}', '{extra}');"
        ) == '0'
        assert database.psql_scalar(
            "SELECT count(*) FROM pg_catalog.pg_namespace "
            "WHERE nspname = 'public';"
        ) == '1'
        assert database.psql_scalar(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'w5_cleanup_probe' "
            "AND c.relkind = 'r';"
        ) == '1'
        database.psql_scalar("DROP TABLE public.w5_cleanup_probe;")
