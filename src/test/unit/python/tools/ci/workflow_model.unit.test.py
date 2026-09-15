"""The restricted workflow YAML reader must be correct or refuse to answer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_CI = ROOT / "tools"
if str(TOOLS_CI) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI))

from ci.workflow_model import (  # noqa: E402
    Workflow,
    WorkflowParseError,
    load_workflow,
    load_workflows,
    parse_yaml,
)

WORKFLOW_DIR = ROOT / ".github/workflows"


def test_parses_nested_mappings_sequences_and_scalars() -> None:
    document = parse_yaml(
        "name: example\n"
        "on:\n"
        "  pull_request:\n"
        "    branches: [staging]\n"
        "    types: [opened, synchronize]\n"
        "  workflow_dispatch:\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  build:\n"
        "    timeout-minutes: 10\n"
        "    steps:\n"
        "      - name: One\n"
        "        uses: actions/checkout@abc\n"
        "        with:\n"
        "          persist-credentials: false\n"
        "      - name: Two\n"
        "        run: echo hi\n"
    )

    assert document["name"] == "example"
    assert document["on"]["pull_request"]["branches"] == ["staging"]
    assert document["on"]["pull_request"]["types"] == ["opened", "synchronize"]
    assert document["on"]["workflow_dispatch"] is None
    assert document["permissions"] == {"contents": "read"}
    assert document["jobs"]["build"]["timeout-minutes"] == 10
    steps = document["jobs"]["build"]["steps"]
    assert steps[0]["with"]["persist-credentials"] is False
    assert steps[1]["run"] == "echo hi"


def test_block_scalars_keep_their_body_verbatim() -> None:
    document = parse_yaml(
        "steps:\n"
        "  - run: |\n"
        "      first --flag \\\n"
        "        second\n"
        "      # not a comment inside a block scalar\n"
        "  - run: echo tail\n"
    )

    assert document["steps"][0]["run"] == (
        "first --flag \\\n  second\n# not a comment inside a block scalar"
    )
    assert document["steps"][1]["run"] == "echo tail"


def test_comments_are_stripped_only_outside_quotes() -> None:
    document = parse_yaml(
        "# leading comment\n"
        "uses: actions/checkout@abc # v7.0.1\n"
        'title: "a # b"\n'
        "expression: ${{ inputs.value }}\n"
    )

    assert document["uses"] == "actions/checkout@abc"
    assert document["title"] == "a # b"
    assert document["expression"] == "${{ inputs.value }}"


def test_scalar_forms() -> None:
    document = parse_yaml(
        "flag_true: true\n"
        "flag_false: false\n"
        "count: -3\n"
        "empty:\n"
        "explicit_null: null\n"
        'version: "3.13"\n'
        "single: 'quoted'\n"
        "empty_list: []\n"
    )

    assert document["flag_true"] is True
    assert document["flag_false"] is False
    assert document["count"] == -3
    assert document["empty"] is None
    assert document["explicit_null"] is None
    assert document["version"] == "3.13"
    assert document["single"] == "quoted"
    assert document["empty_list"] == []


@pytest.mark.parametrize(
    "source",
    [
        "key:\n\tnested: 1\n",
        "anchor: &base\n  value: 1\n",
        "alias: *base\n",
        "flow: {a: 1}\n",
        "folded: >\n  text\n",
        "tagged: !!str 1\n",
        "duplicate: 1\nduplicate: 2\n",
        "---\nkey: 1\n",
        "list:\n  -\n",
        "map:\n  key: 1\n    misaligned: 2\n",
    ],
)
def test_unsupported_constructs_fail_closed(source: str) -> None:
    with pytest.raises(WorkflowParseError):
        parse_yaml(source)


def test_reader_parses_every_real_workflow() -> None:
    workflows = load_workflows(WORKFLOW_DIR)

    assert {workflow.path.name for workflow in workflows} == {
        "repomap-static-analysis.yml",
        "repomap-unit-tests.yml",
        "repomap-staging-gate.yml",
        "repomap-main-source-policy.yml",
        "repomap-main-system-gate.yml",
        "repomap-release-qualification.yml",
    }
    for workflow in workflows:
        assert isinstance(workflow, Workflow)
        assert workflow.name == workflow.path.stem
        assert workflow.triggers
        assert workflow.permissions
        assert workflow.jobs
        assert workflow.steps()

    release_workflow = next(w for w in workflows if w.path.name == "repomap-release-qualification.yml")
    assert set(release_workflow.jobs) == {
        "source-and-export-policy",
        "pre-review-static",
        "unit-tests",
        "staging-integration-gate",
        "main-system-gate",
        "codeql",
        "sbom-security",
    }


def test_accessors_expose_commands_and_actions() -> None:
    workflow = load_workflow(WORKFLOW_DIR / "repomap-staging-gate.yml")

    commands = workflow.run_commands()
    assert any("python3 tools/run_tests.py" in command for command in commands)
    assert any("--pg-container-port 55433" in command for command in commands)
    for action in workflow.action_uses():
        assert "@" in action


def test_non_mapping_document_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(WorkflowParseError):
        load_workflow(path)
