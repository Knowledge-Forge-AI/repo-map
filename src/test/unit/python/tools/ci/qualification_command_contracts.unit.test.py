"""Qualification command counterexamples stay within their owning job."""
from pathlib import Path

import pytest

from ci.qualification_command_contracts import (
    _extract_commands_from_script,
    _validate_downstream_dependencies, _validate_main_system_gate_ordering,
    _validate_staging_runner_tokens,
)
from ci.workflow_model import Workflow, parse_yaml

STAGING = ("python3 tools/run_tests.py --suite staging --hygiene-profile exhaustive "
           "--declared-complete-gates 1 --operator-attest-exclusive "
           "--operator-attest-pressure-degradation --pg-container-port 55433 "
           "--sandbox --report --report-dir 'report with spaces'")
BIND = '''CANDIDATE_SHA="$(git rev-parse HEAD)"
CANDIDATE_TREE="$(git rev-parse 'HEAD^{tree}')"
CANDIDATE_BASE_PARENT="$(git rev-parse 'HEAD^1')"
CANDIDATE_HEAD_PARENT="$(git rev-parse 'HEAD^2')"
export CANDIDATE_SHA CANDIDATE_TREE CANDIDATE_BASE_PARENT CANDIDATE_HEAD_PARENT
{
echo "CANDIDATE_SHA=${CANDIDATE_SHA}"
echo "CANDIDATE_TREE=${CANDIDATE_TREE}"
echo "CANDIDATE_BASE_PARENT=${CANDIDATE_BASE_PARENT}"
echo "CANDIDATE_HEAD_PARENT=${CANDIDATE_HEAD_PARENT}"
} >> "${GITHUB_ENV}"
python3 -c "
import json, os, sys
req = {'schema': 'repomap-ci-gate-request-v1', 'gate_kind': 'main-system',
       'base_sha': os.environ['CANDIDATE_BASE_PARENT'],
       'head_sha': os.environ['CANDIDATE_HEAD_PARENT']}
with open('${RUNNER_TEMP}/gate-request.json', 'w', encoding='utf-8') as f:
    json.dump(req, f)
"
'''
SYSTEM = ("python3 tools/run_tests.py --suite system "
          '--candidate-sha "${CANDIDATE_SHA}" --candidate-tree "${CANDIDATE_TREE}" '
          '--candidate-base-parent "${CANDIDATE_BASE_PARENT}" '
          '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}" '
          '--gate-request-json "${RUNNER_TEMP}/gate-request.json"')


def _workflow(steps, **other_jobs):
    return Workflow(Path("release.yml"), {"jobs": {
        "staging-integration-gate": {"needs": ["source-and-export-policy"], "steps": steps},
        **other_jobs,
    }})


@pytest.mark.parametrize("command", [
    "echo " + STAGING,
    "printf '%s' " + STAGING,
    STAGING + "; " + STAGING,
    STAGING + " && " + STAGING,
    STAGING.replace("--report --report-dir", "--report-dir"),
    STAGING.replace("--report-dir 'report with spaces'", "--report-dir"),
    STAGING.replace("--report-dir 'report with spaces'", "--report-dir --unknown"),
    STAGING.replace("--report-dir 'report with spaces'", "--report-dir=''"),
    STAGING + " --suite unit",
    STAGING.replace("--report ", "--report=false "),
    STAGING.replace("--suite staging", "-- --suite staging"),
])
def test_staging_invocation_counterexamples(command):
    assert _validate_staging_runner_tokens(_workflow([{"run": command}]), "staging-integration-gate")


def test_quoted_values_continuations_and_shell_lists_are_preserved():
    script = "echo starting; " + STAGING.replace(" --", " \\\n --") + " && echo finished"
    assert _validate_staging_runner_tokens(_workflow([{"run": script}]), "staging-integration-gate") == []


def test_other_job_cannot_supply_missing_staging_flags():
    workflow = _workflow([{"run": STAGING.replace("--report ", "")}],
                         other={"steps": [{"run": "echo --report"}]})
    assert any("--report flag" in error for error in _validate_staging_runner_tokens(workflow, "staging-integration-gate"))


def test_multiline_quoted_code_does_not_supply_a_shell_runner():
    script = 'python3 -c "\n' + STAGING.replace("'report with spaces'", "report") + '\n"\n'
    assert _validate_staging_runner_tokens(_workflow([{"run": script}]), "staging-integration-gate")
    assert _validate_staging_runner_tokens(_workflow([{"run": script + STAGING}]), "staging-integration-gate") == []


def test_multiline_quotes_keep_comments_and_command_boundaries():
    script = 'echo "first\n# quoted text; still one argument\nlast" # comment\n' + STAGING
    commands = _extract_commands_from_script(script)
    assert commands[0] == ["echo", "first\n# quoted text; still one argument\nlast"]
    assert len(commands) == 2
    assert _validate_staging_runner_tokens(_workflow([{"run": script}]), "staging-integration-gate") == []


def test_unterminated_multiline_quote_refuses_qualification():
    script = STAGING + '\necho "unterminated\n' + STAGING
    assert _validate_staging_runner_tokens(_workflow([{"run": script}]), "staging-integration-gate") == [
        "release.yml: qualification shell command cannot be parsed",
    ]


@pytest.mark.parametrize("removed", [0, 1, 2])
def test_main_system_requires_each_owned_step(removed):
    steps = [{"run": BIND}, {"uses": "actions/setup-python@fixture"},
             {"run": "python3 tools/run_tests.py \\\n --suite system"}]
    steps.pop(removed)
    workflow = _workflow([], **{"main-system-gate": {"steps": steps}})
    assert _validate_main_system_gate_ordering(workflow)


def test_bind_id_alone_cannot_replace_merge_parent_validation():
    steps = [{"id": "bind", "run": "echo bound"}, {"uses": "actions/setup-python@fixture"},
             {"run": "python3 tools/run_tests.py --suite system"}]
    assert _validate_main_system_gate_ordering(_workflow([], **{"main-system-gate": {"steps": steps}}))


def _main_workflow(binding=BIND, runner=SYSTEM, before=()):
    steps = [*before, {"run": binding}, {"uses": "actions/setup-python@fixture"}, {"run": runner}]
    return _workflow([], **{"main-system-gate": {"steps": steps}})


def test_actual_main_system_binding_constructs_and_consumes_bound_request():
    assert _validate_main_system_gate_ordering(_main_workflow()) == []


@pytest.mark.parametrize("binding", [
    'echo "CANDIDATE_SHA= HEAD^{tree} HEAD^1 HEAD^2"',
    '# CANDIDATE_SHA= HEAD^{tree} HEAD^1 HEAD^2',
    BIND.replace('"$(git rev-parse HEAD)"', '"fake"'),
    BIND.replace('CANDIDATE_HEAD_PARENT="$(git rev-parse \'HEAD^2\')"\n', ''),
    BIND.replace('$(git rev-parse HEAD)', '$(echo git rev-parse HEAD)'),
    BIND.replace('CANDIDATE_SHA="$(git rev-parse HEAD)"', "CANDIDATE_SHA='$(git rev-parse HEAD)'"),
    BIND.replace('CANDIDATE_SHA="$(git rev-parse HEAD)"', '"CANDIDATE_SHA=$(git rev-parse HEAD)"'),
    BIND.replace('CANDIDATE_SHA="$(git rev-parse HEAD)"', '\'CANDIDATE_SHA=$(git rev-parse HEAD)\''),
    BIND.replace('${GITHUB_ENV}', '${FAKE_ENV}'),
    BIND.replace("os.environ['CANDIDATE_HEAD_PARENT']", "'fake'"),
    BIND.replace('json.dump(req, f)', '# json.dump(req, f)\n    pass'),
    BIND.replace('with open(', "req['head_sha'] = 'fake'\nwith open("),
    BIND.replace('json.dump(req, f)', "req['head_sha'] = 'fake'\n    json.dump(req, f)"),
    BIND + 'CANDIDATE_SHA=fake\n',
])
def test_main_system_rejects_fabricated_or_incomplete_binding(binding):
    assert _validate_main_system_gate_ordering(_main_workflow(binding))


def test_main_system_rejects_assignment_after_expensive_setup():
    assert _validate_main_system_gate_ordering(_main_workflow(before=[{"run": "python3 -m pip install ."}]))


def test_main_system_rejects_literal_runner_identity():
    assert _validate_main_system_gate_ordering(_main_workflow(runner=SYSTEM.replace('${CANDIDATE_SHA}', 'fake')))


@pytest.mark.parametrize("needs", [None, "source-and-export-policy", ["unit-tests"],
                                   ["source-and-export-policy", "unit-tests"]])
def test_downstream_dependency_is_the_exact_binding_edge(needs):
    workflow = _workflow([], **{"unit-tests": {"needs": needs, "steps": []}})
    assert _validate_downstream_dependencies(workflow)


BIND_PRIVATE = '''{
echo "CANDIDATE_SHA=$(git rev-parse HEAD)"
echo "CANDIDATE_TREE=$(git rev-parse 'HEAD^{tree}')"
echo "CANDIDATE_BASE_PARENT=$(git rev-parse 'HEAD^1')"
echo "CANDIDATE_HEAD_PARENT=$(git rev-parse 'HEAD^2')"
} >> "${GITHUB_ENV}"
python3 -S -E "${RUNNER_TEMP}/gate_contract.py" verify \\
  --request-json "${RUNNER_TEMP}/gate-request.json" \\
  --candidate-sha "$(git rev-parse HEAD)" \\
  --candidate-tree "$(git rev-parse 'HEAD^{tree}')" \\
  --candidate-base-parent "$(git rev-parse 'HEAD^1')" \\
  --candidate-head-parent "$(git rev-parse 'HEAD^2')"
'''


def _private_workflow(binding=BIND_PRIVATE, runner=SYSTEM):
    steps = [{"run": binding}, {"uses": "actions/setup-python@fixture"}, {"run": runner}]
    return Workflow(Path("repomap-main-system-gate.yml"), {"jobs": {
        "repomap-main-system-gate": {"steps": steps},
    }})


def test_actual_public_and_private_system_workflows_accepted():
    assert _validate_main_system_gate_ordering(_main_workflow()) == []
    assert _validate_main_system_gate_ordering(_private_workflow(), "repomap-main-system-gate") == []
    real_path = Path(".github/workflows/repomap-main-system-gate.yml")
    if real_path.exists():
        real_wf = Workflow(real_path, parse_yaml(real_path.read_text()))
        assert _validate_main_system_gate_ordering(real_wf, "repomap-main-system-gate") == []


@pytest.mark.parametrize("binding", [
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo "CANDIDATE_SHA=$CANDIDATE_SHA"'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo CANDIDATE_SHA=${CANDIDATE_SHA}'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo CANDIDATE_SHA=$CANDIDATE_SHA'),
])
def test_main_system_accepts_maintained_expansions(binding):
    assert _validate_main_system_gate_ordering(_main_workflow(binding=binding)) == []


@pytest.mark.parametrize("runner", [
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha "$CANDIDATE_SHA"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha ${CANDIDATE_SHA}'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha $CANDIDATE_SHA'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha="${CANDIDATE_SHA}"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha="$CANDIDATE_SHA"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha=${CANDIDATE_SHA}'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha=$CANDIDATE_SHA'),
])
def test_main_system_runner_accepts_maintained_expansions(runner):
    assert _validate_main_system_gate_ordering(_main_workflow(runner=runner)) == []


@pytest.mark.parametrize("binding", [
    BIND_PRIVATE.replace('echo "CANDIDATE_SHA=$(git rev-parse HEAD)"', 'echo CANDIDATE_SHA=$(git rev-parse HEAD)'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha $(git rev-parse HEAD)'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha="$(git rev-parse HEAD)"'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha=$(git rev-parse HEAD)'),
])
def test_private_main_system_accepts_maintained_expansions(binding):
    assert _validate_main_system_gate_ordering(_private_workflow(binding=binding), "repomap-main-system-gate") == []


@pytest.mark.parametrize("binding", [
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', "echo 'CANDIDATE_SHA=${CANDIDATE_SHA}'"),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', "echo 'CANDIDATE_SHA=$CANDIDATE_SHA'"),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', "echo CANDIDATE_SHA='${CANDIDATE_SHA}'"),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', "echo CANDIDATE_SHA='$CANDIDATE_SHA'"),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', "'echo' 'CANDIDATE_SHA=${CANDIDATE_SHA}'"),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo "CANDIDATE_SHA=\\${CANDIDATE_SHA}"'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo "CANDIDATE_SHA=\\$CANDIDATE_SHA"'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo CANDIDATE_SHA=\\${CANDIDATE_SHA}'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo CANDIDATE_SHA=\\$CANDIDATE_SHA'),
    BIND.replace('echo "CANDIDATE_SHA=${CANDIDATE_SHA}"', 'echo "CANDIDATE_SHA=\'${CANDIDATE_SHA}\'"'),
    BIND.replace('CANDIDATE_SHA="$(git rev-parse HEAD)"', 'CANDIDATE_SHA="\\$(git rev-parse HEAD)"'),
    BIND.replace('CANDIDATE_SHA="$(git rev-parse HEAD)"', 'CANDIDATE_SHA=\\$(git rev-parse HEAD)'),
])
def test_main_system_rejects_single_quoted_and_escaped_binding(binding):
    assert _validate_main_system_gate_ordering(_main_workflow(binding=binding))


@pytest.mark.parametrize("runner", [
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', "--candidate-sha '${CANDIDATE_SHA}'"),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', "--candidate-sha '$CANDIDATE_SHA'"),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', "--candidate-sha='${CANDIDATE_SHA}'"),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', "--candidate-sha='$CANDIDATE_SHA'"),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', "'--candidate-sha=${CANDIDATE_SHA}'"),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha "\\${CANDIDATE_SHA}"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha "\\$CANDIDATE_SHA"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha \\${CANDIDATE_SHA}'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha \\$CANDIDATE_SHA'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha="\\${CANDIDATE_SHA}"'),
    SYSTEM.replace('--candidate-sha "${CANDIDATE_SHA}"', '--candidate-sha="\\$CANDIDATE_SHA"'),
])
def test_main_system_rejects_single_quoted_and_escaped_runner_candidate(runner):
    assert _validate_main_system_gate_ordering(_main_workflow(runner=runner))


@pytest.mark.parametrize("binding", [
    BIND_PRIVATE.replace('echo "CANDIDATE_SHA=$(git rev-parse HEAD)"', "echo 'CANDIDATE_SHA=$(git rev-parse HEAD)'"),
    BIND_PRIVATE.replace('echo "CANDIDATE_SHA=$(git rev-parse HEAD)"', "echo CANDIDATE_SHA='$(git rev-parse HEAD)'"),
    BIND_PRIVATE.replace('echo "CANDIDATE_SHA=$(git rev-parse HEAD)"', 'echo "CANDIDATE_SHA=\\$(git rev-parse HEAD)"'),
    BIND_PRIVATE.replace('echo "CANDIDATE_SHA=$(git rev-parse HEAD)"', 'echo CANDIDATE_SHA=\\$(git rev-parse HEAD)'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', "--candidate-sha '$(git rev-parse HEAD)'"),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', "--candidate-sha='$(git rev-parse HEAD)'"),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha "\\$(git rev-parse HEAD)"'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha \\$(git rev-parse HEAD)'),
    BIND_PRIVATE.replace('--candidate-sha "$(git rev-parse HEAD)"', '--candidate-sha="\\$(git rev-parse HEAD)"'),
])
def test_private_main_system_rejects_single_quoted_and_escaped(binding):
    assert _validate_main_system_gate_ordering(_private_workflow(binding=binding), "repomap-main-system-gate")


@pytest.mark.parametrize("binding", [
    BIND.replace('"${GITHUB_ENV}"', "'${GITHUB_ENV}'"),
    BIND.replace('"${GITHUB_ENV}"', "'$GITHUB_ENV'"),
    BIND.replace('} >> ', "} '>>' "),
    BIND.replace('} >> ', "'}' >> "),
])
def test_environment_persistence_requires_real_redirect_and_expansion(binding):
    assert _validate_main_system_gate_ordering(_main_workflow(binding=binding))


@pytest.mark.parametrize("runner", [
    SYSTEM.replace('"${RUNNER_TEMP}/gate-request.json"', "'${RUNNER_TEMP}/gate-request.json'"),
    SYSTEM.replace('"${RUNNER_TEMP}/gate-request.json"', "'$RUNNER_TEMP/gate-request.json'"),
])
def test_request_consumption_requires_expanded_path(runner):
    assert _validate_main_system_gate_ordering(_main_workflow(runner=runner))


def test_private_request_verification_requires_expanded_path():
    binding = BIND_PRIVATE.replace(
        '--request-json "${RUNNER_TEMP}/gate-request.json"',
        "--request-json '${RUNNER_TEMP}/gate-request.json'",
    )
    assert _validate_main_system_gate_ordering(_private_workflow(binding=binding), "repomap-main-system-gate")


def test_empty_double_quotes_remain_an_empty_argument():
    assert _extract_commands_from_script('echo ""') == [["echo", ""]]


def test_request_construction_rejects_a_literal_shell_code_argument():
    import shlex

    code = _extract_commands_from_script(BIND)[-1][2]
    literal_binding = BIND[:BIND.index('python3 -c')] + "python3 -c " + shlex.quote(code)
    assert _validate_main_system_gate_ordering(_main_workflow(binding=literal_binding))
