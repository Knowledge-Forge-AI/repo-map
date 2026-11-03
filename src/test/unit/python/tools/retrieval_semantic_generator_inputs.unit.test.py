"""Generation admission refuses stale, private and inapplicable input before a kernel exists."""
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import repomap_test_support.w5_generator_support as generator_support
from common_lore_index.ops.config import (
    OpsGraphConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
    OpsSourcesConfig,
)
from common_lore_index.ops.config_local import LocalSqliteConfig
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_GRAPH_ID
from repomap_test_support.retrieval_evaluation_publication import PublishedCorpusState
from repomap_test_support.w5_semantic_support import (
    BIND_CORE, BIND_PRIVATE, make_w5_calibration_task, make_w5_policy,
    make_w5_sample_nodes_and_evidence, make_w5_verified_pin,
)
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_semantic_generator_inputs import build_worker_request, prepare_public_generation_input
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_provenance import RepresentationValidationError
from retrieval_semantic_representation import (
    RepresentationValidationReport, validate_canonical_node_representations,
)


def _report(*, generation: int = 1):
    pin = make_w5_verified_pin(generation=generation)
    nodes, evidence = make_w5_sample_nodes_and_evidence(generation=generation)
    report = validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
    return pin, report


def _prepare(pin, report, tasks=(), **kwargs):
    return prepare_public_generation_input(
        report, tasks, read_current=kwargs.pop('read_current', lambda: pin),
        read_representations=kwargs.pop('read_representations', lambda: report),
    )


@pytest.mark.parametrize('backend', ['sqlite', 'postgresql'])
def test_private_graph_refuses_direct_representation_read_before_backend_loaders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: str,
) -> None:
    graph = OpsGraphConfig(
        id=MIXED_V1_GRAPH_ID,
        name='private mixed fixture',
        root_path='.',
        root_path_expanded='.',
        repository_name='fixture',
        privacy='private-ops',
        enabled=True,
        mcp_visible=False,
        extractor_profile='default',
        refresh_policy='manual',
    )
    config = LocalSqliteConfig(
        config_path=str(tmp_path / 'config.toml'),
        config_home=str(tmp_path),
        config_files=(),
        schema_version=1,
        service=OpsServiceConfig('native', 'stdio', 'WARNING'),
        graphs=(graph,),
        server_memory=OpsServerMemoryConfig(False, '[redacted]', '[redacted]', 'disabled'),
        sources=OpsSourcesConfig(),
    )
    published = object.__new__(PublishedCorpusState)
    object.__setattr__(published, 'home_root', tmp_path)
    object.__setattr__(published, 'graph_id', MIXED_V1_GRAPH_ID)
    reader = GeneratorFixtureReader(
        published, make_w5_policy(graph_id=MIXED_V1_GRAPH_ID), backend,
    )
    loader_calls: list[str] = []

    def forbidden_loader(*_args: object, **_kwargs: object) -> None:
        loader_calls.append('accepted-data-loader')
        raise AssertionError('private graph opened accepted data')

    monkeypatch.setattr(generator_support, 'load_graph_registry_config_home', lambda _home: config)
    monkeypatch.setattr(generator_support, 'load_sqlite_accepted_nodes_and_evidence', forbidden_loader)
    monkeypatch.setattr(generator_support, 'load_postgres_accepted_nodes_and_evidence', forbidden_loader)

    with pytest.raises(RepresentationValidationError, match='graph_privacy_not_authorized'):
        reader.read_representations()
    assert loader_calls == []


def test_public_documents_and_questions_have_distinct_source_bound_identities():
    pin, report = _report()
    task = make_w5_calibration_task()
    result = _prepare(pin, report, (task,))
    assert len(result.documents) == len(report.verified_entries) == 3
    assert len(result.records) == 4
    assert result.records[-1].text == task.question
    assert result.records[-1].mode == SemanticMode.QUERY
    assert all(record.mode == SemanticMode.DOCUMENT for record in result.records[:-1])
    assert len({record.record_id for record in result.records}) == 4
    assert result.query_decisions[0].state == 'admitted'
    changed_task = replace(task, question='Locate a different accepted name')
    changed = _prepare(pin, report, (changed_task,))
    assert changed.input_identity != result.input_identity
    assert changed.query_decisions[0].task_sha256 != result.query_decisions[0].task_sha256
    assert changed.representation_report_identity == result.representation_report_identity


def test_private_scope_has_a_refusal_ledger_but_no_question_record():
    pin, report = _report()
    task = make_w5_calibration_task(selected_bindings=(BIND_PRIVATE,), grading_rule='safety_refusal')
    result = _prepare(pin, report, (task,))
    decision = result.query_decisions[0]
    assert decision.state == 'refused'
    assert decision.reason == 'binding_privacy_not_authorized'
    assert decision.record_id is None
    assert all(record.mode == SemanticMode.DOCUMENT for record in result.records)
    assert all(record.text != task.question for record in result.records)


@pytest.mark.parametrize('stratum,surface', [('body', 'captured_text'), ('graph_topology', 'stored_metadata'),
                                          ('direct_handoff', 'direct_location')])
def test_inapplicable_task_stays_visible_without_becoming_a_query(stratum, surface):
    pin, report = _report()
    task = make_w5_calibration_task(comparability_stratum=stratum, intended_match_surface=surface)
    result = _prepare(pin, report, (task,))
    assert result.query_decisions[0].state == 'unavailable'
    assert result.query_decisions[0].record_id is None
    assert len(result.records) == len(result.documents)


@pytest.mark.parametrize('change,code', [({'split': 'held_out'}, 'held_out_execution_forbidden'),
                                       ({'generation': 2}, 'generation_mismatch'),
                                       ({'graph_id': 'another-graph'}, 'graph_id_mismatch'),
                                       ({'selected_bindings': (BIND_CORE, BIND_CORE)}, 'invalid_task_binding_scope')])
def test_invalid_task_invalidates_the_entire_input_without_partial_return(change, code):
    pin, report = _report()
    task = replace(make_w5_calibration_task(), **change)
    with pytest.raises(RepresentationValidationError) as error:
        _prepare(pin, report, (task,))
    assert error.value.code == code


def test_duplicate_tasks_and_document_digests_are_not_coerced():
    pin, report = _report()
    task = make_w5_calibration_task()
    with pytest.raises(RepresentationValidationError, match='duplicate_calibration_task'):
        _prepare(pin, report, (task, task))
    forged = replace(report.verified_entries[0], input_digest='sha256:' + '0' * 64)
    with pytest.raises(RepresentationValidationError, match='representation_digest_mismatch'):
        _prepare(pin, replace(report, verified_entries=(forged, *report.verified_entries[1:])))
    duplicate = replace(
        report,
        verified_entries=(report.verified_entries[0], report.verified_entries[0], report.verified_entries[2]),
    )
    with pytest.raises(RepresentationValidationError, match='duplicate_representation_identity'):
        _prepare(pin, duplicate)


def test_readback_advance_during_preparation_refuses_the_whole_manifest():
    pin, report = _report()
    advanced = make_w5_verified_pin(generation=2, run_id=2)
    observations = iter((pin, advanced))
    with pytest.raises(RepresentationValidationError, match='generation_publication_advanced'):
        _prepare(pin, report, read_current=lambda: next(observations))


def test_fresh_representation_readback_and_public_bundle_drift_are_refused():
    pin, report = _report()
    with pytest.raises(RepresentationValidationError, match='generation_representation_advanced'):
        _prepare(pin, report, read_representations=lambda: replace(report, coverage_ceiling=4))
    prepared = _prepare(pin, report)
    forged = replace(prepared, documents=prepared.documents[:-1])
    with pytest.raises(RepresentationValidationError, match='generation_input_changed'):
        forged.require_current()


def test_representation_reader_is_mandatory_before_public_input_creation():
    pin, report = _report()
    with pytest.raises(RepresentationValidationError, match='missing_representation_reader'):
        prepare_public_generation_input(
            report,
            (),
            read_current=lambda: pin,
            read_representations=cast(Callable[[], RepresentationValidationReport], None),
        )


def test_scope_gaps_survive_successful_preparation():
    pin, report = _report()
    partial = replace(report, partial_coverage=True, truncated=True, total_eligible_count=10)
    prepared = _prepare(pin, partial, read_representations=lambda: partial)
    assert prepared.partial_publication_coverage
    assert prepared.truncated_representation_count == 7
    assert len(prepared.documents) == 3


def test_generation_two_catalog_task_keeps_document_only_input_without_query_record():
    pin, report = _report(generation=2)
    task = replace(
        make_w5_calibration_task(
            task_id="cal-23", generation=2, grading_rule="absent_answer",
            intended_match_surface="extracted_metadata",
        ),
        requested_mode="current_literal_enumeration",
        gold_targets=(),
    ).validate()

    prepared = _prepare(pin, report, (task,))
    assert len(prepared.documents) == 3
    assert len(prepared.records) == len(prepared.documents)
    assert all(record.mode == SemanticMode.DOCUMENT for record in prepared.records)
    assert len(prepared.query_decisions) == 1
    decision = prepared.query_decisions[0]
    assert decision.task_id == "cal-23"
    assert decision.state == "unavailable"
    assert decision.reason == "unsupported_semantic_query_mode"
    assert decision.record_id is None

    request = build_worker_request(
        prepared,
        attempt_id="generation-2-document-only",
        artifact_profile_identity="sha256:" + ("0" * 64),
    )
    assert request["records"] == [
        {"record_id": record.record_id, "text": record.text, "mode": "document"}
        for record in prepared.records
    ]
