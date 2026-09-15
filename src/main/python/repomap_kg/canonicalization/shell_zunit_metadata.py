"""Zunit canonicalization identity and metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.graph.keys import (
    zunit_file_key,
    zunit_suite_key,
    zunit_test_case_key,
)
from repomap_kg.observations.raw import RawObservation


def _zunit_static_suite_identity(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "suite_name_kind") != "static":
        return None
    if bool(observation.metadata.get("suite_name_redacted")):
        return None
    return _metadata_text(observation.metadata, "suite_name") or observation.name


def _zunit_static_test_identity(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "test_name_kind") != "static":
        return None
    if bool(observation.metadata.get("test_name_redacted")):
        return None
    return _metadata_text(observation.metadata, "test_name") or observation.name


def _zunit_test_owner(
    observation: RawObservation,
) -> tuple[str, str, str, dict[str, Any]]:
    suite_name = _metadata_text(observation.metadata, "enclosing_suite")
    if suite_name is not None and not bool(
        observation.metadata.get("suite_name_redacted")
    ):
        return (
            zunit_suite_key(observation.path, suite_name),
            "zunit.suite",
            suite_name,
            _zunit_suite_node_metadata({"suite_name": suite_name}),
        )
    return (
        zunit_file_key(observation.path),
        "zunit.file",
        observation.path,
        _zunit_file_node_metadata({}),
    )


def _zunit_context_source(
    observation: RawObservation,
) -> tuple[str, str, str, dict[str, Any]]:
    test_name = _metadata_text(observation.metadata, "enclosing_test")
    if test_name is not None and test_name != "[dynamic]":
        return (
            zunit_test_case_key(observation.path, test_name),
            "zunit.test_case",
            test_name,
            _zunit_test_case_node_metadata({"test_name": test_name}),
        )
    suite_name = _metadata_text(observation.metadata, "enclosing_suite")
    if suite_name is not None:
        return (
            zunit_suite_key(observation.path, suite_name),
            "zunit.suite",
            suite_name,
            _zunit_suite_node_metadata({"suite_name": suite_name}),
        )
    return (
        zunit_file_key(observation.path),
        "zunit.file",
        observation.path,
        _zunit_file_node_metadata({}),
    )


def _zunit_file_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "test_file"
    for key in ("file_type", "classification_evidence", "parser"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _zunit_suite_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "suite"
    summary["body_modeled"] = False
    summary["suite_executed"] = False
    _append_metadata_text(summary, metadata, "suite_kind", "suite_kinds")
    _append_metadata_text(summary, metadata, "suite_name_kind", "suite_name_kinds")
    return summary


def _zunit_test_case_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "test_case"
    summary["body_modeled"] = False
    summary["test_intent"] = True
    summary["test_executed"] = False
    _append_metadata_text(summary, metadata, "test_name_kind", "test_name_kinds")
    _append_metadata_text(summary, metadata, "syntax", "syntaxes")
    return summary


def _zunit_hook_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "hook"
    summary["body_modeled"] = False
    summary["hook_executed"] = False
    _append_metadata_text(summary, metadata, "hook_kind", "hook_kinds")
    _append_metadata_text(summary, metadata, "hook_scope", "hook_scopes")
    return summary


def _zunit_command_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "command_under_test"
    summary["test_intent"] = True
    summary["command_under_test"] = True
    summary["command_executed"] = False
    _append_metadata_text(summary, metadata, "command_kind", "command_kinds")
    _append_metadata_text(summary, metadata, "argument_summary_kind", "argument_kinds")
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary


def _zunit_assertion_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "assertion"
    summary["assertion_executed"] = False
    summary["test_passed_known"] = False
    for source_key, target_key in (
        ("assertion_name", "assertion_names"),
        ("assertion_family", "assertion_families"),
        ("mode", "modes"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary


def _zunit_expectation_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "expectation"
    summary["expectation_checked"] = False
    summary["assertion_executed"] = False
    summary["test_passed_known"] = False
    for source_key, target_key in (
        ("expectation_kind", "expectation_kinds"),
        ("matcher", "matchers"),
        ("expected_value_kind", "expected_value_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    return summary


def _zunit_mock_or_stub_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    summary["node_role"] = "mock_or_stub"
    summary["command_executed"] = False
    summary["target_executed"] = False
    summary["mocks_applied"] = False
    summary["stubs_applied"] = False
    for source_key, target_key in (
        ("target_kind", "target_kinds"),
        ("behavior_kind", "behavior_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    return summary


def _zunit_base_metadata() -> dict[str, Any]:
    return {
        "language": "zsh",
        "dialect": "zsh",
        "test_framework": "zunit",
        "static_only": True,
        "shell_executed": False,
        "zsh_executed": False,
        "zunit_executed": False,
        "tests_executed": False,
        "assertions_executed": False,
        "commands_executed": False,
        "fixtures_loaded": False,
        "mocks_applied": False,
    }


def _zunit_base_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_metadata()
    for source_key, target_key in (
        ("test_intent", "test_intent_observed"),
        ("command_under_test", "command_under_test_observed"),
        ("command_executed", "command_executed_observed"),
        ("filesystem_checked", "filesystem_checked_observed"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, bool):
            summary[target_key] = value
    return summary


def _zunit_helper_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary["helper_loaded"] = False
    summary["file_read"] = False
    summary["filesystem_checked"] = False
    _append_metadata_text(summary, metadata, "reference_kind", "reference_kinds")
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    return summary


def _zunit_fixture_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary["fixture_loaded"] = False
    summary["file_read"] = False
    summary["filesystem_checked"] = False
    _append_metadata_text(summary, metadata, "reference_kind", "reference_kinds")
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    return summary


def _zunit_command_edge_metadata(
    metadata: Mapping[str, Any],
    command_name: str,
) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary.update(
        {
            "commands": [command_name],
            "test_intent": True,
            "command_under_test": True,
            "command_executed": False,
            "commands_executed": False,
            "stdout_known": False,
            "stderr_known": False,
            "status_known": False,
        }
    )
    _append_metadata_text(summary, metadata, "command_kind", "command_kinds")
    _append_metadata_text(summary, metadata, "argument_summary_kind", "argument_kinds")
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary


def _zunit_assertion_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary["assertion_executed"] = False
    summary["test_passed_known"] = False
    for source_key, target_key in (
        ("assertion_name", "assertion_names"),
        ("assertion_family", "assertion_families"),
        ("mode", "modes"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    return summary


def _zunit_expectation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary["expectation_checked"] = False
    summary["assertion_executed"] = False
    summary["test_passed_known"] = False
    for source_key, target_key in (
        ("expectation_kind", "expectation_kinds"),
        ("matcher", "matchers"),
        ("expected_value_kind", "expected_value_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    return summary


def _zunit_mock_or_stub_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _zunit_base_edge_metadata(metadata)
    summary["command_executed"] = False
    summary["target_executed"] = False
    summary["mocks_applied"] = False
    summary["stubs_applied"] = False
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    _append_metadata_text(summary, metadata, "behavior_kind", "behavior_kinds")
    return summary
