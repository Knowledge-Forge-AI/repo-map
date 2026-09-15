"""Dynamic declarations cannot lend governance or erase source obligations."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ci.python_retention_dependencies import build_dependency_graph, find_cross_cohort_cycles
from ci.python_retention_dynamic import apply_dynamic_boundaries
from ci.python_retention_dynamic_history import SCHEMA, active_boundaries, validate_dynamic_transition
from ci.python_retention_cohort_evidence import evaluate_cohorts
from ci.python_retention_operations import dynamic_operations
import ast


OWNER = "src/test/support/python/entry.py"
TEST = "src/test/unit/python/entry.unit.test.py"
PACKAGE = "src/main/python/sample/__init__.py"
ENTRY = "src/main/python/sample/__main__.py"


def _setup(tmp_path: Path) -> tuple[list[str], dict]:
    files = {OWNER: 'import runpy\ndef enter():\n    runpy.run_module("sample", run_name="__main__")\n',
             TEST: 'import entry\ndef test_entry():\n    entry.enter()\n', PACKAGE: '', ENTRY: 'raise SystemExit(0)\n'}
    for path, content in files.items():
        full = tmp_path / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    candidates = sorted(files)
    graph = build_dependency_graph(tmp_path, candidates)
    operation = graph['dynamic_operations'][OWNER][0]
    digest = lambda p: hashlib.sha256((tmp_path / p).read_bytes()).hexdigest()
    record = dict(id='entry-v1', owner=OWNER, owner_sha256=digest(OWNER), test=TEST,
                  test_sha256=digest(TEST), recipe='literal_module_entry',
                  kind=operation['kind'], symbol=operation['symbol'],
                  fingerprint=operation['fingerprint'], supersedes=None,
                  parameters={'module': 'sample', 'run_name': '__main__'}, targets=[
                      dict(module='sample', symbol='', path=PACKAGE, sha256=digest(PACKAGE)),
                      dict(module='sample.__main__', symbol='', path=ENTRY, sha256=digest(ENTRY))])
    return candidates, record


def _write(tmp_path: Path, records: list[dict]) -> None:
    path = tmp_path / 'tools/ci/python_retention_inventory.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(dynamic_schema=SCHEMA, dynamic_boundaries=records)))


def test_literal_entry_adds_both_targets_and_preserves_real_run_name(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    graph = build_dependency_graph(tmp_path, paths)
    assert OWNER in graph['dynamic_uncertainty']
    _write(tmp_path, [record])
    graph = apply_dynamic_boundaries(tmp_path, paths, graph)
    assert OWNER not in graph['dynamic_uncertainty']
    assert graph['dependencies'][OWNER] == sorted([PACKAGE, ENTRY])
    assert graph['resolved_dynamic_dependencies'] == {'entry-v1': sorted([PACKAGE, ENTRY])}


@pytest.mark.parametrize('fault', ['module', 'source', 'symbol', 'missing', 'drift',
                                   'owner-drift', 'test-drift', 'run-name', 'narrow', 'extra'])
def test_inexact_declaration_fails_closed(tmp_path: Path, fault: str) -> None:
    paths, record = _setup(tmp_path)
    if fault == 'module':
        record['targets'][0]['module'] = 'other'
    elif fault == 'source':
        record['targets'][0]['path'] = ENTRY
    elif fault == 'symbol':
        record['targets'][0]['symbol'] = 'missing'
    elif fault == 'missing':
        (tmp_path / ENTRY).unlink()
    elif fault == 'drift':
        (tmp_path / ENTRY).write_text('raise SystemExit(1)\n')
    elif fault == 'owner-drift':
        (tmp_path / OWNER).write_text('import runpy\nrunpy.run_module("other")\n')
    elif fault == 'test-drift':
        (tmp_path / TEST).write_text('')
    elif fault == 'run-name':
        record['parameters']['run_name'] = 'other'
    elif fault == 'narrow':
        record['targets'].pop()
    else:
        record['targets'].append(record['targets'][0].copy())
    _write(tmp_path, [record])
    graph = build_dependency_graph(tmp_path, paths)
    graph = apply_dynamic_boundaries(tmp_path, paths, graph)
    assert OWNER in graph['errors']
    assert OWNER in graph['dynamic_uncertainty']


def test_additional_undeclared_operation_cannot_disappear(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    owner = tmp_path / OWNER
    owner.write_text(owner.read_text() + '\ndef other():\n    eval("3")\n')
    record['owner_sha256'] = hashlib.sha256(owner.read_bytes()).hexdigest()
    _write(tmp_path, [record])
    graph = apply_dynamic_boundaries(tmp_path, paths, build_dependency_graph(tmp_path, paths))
    assert graph['dynamic_uncertainty'][OWNER]


def test_declared_edges_participate_in_atomic_cycle_detection(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    _write(tmp_path, [record])
    graph = apply_dynamic_boundaries(tmp_path, paths, build_dependency_graph(tmp_path, paths))
    graph['dependencies'][ENTRY] = [OWNER]
    cohorts = [dict(id='owner', members=[OWNER]), dict(id='target', members=[ENTRY])]
    assert find_cross_cohort_cycles(cohorts, graph['dependencies']) == {
        'owner': ['owner', 'target'], 'target': ['owner', 'target']}


def test_resolved_evidence_is_deterministic(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    _write(tmp_path, [record])
    first = apply_dynamic_boundaries(tmp_path, paths, build_dependency_graph(tmp_path, paths))
    record['targets'].reverse()
    _write(tmp_path, [record])
    second = apply_dynamic_boundaries(tmp_path, paths, build_dependency_graph(tmp_path, paths))
    assert first['resolved_dynamic_dependencies'] == second['resolved_dynamic_dependencies']


def test_history_refuses_removal_narrowing_and_unwitnessed_replacement(tmp_path: Path) -> None:
    _, record = _setup(tmp_path)
    old: dict = dict(dynamic_schema=SCHEMA, dynamic_boundaries=[record])
    validate_dynamic_transition({}, old)
    for new in ({}, dict(dynamic_schema=SCHEMA, dynamic_boundaries=[])):
        with pytest.raises(ValueError):
            validate_dynamic_transition(old, new)
    changed = copy.deepcopy(old)
    changed['dynamic_boundaries'][0]['targets'].pop()
    with pytest.raises(ValueError, match='append-only'):
        validate_dynamic_transition(old, changed)
    successor = dict(record, id='entry-v2', supersedes='entry-v1')
    with pytest.raises(ValueError, match='changed owner and test'):
        validate_dynamic_transition(old, dict(dynamic_schema=SCHEMA,
                                              dynamic_boundaries=[record, successor]))


@pytest.mark.parametrize('evidence', ['owner_sha256', 'test_sha256'])
def test_replacement_requires_both_changed_commitments(tmp_path: Path, evidence: str) -> None:
    _, record = _setup(tmp_path)
    old = dict(dynamic_schema=SCHEMA, dynamic_boundaries=[record])
    successor = dict(record, id='entry-v2', supersedes=record['id'])
    successor[evidence] = hashlib.sha256(b'new semantic evidence').hexdigest()
    with pytest.raises(ValueError, match='changed owner and test'):
        validate_dynamic_transition(old, dict(dynamic_schema=SCHEMA,
                                              dynamic_boundaries=[record, successor]))


def test_semantic_successor_preserves_published_prefix(tmp_path: Path) -> None:
    _, record = _setup(tmp_path)
    old = dict(dynamic_schema=SCHEMA, dynamic_boundaries=[record])
    successor = dict(record, id='entry-v2', supersedes=record['id'],
                     owner_sha256=hashlib.sha256(b'changed owner').hexdigest(),
                     test_sha256=hashlib.sha256(b'changed assertions').hexdigest())
    new: dict = dict(dynamic_schema=SCHEMA, dynamic_boundaries=[record, successor])
    validate_dynamic_transition(old, new)
    rewritten = copy.deepcopy(new)
    rewritten['dynamic_boundaries'][0]['targets'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='append-only'):
        validate_dynamic_transition(old, rewritten)


def test_residual_target_cannot_lend_governance(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    _write(tmp_path, [record])
    cohort = dict(id='entry', root='test_support', governing_profile='clean_test_support',
                  members=[OWNER], admission='admitted', rationale='module entry')
    check = dict(status='passed', paths=[OWNER], analyzed_paths=[OWNER], checks={
        name: dict(status='passed', completed=True, findings=[])
        for name in ('ruff', 'mypy', 'file_length')})
    refused = evaluate_cohorts([cohort], {'test_support': check}, tmp_path, paths, [])
    assert refused['regressions'] == ['entry']
    assert refused['cohort_results']['entry']['ungoverned_dependencies'] == sorted([PACKAGE, ENTRY])
    accepted = evaluate_cohorts([cohort], {'test_support': check}, tmp_path, paths, [PACKAGE, ENTRY])
    assert accepted['regressions'] == []
    assert accepted['enforced']['test_support'] == [OWNER]


@pytest.mark.parametrize('fault', [None, 'guard', 'domain', 'target-symbol', 'target-source'])
def test_guarded_symbol_recipe_independently_checks_domain_and_source(tmp_path: Path, fault: str | None) -> None:
    paths, record = _setup(tmp_path)
    source = '''import importlib
from ci.domain import PYTHON_TARGETS
class ExecutorEvidenceError(ValueError): pass
def _resolve_symbol(module_name: str, symbol: str):
    if (module_name, symbol) not in PYTHON_TARGETS:
        raise ExecutorEvidenceError("registered symbol outside closed resolver domain")
    value = importlib.import_module(module_name)
    for part in symbol.split("."):
        value = getattr(value, part)
    return value
'''
    if fault == 'guard':
        source = source.replace('not in PYTHON_TARGETS', 'in PYTHON_TARGETS')
    (tmp_path / OWNER).write_text(source)
    domain = 'tools/ci/domain.py'
    target = 'tools/target.py'
    (tmp_path / domain).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / domain).write_text('PYTHON_TARGETS = (("target", "run"),)\n')
    (tmp_path / target).write_text('def run(): return 1\n')
    paths += [domain, target]
    op = dynamic_operations(ast.parse(source))[0]
    digest = lambda p: hashlib.sha256((tmp_path / p).read_bytes()).hexdigest()
    record.update(owner_sha256=digest(OWNER), kind=op['kind'], symbol=op['symbol'],
                  fingerprint=op['fingerprint'], recipe='guarded_symbol_import',
                  parameters=dict(domain_path=domain, domain_sha256=digest(domain), domain_module='ci.domain'),
                  targets=[dict(module='target', symbol='run', path=target, sha256=digest(target))])
    if fault == 'domain':
        (tmp_path / domain).write_text('PYTHON_TARGETS = (("target", "other"),)\n')
    elif fault == 'target-symbol':
        record['targets'][0]['symbol'] = 'other'
    elif fault == 'target-source':
        record['targets'][0]['path'] = ENTRY
    _write(tmp_path, [record])
    graph = build_dependency_graph(tmp_path, paths)
    if fault:
        assert OWNER in graph['errors']
        assert OWNER in graph['dynamic_uncertainty']
    else:
        assert OWNER not in graph['errors']
        assert OWNER not in graph['dynamic_uncertainty']
        assert target in graph['dependencies'][OWNER]
        assert domain in graph['dependencies'][OWNER]


@pytest.mark.parametrize('pending', [False, True])
def test_dynamic_same_root_cycle_admits_only_as_complete_atomic_group(tmp_path: Path, pending: bool) -> None:
    paths, record = _setup(tmp_path)
    new_package = 'src/test/support/python/sample/__init__.py'
    new_entry = 'src/test/support/python/sample/__main__.py'
    for old, new in ((PACKAGE, new_package), (ENTRY, new_entry)):
        dest = tmp_path / new
        dest.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / old).rename(dest)
        paths.remove(old)
        paths.append(new)
        target = next(t for t in record['targets'] if t['path'] == old)
        target['path'] = new
    (tmp_path / new_entry).write_text('import entry\n')
    record['targets'][1]['sha256'] = hashlib.sha256((tmp_path / new_entry).read_bytes()).hexdigest()
    _write(tmp_path, [record])
    members = [OWNER, new_package, new_entry]
    cohorts = [dict(id=str(i), root='test_support', governing_profile='clean_test_support',
                    members=[path], admission='pending' if pending and i == 0 else 'admitted',
                    rationale='atomic dynamic fixture') for i, path in enumerate(members)]
    check = dict(status='passed', paths=members, analyzed_paths=members, checks={
        name: dict(status='passed', completed=True, findings=[])
        for name in ('ruff', 'mypy', 'file_length')})
    result = evaluate_cohorts(cohorts, {'test_support': check}, tmp_path, paths, [])
    if pending:
        assert OWNER not in result['enforced']['test_support']
        assert new_entry not in result['enforced']['test_support']
        assert result['regressions']
    else:
        assert result['enforced']['test_support'] == sorted(members)
        assert result['regressions'] == []


@pytest.mark.parametrize("test_source", ["def test_unrelated(): pass\n",
                                        "import sample\ndef test_target_only(): pass\n"])
def test_unrelated_pinned_test_cannot_witness_owner(tmp_path: Path, test_source: str) -> None:
    paths, record = _setup(tmp_path)
    (tmp_path / TEST).write_text(test_source)
    record["test_sha256"] = hashlib.sha256((tmp_path / TEST).read_bytes()).hexdigest()
    _write(tmp_path, [record])
    graph = build_dependency_graph(tmp_path, paths)
    assert "statically depend" in graph["errors"][OWNER]
    assert OWNER in graph["dynamic_uncertainty"]


def test_unit_owner_can_witness_its_own_dynamic_operation(tmp_path: Path) -> None:
    paths, record = _setup(tmp_path)
    source = (tmp_path / OWNER).read_bytes()
    (tmp_path / TEST).write_bytes(source)
    record.update(owner=TEST, test_sha256=hashlib.sha256(source).hexdigest())
    _write(tmp_path, [record])
    graph = build_dependency_graph(tmp_path, paths)
    assert TEST not in graph["errors"]
    assert TEST not in graph["dynamic_uncertainty"]


def test_current_coverage_owners_resolve_every_declared_operation() -> None:
    root = Path(__file__).resolve().parents[6]
    inventory = json.loads((root / 'tools/ci/python_retention_inventory.json').read_bytes())
    paths = [entry['path'] for entry in inventory['files']]
    graph = build_dependency_graph(root, paths)
    records = active_boundaries(inventory)
    for filename, count in (
        ('coverage_json_export.unit.test.py', 6),
        ('test_runner_coverage_child.unit.test.py', 1),
        ('test_runner_coverage_child_export.unit.test.py', 1),
        ('test_runner_coverage_capability.unit.test.py', 2),
    ):
        owner = 'src/test/unit/python/tools/' + filename
        declared = [record for record in records if record['owner'] == owner]
        assert len(declared) == count
        assert owner not in graph['errors'], graph['errors'].get(owner)
        assert owner not in graph['dynamic_uncertainty']
        assert len(graph['dynamic_operations'][owner]) == count
        for record in declared:
            assert record['id'] in graph['resolved_dynamic_dependencies']
