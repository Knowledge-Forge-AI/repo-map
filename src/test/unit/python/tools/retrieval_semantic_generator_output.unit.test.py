"""A generated import batch requires complete correspondence and honest accounting."""
import hashlib
import json
from dataclasses import replace

import pytest

from repomap_test_support.w5_semantic_support import (
    make_w5_sample_nodes_and_evidence, make_w5_verified_pin,
)
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_kernel import (
    QUERY_PREFIX, SemanticCost, SemanticEmbedding, SemanticGeneration, SemanticMode,
)
from retrieval_semantic_generator_output import (
    VerifiedWorkerResponse, _response_identity, seal_generation_result,
)
from retrieval_semantic_provenance import RepresentationValidationError
from retrieval_semantic_representation import validate_canonical_node_representations

PROFILE = 'sha256:' + 'a' * 64
REQUEST = 'sha256:' + 'c' * 64
REPORT = 'sha256:' + 'd' * 64
TERMINAL = 'sha256:' + 'e' * 64
DECLARATION = 'sha256:' + 'f' * 64
MANIFEST = 'sha256:' + '0' * 64
ARCHIVE = 'sha256:' + '1' * 64
ADMISSION = 'sha256:' + '2' * 64


def _inputs_and_result():
    pin = make_w5_verified_pin()
    nodes, evidence = make_w5_sample_nodes_and_evidence()
    report = validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
    inputs = prepare_public_generation_input(report, (), read_current=lambda: pin,
                                             read_representations=lambda: report)
    embeddings = tuple(SemanticEmbedding(record.record_id, SemanticMode(record.mode), (1.0,) + (0.0,) * 383,
                                         20, 20, 0, False) for record in inputs.records)
    input_bytes = sum(len(record.record_id.encode()) + len(record.text.encode()) for record in inputs.records)
    model_bytes = sum(len(((QUERY_PREFIX if SemanticMode(record.mode) is SemanticMode.QUERY else '') + record.text).encode())
                      for record in inputs.records)
    cost = SemanticCost(
        input_records=len(embeddings), input_bytes=input_bytes,
        model_input_bytes=model_bytes, token_count_before_limit=20 * len(embeddings),
        token_count_used=20 * len(embeddings), overflow_chunks=0,
        truncated_records=0, load_seconds=0.1, inference_seconds=0.2,
        total_seconds=0.3,
    )
    result = SemanticGeneration(embeddings, cost, 'complete', False)
    response = VerifiedWorkerResponse(
        'unit-output-1', inputs.records, REQUEST, REPORT, TERMINAL, DECLARATION, MANIFEST, ARCHIVE,
        (('worker.py', 'sha256:' + '3' * 64),), ADMISSION, inputs.input_identity,
        inputs.representation_report_identity, _publication_identity(inputs), PROFILE,
        len(inputs.records), len(embeddings), len(inputs.documents), 0, result, 'completed',
    )
    return pin, inputs, replace(response, _sealed_identity=_response_identity(response))


def _publication_identity(inputs):
    raw = json.dumps(inputs.provenance.to_dict(), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _seal(inputs, response):
    return seal_generation_result(inputs, response)


def _with_generation(response, result):
    changed = replace(response, generation=result, embedding_count=len(result.embeddings),
                      document_count=sum(1 for item in result.embeddings if item.mode is SemanticMode.DOCUMENT),
                      query_count=sum(1 for item in result.embeddings if item.mode is SemanticMode.QUERY))
    return replace(changed, _sealed_identity=_response_identity(changed))


def test_complete_selected_generation_has_existing_embedding_profile_and_import_rows():
    _, inputs, response = _inputs_and_result()
    artifact = _seal(inputs, response)
    assert artifact.complete_generation
    assert len(artifact.require_importable()) == 3
    assert artifact.profile.dimensions == 384
    assert artifact.profile.representation_version == 'canonical-node-v1'
    assert artifact.profile.generator_version == 'v1:' + PROFILE[7:]
    assert artifact.entries[0].input_digest == inputs.documents[0].representation.input_digest
    assert artifact.to_dict()['component_receipt_identity'] == TERMINAL


@pytest.mark.parametrize('mutation,code', [
    ('missing', 'generation_record_count_mismatch'), ('reordered', 'generation_record_identity_mismatch'),
    ('wrong_id', 'generation_record_identity_mismatch'), ('nan', 'invalid_generated_vector'),
    ('boolean', 'invalid_generated_vector'), ('dimensions', 'invalid_generated_vector'),
    ('unnormalized', 'invalid_generated_vector'), ('cost_count', 'generation_cost_count_mismatch'),
    ('negative_cost', 'invalid_generation_cost'), ('partial_lie', 'invalid_generation_partial_state'),
    ('tokens_lie', 'generation_cost_count_mismatch'),
])
def test_invalid_whole_results_never_expose_an_importable_prefix(mutation, code):
    _, inputs, response = _inputs_and_result()
    result = response.generation
    assert result is not None
    first = result.embeddings[0]
    if mutation == 'missing':
        result = replace(result, embeddings=result.embeddings[:-1])
    elif mutation == 'reordered':
        result = replace(result, embeddings=tuple(reversed(result.embeddings)))
    elif mutation == 'wrong_id':
        result = replace(result, embeddings=(replace(first, record_id='other'), *result.embeddings[1:]))
    elif mutation in {'nan', 'boolean', 'dimensions', 'unnormalized'}:
        vectors = {'nan': (float('nan'),) + (0.0,) * 383, 'boolean': (True,) + (0.0,) * 383,
                   'dimensions': (1.0, 0.0), 'unnormalized': (2.0,) + (0.0,) * 383}
        result = replace(result, embeddings=(replace(first, vector=vectors[mutation]), *result.embeddings[1:]))
    elif mutation == 'cost_count':
        result = replace(result, cost=replace(result.cost, input_records=True))
    elif mutation == 'negative_cost':
        result = replace(result, cost=replace(result.cost, inference_seconds=-1.0))
    elif mutation == 'partial_lie':
        result = replace(result, status='partial')
    elif mutation == 'tokens_lie':
        result = replace(result, cost=replace(result.cost, token_count_used=1))
    with pytest.raises(RepresentationValidationError) as error:
        with_generation = _with_generation(response, result)
        _seal(inputs, with_generation)
    assert error.value.code == code


def test_truncated_generation_retains_evidence_but_cannot_become_complete_import():
    _, inputs, response = _inputs_and_result()
    result = response.generation
    assert result is not None
    first = replace(result.embeddings[0], token_count_before_limit=600, token_count_used=512,
                    overflow_chunks=1, truncated=True)
    cost = replace(result.cost, token_count_before_limit=640, token_count_used=552,
                   overflow_chunks=1, truncated_records=1)
    result = replace(result, embeddings=(first, *result.embeddings[1:]), cost=cost, status='partial', partial=True)
    artifact = _seal(inputs, _with_generation(response, result))
    assert not artifact.complete_generation
    assert artifact.truncated_record_ids == (first.record_id,)
    with pytest.raises(RepresentationValidationError, match='incomplete_generation_cannot_import'):
        artifact.require_importable()


def test_publication_advance_and_modified_worker_report_identity_are_refused():
    pin, inputs, response = _inputs_and_result()
    advanced = make_w5_verified_pin(generation=2, run_id=2)
    advanced_inputs = replace(inputs, _read_current=lambda: advanced)
    with pytest.raises(RepresentationValidationError, match='generation_publication_advanced'):
        _seal(advanced_inputs, response)
    tampered = replace(response, report_sha256='sha256:' + '9' * 64)
    with pytest.raises(RepresentationValidationError, match='invalid_worker_response'):
        _seal(inputs, tampered)
