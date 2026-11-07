"""Live process/CID attribution is required independently of global Docker IDs."""
from dataclasses import replace
from pathlib import Path

import pytest

from retrieval_semantic_bridge_ownership import (
    BridgeOwnershipError, ProcessObservation, RunnerIdentity, identify_outer_cid, verify_outer_inspection,
)

CID = 'a' * 64
IMAGE = 'sha256:' + 'b' * 64
SELECTOR = 'src/test/int/python/repomap_kg/retrieval/semantic_vector_milestone.int.test.py'


def _owner():
    return RunnerIdentity(100, 10.0, Path('/public-source'), IMAGE, (SELECTOR,))


def _processes():
    return [ProcessObservation(100, 1, 10.0, ('python3', 'canonical-runner')),
            ProcessObservation(101, 100, 11.0, ('docker', 'logs', '--follow', CID)),
            ProcessObservation(102, 100, 11.1, ('docker', 'wait', CID))]


def _inspection():
    return {'Id': CID, 'Image': IMAGE, 'State': {'Running': True},
            'Config': {'Labels': {'org.repomap.test.sandbox': 'true',
                                  'org.repomap.test.sandbox.backend': 'monolithic-dind-v1'},
                       'Cmd': ['docker-init', '--', 'python3', '/workspace-ro/tools/test_sandbox_entrypoint.py',
                               '--docker-group', '20', '--', '--suite', 'int', '--jobs', '1',
                               '--no-coverage', '--pg-test-profile', 'pgvector', '--', SELECTOR, '-s']},
            'Mounts': [{'Type': 'bind', 'Source': '/public-source', 'Destination': '/workspace-ro', 'RW': False}]}


def test_exact_live_descendants_and_inspected_source_are_both_required():
    owner = _owner()
    assert identify_outer_cid(owner, _processes()) == CID
    verify_outer_inspection(owner, CID, _inspection())


@pytest.mark.parametrize('change', ['reused_pid', 'dead_root', 'foreign_parent', 'cid_disagreement',
                                  'missing_wait', 'ambiguous_logs', 'creation_before_parent'])
def test_ambiguous_or_foreign_processes_cannot_supply_an_outer_cid(change):
    processes = _processes()
    if change == 'reused_pid':
        processes[0] = replace(processes[0], creation_time=12.0)
    elif change == 'dead_root':
        processes[0] = replace(processes[0], alive=False)
    elif change == 'foreign_parent':
        processes[1] = replace(processes[1], parent_pid=999)
    elif change == 'cid_disagreement':
        processes[2] = replace(processes[2], argv=('docker', 'wait', 'c' * 64))
    elif change == 'missing_wait':
        processes.pop()
    elif change == 'ambiguous_logs':
        processes.append(replace(processes[1], pid=103))
    elif change == 'creation_before_parent':
        processes[1] = replace(processes[1], creation_time=9.0)
    with pytest.raises(BridgeOwnershipError):
        identify_outer_cid(_owner(), processes)


@pytest.mark.parametrize('change', ['image', 'cid', 'stopped', 'labels', 'selector', 'writable', 'other_mount', 'coverage'])
def test_container_inspection_cannot_replace_missing_source_or_scope_proof(change):
    inspection = _inspection()
    if change == 'image':
        inspection['Image'] = 'sha256:' + 'c' * 64
    elif change == 'cid':
        inspection['Id'] = 'c' * 64
    elif change == 'stopped':
        inspection['State']['Running'] = False
    elif change == 'labels':
        inspection['Config']['Labels'] = {}
    elif change == 'selector':
        inspection['Config']['Cmd'][-2] = 'src/test/int/python/other.int.test.py'
    elif change == 'writable':
        inspection['Mounts'][0]['RW'] = True
    elif change == 'other_mount':
        inspection['Mounts'].append({'Type': 'bind', 'Source': '/private-data', 'Destination': '/private'})
    elif change == 'coverage':
        inspection['Config']['Cmd'].remove('--no-coverage')
    with pytest.raises(BridgeOwnershipError):
        verify_outer_inspection(_owner(), CID, inspection)
