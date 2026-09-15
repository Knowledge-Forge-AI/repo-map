"""Conservative static zunit raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.base import slug
from repomap_kg.extractors.shell.zunit_helpers import (
    EXTRACTOR,
    bounded_name_metadata,
    is_dynamic_value,
    redaction_for_value,
    secret_observations_from_metadata,
    tokenize_line,
    zunit_metadata,
    zunit_observation,
)
from repomap_kg.extractors.shell.zunit_observations import (
    ASSERTION_SHAPES,
    ASSIGNMENT_RE,
    assertion_observations,
    assignment_observations,
    command_under_test_observations,
    dynamic_assertion_observations,
    helper_observations,
    load_fixture_observations,
    mock_or_stub_observations,
    skip_or_todo_observation,
    strip_inline_comment,
)
from repomap_kg.observations.raw import RawObservation

DESCRIBE_RE = re.compile(r"^\s*describe\s+(?P<quote>['\"])(?P<name>.*?)\1\s*$")
TEST_RE = re.compile(r"^\s*test\s+(?P<quote>['\"])(?P<name>.*?)\1\s*\{")
HOOK_RE = re.compile(
    r"^\s*(?P<name>setup|teardown|before_each|after_each)\s*\(\)\s*\{"
)
FOR_RE = re.compile(
    r"^\s*for\s+(?P<parameter>[A-Za-z_][A-Za-z0-9_]*)\s+in\s+"
    r"(?P<values>.*?)\s*;?\s*do\s*$"
)
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


@dataclass
class PendingHeredoc:
    delimiter: str
    tab_stripping: bool


def is_zunit_file_path(path: Path) -> bool:
    return path.suffix == ".zunit"


def extract_zunit_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = [zunit_file_observation(relative_path)]
    pending_heredoc: PendingHeredoc | None = None
    current_suite: str | None = None
    current_suite_redacted = False
    current_test: str | None = None
    current_hook: str | None = None
    fixture_variables: dict[str, str] = {}

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if pending_heredoc is not None:
            terminator = (
                raw_line.lstrip("\t").strip()
                if pending_heredoc.tab_stripping
                else stripped
            )
            if terminator == pending_heredoc.delimiter:
                pending_heredoc = None
            continue
        if not stripped or stripped.startswith("#"):
            continue

        line = strip_inline_comment(raw_line).rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        heredoc_match = HEREDOC_RE.search(line)
        if heredoc_match is not None:
            pending_heredoc = PendingHeredoc(
                delimiter=heredoc_match.group(2),
                tab_stripping="<<-" in line,
            )

        if stripped[0] in {"'", '"'}:
            continue

        for_match = FOR_RE.match(stripped)
        if for_match is not None:
            observations.append(
                dynamic_test_observation(
                    relative_path,
                    line_number,
                    dynamic_reason="generated_loop",
                )
            )
            observations.append(
                parameterized_case_observation(relative_path, line_number, stripped)
            )
            continue

        if stripped in {"}", "done"}:
            current_test = None
            current_hook = None
            continue

        suite = suite_observation(relative_path, line_number, line)
        if suite is not None:
            observations.append(suite)
            observations.extend(
                secret_observations_from_metadata(
                    relative_path,
                    line_number,
                    suite.metadata,
                    secret_source="suite_name",
                )
            )
            current_suite = suite.metadata.get("suite_name")
            current_suite_redacted = bool(suite.metadata.get("suite_name_redacted"))
            continue

        hook = hook_observation(relative_path, line_number, line)
        if hook is not None:
            observations.append(hook)
            current_hook = hook.metadata["hook_name"]
            current_test = None
            continue

        test_case, test_name, dynamic_test = test_case_observations(
            relative_path,
            line_number,
            line,
            current_suite=current_suite,
            current_suite_redacted=current_suite_redacted,
        )
        if test_case is not None:
            observations.append(test_case)
            observations.extend(
                secret_observations_from_metadata(
                    relative_path,
                    line_number,
                    test_case.metadata,
                    secret_source="test_name",
                )
            )
            current_test = test_case.name
            current_hook = None
        if test_name is not None:
            observations.append(test_name)
        if dynamic_test is not None:
            observations.append(dynamic_test)
            current_test = "[dynamic]"
            current_hook = None
            continue

        if stripped.startswith("eval "):
            observations.append(
                dynamic_test_observation(
                    relative_path,
                    line_number,
                    dynamic_reason="eval_generated",
                )
            )
            continue

        tokens = tokenize_line(stripped)
        if not tokens:
            continue

        assignment = assignment_observations(
            relative_path,
            line_number,
            stripped,
            fixture_variables=fixture_variables,
        )
        if assignment:
            observations.extend(assignment)
            continue

        helper = helper_observations(relative_path, line_number, tokens)
        if helper:
            observations.extend(helper)
            continue

        fixture = load_fixture_observations(relative_path, line_number, tokens)
        if fixture:
            observations.extend(fixture)
            continue

        mock_or_stub = mock_or_stub_observations(relative_path, line_number, tokens)
        if mock_or_stub:
            observations.extend(mock_or_stub)
            continue

        skip_or_todo = skip_or_todo_observation(relative_path, line_number, tokens)
        if skip_or_todo:
            observations.extend(skip_or_todo)
            continue

        assertion = assertion_observations(
            relative_path,
            line_number,
            tokens,
            current_test=current_test,
        )
        if assertion:
            observations.extend(assertion)
            continue

        dynamic_assertion = dynamic_assertion_observations(
            relative_path,
            line_number,
            tokens,
            current_test=current_test,
        )
        if dynamic_assertion:
            observations.extend(dynamic_assertion)
            continue

        command = command_under_test_observations(
            relative_path,
            line_number,
            tokens,
            current_test=current_test,
            current_hook=current_hook,
            fixture_variables=fixture_variables,
        )
        if command:
            observations.extend(command)

    return tuple(observations)


def zunit_file_observation(relative_path: str) -> RawObservation:
    metadata = zunit_metadata(
        {
            "file_type": "test",
            "classification_evidence": classification_evidence(relative_path),
            "parser": "stdlib-static-scanner",
        }
    )
    return RawObservation(
        kind="zunit.file",
        source_id=f"{relative_path}#zunit-file",
        path=relative_path,
        name=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def classification_evidence(relative_path: str) -> list[str]:
    evidence: list[str] = []
    path = Path(relative_path)
    if path.suffix == ".zunit":
        evidence.append("extension")
    if "zunit" in path.parts or ".zunit" in path.parts:
        evidence.append("zunit_path")
    return evidence or ["unknown"]


def suite_observation(
    relative_path: str,
    line_number: int,
    line: str,
) -> RawObservation | None:
    match = DESCRIBE_RE.match(line)
    if match is None:
        return None
    suite_name = match.group("name")
    stored_name, redaction_metadata = bounded_name_metadata(suite_name, "suite_name")
    metadata = zunit_metadata(
        {
            "suite_kind": "describe",
            "body_modeled": False,
            "suite_executed": False,
            "tests_executed": False,
            **redaction_metadata,
        }
    )
    return RawObservation(
        kind="zunit.suite",
        source_id=f"{relative_path}#zunit-suite:{line_number}:{slug(stored_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=stored_name,
        confidence=(
            "extracted" if metadata["suite_name_kind"] == "static" else "heuristic"
        ),
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def test_case_observations(
    relative_path: str,
    line_number: int,
    line: str,
    *,
    current_suite: str | None,
    current_suite_redacted: bool,
) -> tuple[RawObservation | None, RawObservation | None, RawObservation | None]:
    match = TEST_RE.match(line)
    if match is None:
        if line.lstrip().startswith("test "):
            return (
                None,
                None,
                dynamic_test_observation(
                    relative_path,
                    line_number,
                    dynamic_reason="unknown",
                ),
            )
        return (None, None, None)

    test_name_value = match.group("name")
    if is_dynamic_value(test_name_value):
        return (
            None,
            None,
            dynamic_test_observation(
                relative_path,
                line_number,
                dynamic_reason="dynamic_test_name",
            ),
        )

    stored_name, redaction_metadata = bounded_name_metadata(test_name_value, "test_name")
    metadata: dict[str, Any] = {
        "syntax": "test_block",
        "body_modeled": False,
        "test_intent": True,
        "test_executed": False,
        "tests_executed": False,
        **redaction_metadata,
    }
    if current_suite is not None:
        metadata["enclosing_suite"] = current_suite
        metadata["enclosing_suite_redacted"] = current_suite_redacted
    test_case = RawObservation(
        kind="zunit.test_case",
        source_id=f"{relative_path}#zunit-test:{line_number}:{slug(stored_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=stored_name,
        confidence=(
            "extracted" if metadata["test_name_kind"] == "static" else "heuristic"
        ),
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zunit_metadata(metadata),
    )

    test_name_metadata: dict[str, Any] = {
        "associated_test_source_id": test_case.source_id,
        "test_executed": False,
    }
    name_kind = redaction_metadata["test_name_kind"]
    test_name_metadata["name_kind"] = name_kind
    if name_kind == "static":
        test_name_metadata["test_name"] = test_name_value
        test_name_metadata["raw_name_stored"] = True
    else:
        test_name_metadata["raw_name_stored"] = False
        test_name_metadata["test_name_redacted"] = True
        test_name_metadata["redaction_reason"] = redaction_metadata.get(
            "redaction_reason"
        )
    test_name = RawObservation(
        kind="zunit.test_name",
        source_id=f"{test_case.source_id}:name",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=stored_name,
        confidence=test_case.confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zunit_metadata(test_name_metadata),
    )
    return (test_case, test_name, None)


def dynamic_test_observation(
    relative_path: str,
    line_number: int,
    *,
    dynamic_reason: str,
) -> RawObservation:
    return RawObservation(
        kind="zunit.dynamic_test",
        source_id=f"{relative_path}#zunit-dynamic-test:{line_number}:{slug(dynamic_reason)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="[dynamic]",
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zunit_metadata(
            {
                "resolution": "dynamic",
                "dynamic_reason": dynamic_reason,
                "test_count_known": False,
                "generated_tests_executed": False,
            }
        ),
    )


def parameterized_case_observation(
    relative_path: str,
    line_number: int,
    line: str,
) -> RawObservation:
    match = FOR_RE.match(line)
    parameter_name = match.group("parameter") if match is not None else None
    raw_values = match.group("values") if match is not None else ""
    value_tokens = tokenize_line(raw_values)
    static_values = [
        value
        for value in value_tokens
        if not is_dynamic_value(value) and redaction_for_value(value) is None
    ]
    dynamic_value_count = len(value_tokens) - len(static_values)
    return zunit_observation(
        "zunit.parameterized_case",
        relative_path,
        line_number,
        name=parameter_name or "[dynamic]",
        metadata={
            "parameter_name": parameter_name,
            "static_value_count": len(static_values),
            "dynamic_value_count": max(dynamic_value_count, 0),
            "generated_test_count_known": False,
            "parameterized_cases_executed": False,
            "test_count_known": False,
        },
        confidence="heuristic",
    )


def hook_observation(
    relative_path: str,
    line_number: int,
    line: str,
) -> RawObservation | None:
    match = HOOK_RE.match(line)
    if match is None:
        return None
    hook_name = match.group("name")
    return zunit_observation(
        f"zunit.{hook_name}",
        relative_path,
        line_number,
        name=hook_name,
        metadata={
            "hook_name": hook_name,
            "hook_kind": hook_name,
            "hook_scope": "file",
            "body_modeled": False,
            "hook_executed": False,
            "tests_executed": False,
        },
    )
