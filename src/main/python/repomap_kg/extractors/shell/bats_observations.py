"""Observation builders for conservative static Bats extraction."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg import __version__
from repomap_kg.extractors.shell.bats_helpers import (
    EXTRACTOR,
    SECRET_NAME_PARTS,
    BatsContext,
    assertion_expected_value,
    assertion_mode,
    bats_metadata,
    context_metadata,
    expected_value_metadata,
    is_dynamic_value,
    is_helper_like_command,
    redaction_for_value,
    secret_like_argument_observations,
    secret_like_observation,
    split_words,
    status_expectation_from_assertion,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug
DYNAMIC_TARGET_CHARS = frozenset("$`*?[")
BATS_LIBRARY_RE = re.compile(r"^\s*bats_load_library(?:\s+|$)")
ASSERTION_FAMILIES = {
    "assert_success": "status",
    "assert_failure": "status",
    "assert_equal": "equality",
    "assert_output": "output",
    "refute_output": "output",
    "assert_line": "line",
    "refute_line": "line",
    "assert_file_exists": "file",
    "refute_file_exists": "file",
    "assert_dir_exists": "directory",
    "refute_dir_exists": "directory",
}
ASSERTION_NAMES = frozenset(ASSERTION_FAMILIES)
BATS_TEMP_VARS = frozenset(
    {
        "$BATS_TMPDIR",
        "$BATS_TEST_TMPDIR",
        "$BATS_RUN_TMPDIR",
        "$BATS_FILE_TMPDIR",
        "${BATS_TMPDIR}",
        "${BATS_TEST_TMPDIR}",
        "${BATS_RUN_TMPDIR}",
        "${BATS_FILE_TMPDIR}",
    }
)

def load_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if len(words) < 2 or words[0] != "load":
        return ()
    target_token = words[1]
    target, metadata = load_target(relative_path, target_token)
    metadata["syntax"] = "load"
    name = metadata.get("target_token", "[dynamic]")
    return (
        RawObservation(
            kind="bats.load",
            source_id=f"{relative_path}#bats-load:{line_number}:{slug(str(name))}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=str(name),
            target=target,
            confidence="heuristic" if target is not None else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bats_metadata(metadata),
        ),
    )


def load_target(relative_path: str, target_token: str) -> tuple[str | None, dict[str, Any]]:
    redacted, reason = redaction_for_value(target_token)
    if redacted:
        return None, {
            "target_kind": "static",
            "resolution": "static",
            "target_redacted": True,
            "raw_value_stored": False,
            "redaction_reason": reason,
        }
    if (
        not target_token
        or target_token.startswith("/")
        or any(character in target_token for character in DYNAMIC_TARGET_CHARS)
    ):
        return None, {
            "target_kind": "dynamic",
            "resolution": "dynamic",
            "dynamic_reason": "computed-load",
            "raw_value_stored": False,
        }
    resolved = posixpath.normpath(
        posixpath.join(posixpath.dirname(relative_path), target_token)
    )
    if resolved == "." or resolved.startswith("../"):
        return None, {
            "target_token": target_token,
            "target_kind": "unknown",
            "resolution": "unknown",
            "unknown_reason": "repo-escaping-load",
            "target_redacted": False,
            "raw_value_stored": True,
        }
    return f"file:{resolved}", {
        "target_token": target_token,
        "target_kind": "static",
        "resolution": "static",
        "resolved_path": resolved,
        "helper_name": posixpath.basename(target_token.rstrip("/")),
        "target_redacted": False,
        "raw_value_stored": True,
    }


def library_load_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
    context: BatsContext,
) -> tuple[RawObservation, ...]:
    if BATS_LIBRARY_RE.match(raw_line) is None:
        return ()
    words = split_words(raw_line)
    if len(words) < 2 or words[0] != "bats_load_library":
        return (
            library_load_observation(
                relative_path,
                line_number,
                "[dynamic]",
                target_kind="dynamic",
                resolution="dynamic",
                context=context,
                dynamic_reason="computed-library",
            ),
        )
    library_name = words[1]
    if is_dynamic_value(library_name):
        return (
            library_load_observation(
                relative_path,
                line_number,
                "[dynamic]",
                target_kind="dynamic",
                resolution="dynamic",
                context=context,
                dynamic_reason="computed-library",
            ),
        )
    redacted, reason = redaction_for_value(library_name)
    if redacted:
        return (
            library_load_observation(
                relative_path,
                line_number,
                "[redacted]",
                target_kind="static",
                resolution="static",
                context=context,
                redaction_reason=reason,
            ),
            secret_like_observation(
                relative_path,
                line_number,
                "library",
                "library_load",
                reason or "secret-like-value",
                context,
            ),
        )
    return (
        library_load_observation(
            relative_path,
            line_number,
            library_name,
            target_kind="static",
            resolution="static",
            context=context,
        ),
    )


def library_load_observation(
    relative_path: str,
    line_number: int,
    library_name: str,
    *,
    target_kind: str,
    resolution: str,
    context: BatsContext,
    dynamic_reason: str | None = None,
    redaction_reason: str | None = None,
) -> RawObservation:
    redacted = redaction_reason is not None
    metadata: dict[str, Any] = {
        "library_name": library_name if not redacted and library_name != "[dynamic]" else None,
        "target_kind": target_kind,
        "resolution": resolution,
        "raw_value_stored": not redacted and library_name != "[dynamic]",
        "redacted": redacted,
        **context_metadata(context),
    }
    if dynamic_reason is not None:
        metadata["dynamic_reason"] = dynamic_reason
    if redaction_reason is not None:
        metadata["redaction_reason"] = redaction_reason
    return RawObservation(
        kind="bats.library_load",
        source_id=f"{relative_path}#bats-library-load:{line_number}:{slug(library_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=library_name,
        confidence="heuristic" if target_kind == "static" else "unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(metadata),
    )


def run_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
    context: BatsContext,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if len(words) < 2 or words[0] != "run":
        return ()
    index = 1
    expected_status: int | None = None
    negated = False
    separate_stderr = False
    while index < len(words):
        word = words[index]
        if word == "--separate-stderr":
            separate_stderr = True
            index += 1
            continue
        if word == "!":
            negated = True
            index += 1
            continue
        if re.match(r"^-\d+$", word):
            expected_status = int(word[1:])
            index += 1
            continue
        break
    if index >= len(words):
        command_token = "[unknown]"
        command_kind = "unknown"
        command_name = "[unknown]"
        argument_tokens: list[str] = []
    else:
        command_token = words[index]
        argument_tokens = words[index + 1 :]
        command_kind = "dynamic" if is_dynamic_value(command_token) else "static"
        command_name = "[dynamic]" if command_kind == "dynamic" else command_token
    metadata: dict[str, Any] = {
        "command_kind": command_kind,
        "argument_count": len(argument_tokens),
        "negated": negated,
        "separate_stderr": separate_stderr,
        "command_under_test": True,
        "command_executed": False,
        **context_metadata(context),
    }
    if command_kind == "static":
        metadata["command_token"] = command_token
    elif command_kind == "dynamic":
        metadata["dynamic_reason"] = "computed-run-command"
    if expected_status is not None:
        metadata["expected_status"] = expected_status
        metadata["expected_status_source"] = "run_flag"
    observations: list[RawObservation] = [
        RawObservation(
            kind="bats.run",
            source_id=f"{relative_path}#bats-run:{line_number}:{slug(command_name)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=command_name,
            confidence="heuristic" if command_kind == "static" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bats_metadata(metadata),
        )
    ]
    source_id = observations[0].source_id
    if expected_status is not None:
        observations.append(
            status_expectation_observation(
                relative_path,
                line_number,
                f"run:{command_name}:{expected_status}",
                source="run_flag",
                source_observation_id=source_id,
                expected_status=expected_status,
                expected_success=expected_status == 0,
                positive=not negated,
                context=context,
            )
        )
    elif negated:
        observations.append(
            status_expectation_observation(
                relative_path,
                line_number,
                f"run:{command_name}:negated",
                source="run_flag",
                source_observation_id=source_id,
                expected_status=None,
                expected_success=False,
                positive=False,
                context=context,
            )
        )
    observations.extend(
        fixture_reference_observations(
            relative_path,
            line_number,
            argument_tokens,
            context,
            source_kind="bats.run",
            source_observation_id=source_id,
        )
    )
    if command_kind == "static" and is_helper_like_command(command_token):
        observations.append(
            helper_reference_observation(
                relative_path,
                line_number,
                command_token,
                reference_kind="command_under_test",
                context=context,
            )
        )
    observations.extend(
        secret_like_argument_observations(
            relative_path,
            line_number,
            argument_tokens,
            context,
            secret_context="run_argument",
        )
    )
    return tuple(observations)


def assertion_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
    context: BatsContext,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if not words or words[0] not in ASSERTION_NAMES:
        return ()
    assertion_name = words[0]
    positive = not assertion_name.startswith("refute_")
    kind = "bats.assertion" if positive else "bats.refutation"
    family = ASSERTION_FAMILIES[assertion_name]
    mode = assertion_mode(words[1:])
    if family == "status" and mode == "unknown":
        mode = "exact"
    expected_value = assertion_expected_value(words[1:])
    value_kind, value_metadata, secret = expected_value_metadata(expected_value)
    metadata: dict[str, Any] = {
        "assertion_name": assertion_name,
        "assertion_family": family,
        "mode": "negated" if not positive and mode == "unknown" else mode,
        "argument_count": len(words) - 1,
        "expected_value_kind": value_kind,
        "assertion_executed": False,
        "redacted": value_metadata.get("redacted", False),
        **context_metadata(context),
        **value_metadata,
    }
    assertion = RawObservation(
        kind=kind,
        source_id=f"{relative_path}#bats-assertion:{line_number}:{slug(assertion_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=assertion_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(metadata),
    )
    observations: list[RawObservation] = [assertion]
    if family in {"output", "line"}:
        observations.append(
            output_expectation_observation(
                relative_path,
                line_number,
                assertion,
                expectation_kind=family,
                mode=mode,
                positive=positive,
                expected_value_kind=value_kind,
                value_metadata=value_metadata,
                context=context,
            )
        )
    if family in {"file", "directory"} and expected_value is not None:
        observations.extend(
            fixture_reference_observations(
                relative_path,
                line_number,
                [expected_value],
                context,
                source_kind=kind,
                source_observation_id=assertion.source_id,
            )
        )
    status = status_expectation_from_assertion(assertion_name, words[1:])
    if status is not None:
        observations.append(
            status_expectation_observation(
                relative_path,
                line_number,
                f"{assertion_name}:{status[0]}",
                source=status[2],
                source_observation_id=assertion.source_id,
                expected_status=status[0],
                expected_success=status[1],
                positive=positive,
                context=context,
            )
        )
    if secret is not None:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                assertion_name,
                "assertion_expected_value",
                secret,
                context,
            )
        )
    return tuple(observations)


def skip_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
    context: BatsContext,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if not words or words[0] != "skip":
        return ()
    reason = words[1] if len(words) > 1 else None
    if reason is None:
        reason_kind = "omitted"
        metadata: dict[str, Any] = {"reason_kind": reason_kind, "raw_value_stored": False}
        secret = None
    else:
        reason_kind, value_metadata, secret = expected_value_metadata(reason)
        if reason_kind == "static":
            metadata = {"reason_kind": "static", **value_metadata}
            if "expected_value_summary" in metadata:
                metadata["reason_summary"] = metadata.pop("expected_value_summary")
        elif reason_kind == "redacted":
            metadata = {"reason_kind": "redacted", **value_metadata}
        elif reason_kind == "dynamic":
            metadata = {"reason_kind": "dynamic", **value_metadata}
        else:
            metadata = {"reason_kind": "unknown", **value_metadata}
    metadata.update(
        {
            "reason_redacted": metadata.get("redacted", False),
            "skip_executed": False,
            **context_metadata(context),
        }
    )
    skip = RawObservation(
        kind="bats.skip",
        source_id=f"{relative_path}#bats-skip:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="skip",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(metadata),
    )
    if secret is None:
        return (skip,)
    return (
        skip,
        secret_like_observation(
            relative_path,
            line_number,
            "skip",
            "skip_reason",
            secret,
            context,
        ),
    )


def output_expectation_observation(
    relative_path: str,
    line_number: int,
    assertion: RawObservation,
    *,
    expectation_kind: str,
    mode: str,
    positive: bool,
    expected_value_kind: str,
    value_metadata: dict[str, Any],
    context: BatsContext,
) -> RawObservation:
    metadata = {
        "source_assertion_id": assertion.source_id,
        "expectation_kind": expectation_kind,
        "mode": mode,
        "positive": positive,
        "expected_value_kind": expected_value_kind,
        **context_metadata(context),
        **value_metadata,
    }
    return RawObservation(
        kind="bats.output_expectation",
        source_id=f"{relative_path}#bats-output-expectation:{line_number}:{slug(assertion.name or expectation_kind)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=expectation_kind,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(metadata),
    )


def status_expectation_observation(
    relative_path: str,
    line_number: int,
    name: str,
    *,
    source: str,
    source_observation_id: str,
    expected_status: int | None,
    expected_success: bool | None,
    positive: bool,
    context: BatsContext,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "source": source,
        "source_observation_id": source_observation_id,
        "positive": positive,
        **context_metadata(context),
    }
    if expected_status is not None:
        metadata["expected_status"] = expected_status
    if expected_success is not None:
        metadata["expected_success"] = expected_success
    return RawObservation(
        kind="bats.status_expectation",
        source_id=f"{relative_path}#bats-status-expectation:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(metadata),
    )


def helper_reference_from_load(
    relative_path: str,
    line_number: int,
    load: RawObservation,
    context: BatsContext,
) -> RawObservation | None:
    helper_name = load.metadata.get("helper_name")
    if not isinstance(helper_name, str) or not helper_name:
        return None
    return helper_reference_observation(
        relative_path,
        line_number,
        helper_name,
        reference_kind="load_target",
        context=context,
    )


def helper_reference_observation(
    relative_path: str,
    line_number: int,
    helper_name: str,
    *,
    reference_kind: str,
    context: BatsContext,
) -> RawObservation:
    return RawObservation(
        kind="bats.helper_reference",
        source_id=f"{relative_path}#bats-helper-reference:{line_number}:{slug(reference_kind + '-' + helper_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=helper_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(
            {
                "helper_name": helper_name,
                "reference_kind": reference_kind,
                "resolution": "static",
                "helper_executed": False,
                **context_metadata(context),
            }
        ),
    )


def fixture_reference_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    context: BatsContext,
    *,
    source_kind: str,
    source_observation_id: str,
) -> tuple[RawObservation, ...]:
    observations = []
    for token in tokens:
        reference = fixture_reference_metadata(relative_path, token)
        if reference is None:
            continue
        target, metadata = reference
        metadata.update(
            {
                "source_kind": source_kind,
                "source_observation_id": source_observation_id,
                "filesystem_checked": False,
                "file_created": False,
                **context_metadata(context),
            }
        )
        observations.append(
            RawObservation(
                kind="bats.fixture_reference",
                source_id=f"{relative_path}#bats-fixture-reference:{line_number}:{slug(token)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=metadata.get("path_token", "[dynamic]"),
                target=target,
                confidence="heuristic" if target is not None else "unknown",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=bats_metadata(metadata),
            )
        )
    return tuple(observations)


def fixture_reference_metadata(
    relative_path: str,
    token: str,
) -> tuple[str | None, dict[str, Any]] | None:
    if any(temp_var in token for temp_var in BATS_TEMP_VARS):
        return None, {
            "path_token": "[temp]",
            "fixture_kind": "temp_fixture",
            "resolution": "temp",
            "raw_value_stored": False,
        }
    dirname = posixpath.dirname(relative_path)
    marker = "${BATS_TEST_DIRNAME}/"
    if token.startswith(marker):
        tail = token[len(marker) :]
        resolved = posixpath.normpath(posixpath.join(dirname, tail))
        return f"file:{resolved}", {
            "path_token": token,
            "fixture_kind": "repo_fixture",
            "resolution": "static",
            "resolved_path": resolved,
            "raw_value_stored": True,
        }
    marker = "$BATS_TEST_DIRNAME/"
    if token.startswith(marker):
        tail = token[len(marker) :]
        resolved = posixpath.normpath(posixpath.join(dirname, tail))
        return f"file:{resolved}", {
            "path_token": token,
            "fixture_kind": "repo_fixture",
            "resolution": "static",
            "resolved_path": resolved,
            "raw_value_stored": True,
        }
    if token == "./fixtures" or token.startswith("./fixtures/"):
        resolved = posixpath.normpath(posixpath.join(dirname, token))
        return f"file:{resolved}", {
            "path_token": token,
            "fixture_kind": "repo_fixture",
            "resolution": "static",
            "resolved_path": resolved,
            "raw_value_stored": True,
        }
    if token == "test/fixtures" or token.startswith("test/fixtures/"):
        resolved = posixpath.normpath(token)
        return f"file:{resolved}", {
            "path_token": token,
            "fixture_kind": "repo_fixture",
            "resolution": "static",
            "resolved_path": resolved,
            "raw_value_stored": True,
        }
    if "fixtures" in token and is_dynamic_value(token):
        return None, {
            "path_token": "[dynamic]",
            "fixture_kind": "dynamic",
            "resolution": "dynamic",
            "raw_value_stored": False,
        }
    return None
