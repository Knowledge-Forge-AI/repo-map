"""Shared canonicalization evidence helpers."""

from __future__ import annotations

from repomap_kg.canonicalization.core import _evidence_from_observation, _evidence_key

BASH_EVIDENCE_OMIT_KEYS = frozenset(
    (
        "raw",
        "value",
        "values",
        "source",
        "source_token",
        "target_display",
        "target_summary",
        "values_summary",
        "handler_summary",
        "expression_summary",
        "pattern",
        "resolved_path",
    )
)

BATS_EVIDENCE_OMIT_KEYS = frozenset(
    (
        "raw",
        "value",
        "values",
        "source",
        "target_token",
        "target_display",
        "expected_value_summary",
        "reason_summary",
        "path_token",
        "resolved_path",
    )
)

ZUNIT_EVIDENCE_OMIT_KEYS = frozenset(
    (
        "raw",
        "value",
        "values",
        "source",
        "source_token",
        "target_token",
        "target_display",
        "expected_value_summary",
        "reason_summary",
        "path_token",
        "helper_path",
        "fixture_path",
        "resolved_path",
    )
)

AWK_EVIDENCE_OMIT_KEYS = frozenset(
    (
        "raw",
        "value",
        "values",
        "source",
        "source_text",
        "raw_source",
        "pattern_summary",
        "value_summary",
        "target_display",
        "command_summary",
        "include_target",
        "resolved_path",
    )
)

ZSH_EVIDENCE_OMIT_KEYS = frozenset(
    (
        "raw",
        "value",
        "values",
        "source",
        "source_text",
        "raw_source",
        "target_token",
        "target_display",
        "argument_display",
        "value_summary",
        "context_pattern",
        "path_display",
        "pattern_summary",
        "resolved_path",
        "theme_name",
        "compdef_target",
        "completion_name",
        "plugin_name",
        "module_name",
        "function_names",
    )
)
