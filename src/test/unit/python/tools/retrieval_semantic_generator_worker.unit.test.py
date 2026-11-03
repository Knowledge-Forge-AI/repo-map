"""The offline worker rejects a whole invalid request before artifact/runtime access."""
import json
from pathlib import Path

import pytest

from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_generator_worker import (
    CONTROLLER_ADMISSION_SCHEMA, WorkerRequestError, _digest, _source_digests, _source_files,
    parse_worker_request, run_worker,
)


def _request():
    return {'schema': 'cloe-w5-native-generation-request-v1', 'attempt_id': 'unit-public-component-1',
            'input_identity': 'sha256:' + '1' * 64, 'representation_report_identity': 'sha256:' + '2' * 64,
            'publication_identity': 'sha256:' + '3' * 64, 'artifact_profile_identity': 'sha256:' + '4' * 64,
            'records': [{'record_id': 'document:1', 'text': 'public metadata', 'mode': 'document'}]}


def test_document_and_query_keep_their_explicit_order_and_modes():
    request = _request()
    request['records'].append({'record_id': 'query:cal-1', 'text': 'Where is the public function?', 'mode': 'query'})
    declaration, records = parse_worker_request(json.dumps(request).encode())
    assert declaration == request
    assert [record.record_id for record in records] == ['document:1', 'query:cal-1']
    assert [SemanticMode(record.mode).value for record in records] == ['document', 'query']
    assert records[1].text == 'Where is the public function?'


@pytest.mark.parametrize('mutation,code', [('extra', 'invalid_request_schema'),
                                        ('identity', 'invalid_request_identity'),
                                        ('attempt', 'invalid_attempt_id'),
                                        ('empty', 'invalid_record_count'),
                                        ('duplicate', 'invalid_or_duplicate_record_id'),
                                        ('mode', 'invalid_record_input'),
                                        ('control', 'invalid_input_bounds'),
                                        ('surrogate', 'invalid_input'),
                                        ('record_extra', 'invalid_record_schema')])
def test_bad_record_or_declaration_never_returns_a_valid_prefix(mutation, code):
    request = _request()
    if mutation == 'extra':
        request['trusted'] = True
    elif mutation == 'identity':
        request['publication_identity'] = True
    elif mutation == 'attempt':
        request['attempt_id'] = '../outside'
    elif mutation == 'empty':
        request['records'] = []
    elif mutation == 'duplicate':
        request['records'].append(dict(request['records'][0]))
    elif mutation == 'mode':
        request['records'][0]['mode'] = 'plugin'
    elif mutation == 'control':
        request['records'][0]['text'] = 'secret\x00payload'
    elif mutation == 'surrogate':
        request['records'][0]['text'] = '\ud800'
    elif mutation == 'record_extra':
        request['records'][0]['plugin'] = 'arbitrary.py'
    with pytest.raises(WorkerRequestError) as error:
        parse_worker_request(json.dumps(request).encode())
    assert error.value.code == code


def test_duplicate_json_keys_and_nonfinite_values_are_refused():
    with pytest.raises(WorkerRequestError, match='duplicate_json_key'):
        parse_worker_request(b'{"schema": "one", "schema": "two"}')
    with pytest.raises(WorkerRequestError, match='nonfinite_json'):
        parse_worker_request(b'{"unexpected": NaN}')


def test_missing_artifacts_produce_a_terminal_failure_without_embeddings(tmp_path: Path):
    request = tmp_path / 'input.json'
    request_value = _request()
    request_raw = (json.dumps(request_value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    request.write_bytes(request_raw)
    closure = _source_digests(_source_files())
    admission_value = {
        'schema': CONTROLLER_ADMISSION_SCHEMA, 'phase': 'unit',
        'operator_authority_sha256': 'sha256:' + 'a' * 64,
        'gate_references': {'unit': 'sha256:' + 'b' * 64},
        'bounded_component_execution_admitted': True, 'request_sha256': _digest(request_raw),
        'input_identity': request_value['input_identity'],
        'representation_report_identity': request_value['representation_report_identity'],
        'publication_identity': request_value['publication_identity'],
        'artifact_profile_identity': request_value['artifact_profile_identity'],
        'candidate_closure_digests': closure, 'scope': 'unit missing-artifact refusal',
    }
    admission_raw = (json.dumps(admission_value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    admission = tmp_path / 'admission.json'
    admission.write_bytes(admission_raw)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    output = tmp_path / 'output'
    with pytest.raises(WorkerRequestError):
        run_worker(request, artifacts, output, admission_path=admission,
                   expected_admission_sha256=_digest(admission_raw))
    directory = output / 'unit-public-component-1'
    terminal = json.loads((directory / 'terminal.json').read_text())
    report = json.loads((directory / 'report.json').read_text())
    assert terminal['status'] == 'failed'
    assert report['status'] == 'failed'
    assert report['embedding_count'] == 0
    assert 'embeddings' not in report
    assert (directory / 'sources.zip').is_file()
    assert (directory / 'source-manifest.json').is_file()
    # Exclusive attempt admission preserves the failed receipt rather than
    # allowing the same path to be retried into an apparent successful result.
    with pytest.raises(WorkerRequestError, match='attempt_admission_failed'):
        run_worker(request, artifacts, output, admission_path=admission,
                   expected_admission_sha256=_digest(admission_raw))
