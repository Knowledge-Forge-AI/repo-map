"""Observation builders for conservative static ZUnit extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg.extractors.shell.zunit_helpers import (
    argument_summary_kind_for,
    assertion_family_for,
    assertion_mode_for,
    behavior_kind_for_mock,
    command_token_metadata,
    confidence_for_reason,
    confidence_for_target,
    confidence_for_value_kind,
    expectation_kind_for,
    expectation_matcher_for,
    expected_value_metadata,
    expected_value_token,
    fixture_metadata_from_argument,
    fixture_reference_observation,
    is_direct_command_token,
    is_dynamic_value,
    looks_like_fixture,
    reason_metadata,
    redaction_for_value,
    secret_like_observation,
    secret_observation_for_redacted_target,
    target_kind_for_command,
    target_path_metadata,
    tokenize_line,
    zunit_observation,
)
from repomap_kg.observations.raw import RawObservation


ASSIGNMENT_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.+?)\s*$"
)
ASSERTION_SHAPES: dict[str, dict[str, str]] = {
    "assert_success": {
        "family": "status",
        "mode": "success",
        "expectation_kind": "status",
        "matcher": "success",
    },
    "assert_failure": {
        "family": "status",
        "mode": "failure",
        "expectation_kind": "status",
        "matcher": "failure",
    },
    "assert_equal": {
        "family": "equality",
        "mode": "exact",
        "expectation_kind": "unknown",
        "matcher": "equals",
    },
    "assert_output": {
        "family": "output",
        "mode": "exact",
        "expectation_kind": "output",
        "matcher": "equals",
    },
    "refute_output": {
        "family": "output",
        "mode": "negated",
        "expectation_kind": "output",
        "matcher": "not_exists",
    },
    "assert_file_exists": {
        "family": "file",
        "mode": "exists",
        "expectation_kind": "file",
        "matcher": "exists",
    },
    "assert_dir_exists": {
        "family": "directory",
        "mode": "exists",
        "expectation_kind": "directory",
        "matcher": "exists",
    },
}
def assignment_observations(
    relative_path: str,
    line_number: int,
    line: str,
    *,
    fixture_variables: dict[str, str],
) -> list[RawObservation]:
    match = ASSIGNMENT_RE.match(line)
    if match is None:
        return []
    variable_name = match.group("name")
    raw_value = match.group("value").strip()
    tokens = tokenize_line(raw_value)
    value = tokens[0] if len(tokens) == 1 else raw_value.strip("'\"")
    observations: list[RawObservation] = []
    if "fixture" not in variable_name.lower() and not looks_like_fixture(value):
        return observations
    target_metadata = target_path_metadata(
        "fixture_path",
        value,
        relative_path,
    )
    if target_metadata["target_kind"] == "static":
        fixture_variables[variable_name] = target_metadata["fixture_path"]
    observations.append(
        fixture_reference_observation(
            relative_path,
            line_number,
            reference_kind="assignment",
            target_metadata=target_metadata,
        )
    )
    observations.extend(
        secret_observation_for_redacted_target(
            relative_path,
            line_number,
            target_metadata,
            secret_source="fixture_path",
        )
    )
    return observations


def helper_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
) -> list[RawObservation]:
    if len(tokens) < 2 or tokens[0] not in {"source", "load_helper"}:
        return []
    metadata = target_path_metadata("helper_path", tokens[1], relative_path)
    observations = [
        zunit_observation(
            "zunit.helper",
            relative_path,
            line_number,
            name=metadata.get("helper_path") or "[dynamic]",
            metadata={
                **metadata,
                "reference_kind": tokens[0],
                "helper_loaded": False,
                "file_read": False,
                "filesystem_checked": False,
            },
            confidence=confidence_for_target(metadata),
        )
    ]
    observations.extend(
        secret_observation_for_redacted_target(
            relative_path,
            line_number,
            metadata,
            secret_source="helper_path",
        )
    )
    return observations


def load_fixture_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
) -> list[RawObservation]:
    if len(tokens) < 2 or tokens[0] != "load_fixture":
        return []
    metadata = target_path_metadata("fixture_path", tokens[1], relative_path)
    observations = [
        fixture_reference_observation(
            relative_path,
            line_number,
            reference_kind="load_fixture",
            target_metadata=metadata,
        )
    ]
    observations.extend(
        secret_observation_for_redacted_target(
            relative_path,
            line_number,
            metadata,
            secret_source="fixture_path",
        )
    )
    return observations


def assertion_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    current_test: str | None,
) -> list[RawObservation]:
    if not tokens or tokens[0] not in ASSERTION_SHAPES:
        return []
    assertion_name = tokens[0]
    shape = ASSERTION_SHAPES[assertion_name]
    args = tokens[1:]
    family = assertion_family_for(assertion_name, args, shape["family"])
    mode = assertion_mode_for(assertion_name, args, shape["mode"])
    observations: list[RawObservation] = [
        zunit_observation(
            "zunit.assertion",
            relative_path,
            line_number,
            name=assertion_name,
            metadata={
                "assertion_name": assertion_name,
                "assertion_family": family,
                "mode": mode,
                "argument_count": len(args),
                "enclosing_test": current_test,
                "assertion_executed": False,
                "test_passed_known": False,
            },
        )
    ]
    expected_token = expected_value_token(assertion_name, args)
    expected_metadata = expected_value_metadata(expected_token)
    expectation_kind = expectation_kind_for(assertion_name, args, shape)
    observations.append(
        zunit_observation(
            "zunit.expectation",
            relative_path,
            line_number,
            name=assertion_name,
            metadata={
                "expectation_kind": expectation_kind,
                "matcher": expectation_matcher_for(assertion_name, args, shape),
                **expected_metadata,
                "enclosing_test": current_test,
                "expectation_checked": False,
                "assertion_executed": False,
                "test_passed_known": False,
            },
            confidence=confidence_for_value_kind(
                expected_metadata["expected_value_kind"]
            ),
        )
    )
    if expected_metadata["expected_value_kind"] == "redacted":
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                secret_source="expected_value",
            )
        )
    if assertion_name in {"assert_file_exists", "assert_dir_exists"} and args:
        target_metadata = target_path_metadata("fixture_path", args[0], relative_path)
        observations.append(
            fixture_reference_observation(
                relative_path,
                line_number,
                reference_kind="assertion_argument",
                target_metadata=target_metadata,
                context_metadata={"enclosing_test": current_test},
            )
        )
        observations.extend(
            secret_observation_for_redacted_target(
                relative_path,
                line_number,
                target_metadata,
                secret_source="fixture_path",
            )
        )
    return observations


def dynamic_assertion_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    current_test: str | None,
) -> list[RawObservation]:
    if not tokens or not is_dynamic_value(tokens[0]) or "ASSERT" not in tokens[0].upper():
        return []
    return [
        zunit_observation(
            "zunit.assertion",
            relative_path,
            line_number,
            name="[dynamic]",
            metadata={
                "assertion_name": "[dynamic]",
                "assertion_family": "unknown",
                "mode": "unknown",
                "argument_count": max(len(tokens) - 1, 0),
                "enclosing_test": current_test,
                "resolution": "dynamic",
                "dynamic_reason": "dynamic_assertion",
                "assertion_executed": False,
                "test_passed_known": False,
            },
            confidence="unknown",
        ),
        zunit_observation(
            "zunit.expectation",
            relative_path,
            line_number,
            name="[dynamic]",
            metadata={
                "expectation_kind": "unknown",
                "matcher": "unknown",
                "expected_value_kind": "dynamic",
                "raw_expected_value_stored": False,
                "enclosing_test": current_test,
                "dynamic_reason": "dynamic_assertion",
                "expectation_checked": False,
                "assertion_executed": False,
                "test_passed_known": False,
            },
            confidence="unknown",
        ),
    ]


def command_under_test_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    current_test: str | None,
    current_hook: str | None,
    fixture_variables: dict[str, str],
) -> list[RawObservation]:
    if not tokens or current_hook is not None:
        return []
    command_kind: str | None = None
    command_token: str | None = None
    args: list[str] = []
    if tokens[0] == "run":
        command_kind = "run_wrapper"
        if len(tokens) > 1:
            command_token = tokens[1]
            args = tokens[2:]
    elif current_test is not None and is_direct_command_token(tokens[0]):
        command_kind = "direct_command"
        command_token = tokens[0]
        args = tokens[1:]
    if command_kind is None:
        return []
    command_metadata = command_token_metadata(command_token)
    if command_metadata["command_kind"] == "dynamic":
        command_kind = "dynamic"
    argument_summary_kind = argument_summary_kind_for(args)
    observations: list[RawObservation] = [
        zunit_observation(
            "zunit.command_under_test",
            relative_path,
            line_number,
            name=command_metadata.get("command_name") or "[dynamic]",
            metadata={
                **command_metadata,
                "command_kind": command_kind,
                "argument_count": len(args),
                "argument_summary_kind": argument_summary_kind,
                "enclosing_test": current_test,
                "test_intent": True,
                "command_under_test": True,
                "command_executed": False,
                "commands_executed": False,
                "stdout_known": False,
                "stderr_known": False,
                "status_known": False,
            },
            confidence=(
                "unknown"
                if command_metadata["command_kind"] == "dynamic"
                else "extracted"
            ),
        )
    ]
    if argument_summary_kind == "redacted":
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                secret_source="command_argument",
            )
        )
    for arg in args:
        fixture_metadata = fixture_metadata_from_argument(
            arg,
            relative_path,
            fixture_variables,
        )
        if fixture_metadata is None:
            continue
        observations.append(
            fixture_reference_observation(
                relative_path,
                line_number,
                reference_kind="command_argument",
                target_metadata=fixture_metadata,
                context_metadata={"enclosing_test": current_test},
            )
        )
        observations.extend(
            secret_observation_for_redacted_target(
                relative_path,
                line_number,
                fixture_metadata,
                secret_source="fixture_path",
            )
        )
    return observations


def mock_or_stub_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
) -> list[RawObservation]:
    if not tokens or tokens[0] not in {"mock_command", "stub_command", "mock", "stub"}:
        return []
    kind = "zunit.mock" if tokens[0].startswith("mock") else "zunit.stub"
    args = tokens[1:]
    target_metadata = command_token_metadata(args[0] if args else None)
    metadata: dict[str, Any] = {
        **target_metadata,
        "target_kind": target_kind_for_command(target_metadata),
        "argument_count": len(args),
        "behavior_kind": behavior_kind_for_mock(tokens),
        "target_executed": False,
        "command_executed": False,
    }
    if target_metadata.get("command_name") is not None:
        metadata["target_command"] = target_metadata["command_name"]
    if kind == "zunit.mock":
        metadata["mock_declared"] = True
        metadata["mocks_applied"] = False
    else:
        metadata["stub_declared"] = True
        metadata["stub_applied"] = False
    observations = [
        zunit_observation(
            kind,
            relative_path,
            line_number,
            name=target_metadata.get("command_name") or "[dynamic]",
            metadata=metadata,
            confidence=(
                "unknown"
                if target_metadata["command_kind"] == "dynamic"
                else "extracted"
            ),
        )
    ]
    if any(redaction_for_value(token) is not None for token in args[1:]):
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                secret_source="stub_behavior" if kind == "zunit.stub" else "mock_behavior",
            )
        )
    return observations


def skip_or_todo_observation(
    relative_path: str,
    line_number: int,
    tokens: list[str],
) -> list[RawObservation]:
    if not tokens or tokens[0] not in {"skip", "todo"}:
        return []
    reason = tokens[1] if len(tokens) > 1 else ""
    metadata = reason_metadata(reason)
    kind = f"zunit.{tokens[0]}"
    extra = {
        **metadata,
        "test_status_known": False,
    }
    if tokens[0] == "skip":
        extra["skip_executed"] = False
    else:
        extra["todo_executed"] = False
    observations = [
        zunit_observation(
            kind,
            relative_path,
            line_number,
            name=tokens[0],
            metadata=extra,
            confidence=confidence_for_reason(metadata["reason_kind"]),
        )
    ]
    if metadata["reason_kind"] == "redacted":
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                secret_source=f"{tokens[0]}_reason",
            )
        )
    return observations


def strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and in_double:
            escaped = True
            continue
        if character == "'" and not in_double:
            in_single = not in_single
            continue
        if character == '"' and not in_single:
            in_double = not in_double
            continue
        if character == "#" and not in_single and not in_double:
            prefix = line[:index]
            if not prefix or prefix[-1].isspace():
                return prefix
    return line
