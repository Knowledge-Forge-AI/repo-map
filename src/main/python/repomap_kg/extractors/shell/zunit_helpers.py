"""Shared ZUnit extractor metadata, target, and redaction helpers."""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


EXTRACTOR = "repo-zunit"
DYNAMIC_TARGET_CHARS = frozenset("$`*?[")
SECRET_NAME_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "key",
        "credential",
        "apikey",
        "pat",
        "authorization",
        "auth",
    }
)


def bounded_name_metadata(value: str, field_name: str) -> tuple[str, dict[str, Any]]:
    redaction_reason = redaction_for_value(value)
    kind_key = f"{field_name}_kind"
    if redaction_reason is not None:
        return (
            "[redacted]",
            {
                kind_key: "redacted",
                f"{field_name}_redacted": True,
                "redaction_reason": redaction_reason,
                "raw_value_stored": False,
            },
        )
    if len(value) > 120:
        return (
            "[dynamic]",
            {
                kind_key: "unknown",
                f"{field_name}_redacted": False,
                "raw_value_stored": False,
                "dynamic_reason": "long_name",
            },
        )
    return (
        value,
        {
            kind_key: "static",
            field_name: value,
            f"{field_name}_redacted": False,
            "raw_value_stored": True,
        },
    )


def redaction_for_value(value: str) -> str | None:
    lower = value.lower()
    for part in SECRET_NAME_PARTS:
        if part == "pat":
            if re.search(r"(^|[^a-z])pat([^a-z]|$)", lower):
                return "secret-like-name"
            continue
        if part in lower:
            return "secret-like-name"
    return None


def is_dynamic_value(value: str) -> bool:
    return (
        any(character in value for character in DYNAMIC_TARGET_CHARS)
        or "${" in value
    )


def tokenize_line(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=False, posix=True)
    except ValueError:
        return []


def zunit_observation(
    kind: str,
    relative_path: str,
    line_number: int,
    *,
    name: str,
    metadata: dict[str, Any],
    confidence: str = "extracted",
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind}:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zunit_metadata(metadata),
    )


def secret_observations_from_metadata(
    relative_path: str,
    line_number: int,
    metadata: dict[str, Any],
    *,
    secret_source: str,
) -> list[RawObservation]:
    if metadata.get("redaction_reason") is None:
        return []
    if metadata.get("raw_value_stored") is not False:
        return []
    return [
        secret_like_observation(
            relative_path,
            line_number,
            secret_source=secret_source,
            redaction_reason=str(metadata["redaction_reason"]),
        )
    ]


def secret_observation_for_redacted_target(
    relative_path: str,
    line_number: int,
    metadata: dict[str, Any],
    *,
    secret_source: str,
) -> list[RawObservation]:
    if metadata.get("target_kind") != "redacted":
        return []
    return [
        secret_like_observation(
            relative_path,
            line_number,
            secret_source=secret_source,
            redaction_reason=str(metadata.get("redaction_reason", "secret-like-name")),
        )
    ]


def secret_like_observation(
    relative_path: str,
    line_number: int,
    *,
    secret_source: str,
    redaction_reason: str = "secret-like-name",
) -> RawObservation:
    return zunit_observation(
        "zunit.secret_like",
        relative_path,
        line_number,
        name=secret_source,
        metadata={
            "secret_source": secret_source,
            "redaction_reason": redaction_reason,
            "raw_value_stored": False,
        },
        confidence="heuristic",
    )


def target_path_metadata(
    field_name: str,
    token: str,
    relative_path: str,
) -> dict[str, Any]:
    redaction_reason = redaction_for_value(token)
    if redaction_reason is not None:
        return {
            "target_kind": "redacted",
            "resolution": "unknown",
            "redaction_reason": redaction_reason,
            "raw_value_stored": False,
        }
    if is_dynamic_value(token):
        return {
            "target_kind": "dynamic",
            "resolution": "dynamic",
            "dynamic_reason": "computed_target",
            "raw_value_stored": False,
        }
    if token.startswith(("/", "~")):
        return {
            "target_kind": "unknown",
            "resolution": "unknown",
            "dynamic_reason": "unsafe_path",
            "raw_value_stored": False,
        }
    base_dir = posixpath.dirname(relative_path)
    resolved = posixpath.normpath(posixpath.join(base_dir, token))
    if resolved == ".." or resolved.startswith("../"):
        return {
            "target_kind": "unknown",
            "resolution": "unknown",
            "dynamic_reason": "repository_escaping_path",
            "raw_value_stored": False,
        }
    return {
        field_name: token,
        "target_kind": "static",
        "resolution": "static",
        "resolved_path": resolved,
        "raw_value_stored": True,
    }


def confidence_for_target(metadata: dict[str, Any]) -> str:
    return "extracted" if metadata.get("target_kind") == "static" else "unknown"


def fixture_reference_observation(
    relative_path: str,
    line_number: int,
    *,
    reference_kind: str,
    target_metadata: dict[str, Any],
    context_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    return zunit_observation(
        "zunit.fixture_reference",
        relative_path,
        line_number,
        name=target_metadata.get("fixture_path") or "[dynamic]",
        metadata={
            **target_metadata,
            **(context_metadata or {}),
            "reference_kind": reference_kind,
            "fixture_loaded": False,
            "file_read": False,
            "filesystem_checked": False,
        },
        confidence=confidence_for_target(target_metadata),
    )


def looks_like_fixture(token: str) -> bool:
    lower = token.lower()
    return "fixture" in lower or "fixtures/" in lower or "zunit_tmpdir" in lower


def fixture_metadata_from_argument(
    token: str,
    relative_path: str,
    fixture_variables: dict[str, str],
) -> dict[str, Any] | None:
    variable_name = variable_name_from_reference(token)
    if variable_name is not None and variable_name in fixture_variables:
        return target_path_metadata(
            "fixture_path",
            fixture_variables[variable_name],
            relative_path,
        )
    if looks_like_fixture(token):
        return target_path_metadata("fixture_path", token, relative_path)
    return None


def variable_name_from_reference(token: str) -> str | None:
    if token.startswith("${") and token.endswith("}"):
        return token[2:-1]
    if token.startswith("$") and len(token) > 1:
        return token[1:]
    return None


def command_token_metadata(command_token: str | None) -> dict[str, Any]:
    if not command_token:
        return {
            "command_kind": "dynamic",
            "dynamic_reason": "missing_command",
            "raw_value_stored": False,
        }
    redaction_reason = redaction_for_value(command_token)
    if redaction_reason is not None:
        return {
            "command_kind": "redacted",
            "target_kind": "redacted",
            "redaction_reason": redaction_reason,
            "raw_value_stored": False,
        }
    if is_dynamic_value(command_token):
        return {
            "command_kind": "dynamic",
            "target_kind": "dynamic",
            "dynamic_reason": "computed_command",
            "raw_value_stored": False,
        }
    if len(command_token) > 120:
        return {
            "command_kind": "unknown",
            "target_kind": "unknown",
            "dynamic_reason": "long_command",
            "raw_value_stored": False,
        }
    return {
        "command_name": command_token,
        "command_kind": "static",
        "target_kind": "command",
        "raw_value_stored": True,
    }


def target_kind_for_command(metadata: dict[str, Any]) -> str:
    if metadata.get("target_kind") in {"dynamic", "redacted", "unknown"}:
        return str(metadata["target_kind"])
    return "command"


def argument_summary_kind_for(args: list[str]) -> str:
    if not args:
        return "omitted"
    if any(redaction_for_value(arg) is not None for arg in args):
        return "redacted"
    if any(is_dynamic_value(arg) for arg in args):
        return "dynamic"
    return "bounded"


def is_direct_command_token(token: str) -> bool:
    return token.startswith(("./", "../")) or "/" in token


def assertion_family_for(
    assertion_name: str,
    args: list[str],
    fallback: str,
) -> str:
    if assertion_name == "assert_equal" and args and "status" in args[0]:
        return "status"
    return fallback


def assertion_mode_for(
    assertion_name: str,
    args: list[str],
    fallback: str,
) -> str:
    if assertion_name == "assert_output" and "--partial" in args:
        return "partial"
    if assertion_name == "refute_output":
        return "negated"
    return fallback


def expectation_kind_for(
    assertion_name: str,
    args: list[str],
    shape: dict[str, str],
) -> str:
    if assertion_name == "assert_equal" and args and "status" in args[0]:
        return "status"
    if assertion_name == "assert_equal":
        return "unknown"
    return shape["expectation_kind"]


def expectation_matcher_for(
    assertion_name: str,
    args: list[str],
    shape: dict[str, str],
) -> str:
    if assertion_name == "assert_output" and "--partial" in args:
        return "contains"
    return shape["matcher"]


def expected_value_token(assertion_name: str, args: list[str]) -> str | None:
    if assertion_name in {"assert_success", "assert_failure"}:
        return None
    if assertion_name == "assert_output" and "--partial" in args:
        non_options = [arg for arg in args if not arg.startswith("--")]
        return non_options[-1] if non_options else None
    if assertion_name in {"assert_output", "refute_output"}:
        return args[-1] if args else None
    if assertion_name == "assert_equal":
        return args[-1] if args else None
    if assertion_name in {"assert_file_exists", "assert_dir_exists"}:
        return args[0] if args else None
    return None


def expected_value_metadata(value: str | None) -> dict[str, Any]:
    if value is None:
        return {
            "expected_value_kind": "omitted",
            "raw_expected_value_stored": False,
        }
    redaction_reason = redaction_for_value(value)
    if redaction_reason is not None:
        return {
            "expected_value_kind": "redacted",
            "raw_expected_value_stored": False,
            "redaction_reason": redaction_reason,
        }
    if is_dynamic_value(value):
        return {
            "expected_value_kind": "dynamic",
            "raw_expected_value_stored": False,
            "dynamic_reason": "computed_expected_value",
        }
    if len(value) > 120:
        return {
            "expected_value_kind": "omitted",
            "raw_expected_value_stored": False,
            "dynamic_reason": "long_expected_value",
        }
    return {
        "expected_value_kind": "static",
        "expected_value_summary": value,
        "raw_expected_value_stored": True,
    }


def confidence_for_value_kind(value_kind: str) -> str:
    return "extracted" if value_kind in {"static", "omitted"} else "heuristic"


def behavior_kind_for_mock(tokens: list[str]) -> str:
    if "--stdout" in tokens:
        return "stdout"
    if "--stderr" in tokens:
        return "stderr"
    if "--status" in tokens:
        return "status"
    if any(looks_like_fixture(token) for token in tokens[1:]):
        return "file"
    if any(is_dynamic_value(token) for token in tokens[1:]):
        return "dynamic"
    return "unknown"


def reason_metadata(reason: str) -> dict[str, Any]:
    if not reason:
        return {
            "reason_kind": "omitted",
            "raw_value_stored": False,
        }
    redaction_reason = redaction_for_value(reason)
    if redaction_reason is not None:
        return {
            "reason_kind": "redacted",
            "redaction_reason": redaction_reason,
            "raw_value_stored": False,
        }
    if is_dynamic_value(reason):
        return {
            "reason_kind": "dynamic",
            "dynamic_reason": "computed_reason",
            "raw_value_stored": False,
        }
    if len(reason) > 120:
        return {
            "reason_kind": "omitted",
            "dynamic_reason": "long_reason",
            "raw_value_stored": False,
        }
    return {
        "reason_kind": "static",
        "reason_summary": reason,
        "raw_value_stored": True,
    }


def confidence_for_reason(reason_kind: str) -> str:
    return "extracted" if reason_kind in {"static", "omitted"} else "heuristic"


def zunit_metadata(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
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
    if extra:
        metadata.update(
            {key: value for key, value in extra.items() if value is not None}
        )
    return metadata
