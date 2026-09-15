"""Conservative static Bats raw observation extraction."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


BATS_TEST_RE = re.compile(r"^\s*@test\s+(?P<quote>['\"])(?P<name>.*?)\1\s*\{")
HOOK_RE = re.compile(r"^\s*(setup|teardown|setup_file|teardown_file)\s*\(\s*\)\s*\{")
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
from repomap_kg.extractors.shell.bats_observations import (
    ASSERTION_FAMILIES,
    ASSERTION_NAMES,
    BATS_LIBRARY_RE,
    BATS_TEMP_VARS,
    DYNAMIC_TARGET_CHARS,
    assertion_observations,
    fixture_reference_metadata,
    fixture_reference_observations,
    helper_reference_from_load,
    helper_reference_observation,
    library_load_observation,
    library_load_observations,
    load_observations,
    load_target,
    output_expectation_observation,
    run_observations,
    skip_observations,
    status_expectation_observation,
)


@dataclass
class PendingHeredoc:
    delimiter: str
    tab_stripping: bool


def extract_bats_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = [bats_file_observation(relative_path, content)]
    pending_heredoc: PendingHeredoc | None = None
    current_context: BatsContext | None = None

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if pending_heredoc is not None:
            terminator = raw_line.lstrip("\t").strip() if pending_heredoc.tab_stripping else stripped
            if terminator == pending_heredoc.delimiter:
                pending_heredoc = None
            continue
        if not stripped or stripped.startswith("#"):
            continue

        test_cases = test_case_observations(relative_path, line_number, raw_line)
        if test_cases:
            observations.extend(test_cases)
            current_context = context_from_test_case(test_cases[0], raw_line)
            continue

        hooks = hook_observations(relative_path, line_number, raw_line)
        if hooks:
            observations.extend(hooks)
            current_context = context_from_hook(hooks[0], raw_line)
            continue

        heredoc_match = HEREDOC_RE.search(raw_line)
        if heredoc_match is not None:
            pending_heredoc = PendingHeredoc(
                delimiter=heredoc_match.group(2),
                tab_stripping="<<-" in raw_line,
            )

        line_context = current_context or BatsContext(test_context="file")
        loads = load_observations(relative_path, line_number, raw_line)
        observations.extend(loads)
        for load in loads:
            helper = helper_reference_from_load(relative_path, line_number, load, line_context)
            if helper is not None:
                observations.append(helper)
        observations.extend(library_load_observations(relative_path, line_number, raw_line, line_context))
        observations.extend(run_observations(relative_path, line_number, raw_line, line_context))
        observations.extend(assertion_observations(relative_path, line_number, raw_line, line_context))
        observations.extend(skip_observations(relative_path, line_number, raw_line, line_context))

        if current_context is not None:
            current_context.brace_depth += raw_line.count("{") - raw_line.count("}")
            if current_context.brace_depth <= 0:
                current_context = None

    return tuple(observations)


def bats_file_observation(relative_path: str, content: str) -> RawObservation:
    first = content.splitlines()[0].strip() if content.splitlines() else ""
    metadata = bats_metadata(
        {
            "file_type": "bats",
            "shebang": first if first.startswith("#!") else None,
            "classification_evidence": classification_evidence(relative_path, first),
        }
    )
    return RawObservation(
        kind="bats.file",
        source_id=f"{relative_path}#bats-file",
        path=relative_path,
        name=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def classification_evidence(relative_path: str, shebang: str) -> list[str]:
    evidence = []
    if Path(relative_path).suffix == ".bats":
        evidence.append("extension")
    if is_bats_shebang(shebang):
        evidence.append("shebang")
    return evidence


def is_bats_shebang(line: str) -> bool:
    return bool(re.match(r"^#!.*(?:^|/|\s)bats(?:\s|$)", line.strip()))


def test_case_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    match = BATS_TEST_RE.match(raw_line)
    if match is None:
        if raw_line.lstrip().startswith("@test "):
            return (
                dynamic_test_case_observation(
                    relative_path,
                    line_number,
                    dynamic_reason="unsupported-test-name",
                ),
            )
        return ()
    test_name = match.group("name")
    if is_dynamic_value(test_name):
        return (
            dynamic_test_case_observation(
                relative_path,
                line_number,
                dynamic_reason="computed-test-name",
            ),
        )
    redacted, reason = redaction_for_value(test_name)
    metadata: dict[str, Any] = {
        "test_name_kind": "static",
        "body_modeled": False,
        "command_count_modeled": False,
        "test_name_redacted": redacted,
        "raw_value_stored": not redacted,
    }
    name = test_name
    if redacted:
        name = "[redacted]"
        metadata["redaction_reason"] = reason
    else:
        metadata["test_name"] = test_name
    return (
        RawObservation(
            kind="bats.test_case",
            source_id=f"{relative_path}#bats-test:{line_number}:{slug(name)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=name,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bats_metadata(metadata),
        ),
    )


def dynamic_test_case_observation(
    relative_path: str,
    line_number: int,
    *,
    dynamic_reason: str,
) -> RawObservation:
    return RawObservation(
        kind="bats.test_case",
        source_id=f"{relative_path}#bats-test:{line_number}:dynamic",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="[dynamic]",
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(
            {
                "test_name_kind": "dynamic",
                "body_modeled": False,
                "command_count_modeled": False,
                "resolution": "dynamic",
                "dynamic_reason": dynamic_reason,
                "raw_value_stored": False,
            }
        ),
    )


def context_from_test_case(observation: RawObservation, raw_line: str) -> BatsContext:
    metadata = observation.metadata
    test_case_name = metadata.get("test_name")
    if not isinstance(test_case_name, str):
        test_case_name = observation.name
    return BatsContext(
        test_context="test_case",
        test_case_name=test_case_name,
        test_case_name_redacted=bool(metadata.get("test_name_redacted")),
        brace_depth=brace_delta(raw_line),
    )


def hook_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    match = HOOK_RE.match(raw_line)
    if match is None:
        return ()
    hook_name = match.group(1)
    hook_scope = "per_file" if hook_name.endswith("_file") else "per_test"
    return (
        RawObservation(
            kind=f"bats.{hook_name}",
            source_id=f"{relative_path}#bats-hook:{line_number}:{hook_name}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=hook_name,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bats_metadata(
                {
                    "hook_name": hook_name,
                    "hook_scope": hook_scope,
                    "body_modeled": False,
                    "executes_at_parse_time": False,
                }
            ),
        ),
    )


def context_from_hook(observation: RawObservation, raw_line: str) -> BatsContext:
    return BatsContext(
        test_context=str(observation.name or "file"),
        brace_depth=brace_delta(raw_line),
    )


def brace_delta(raw_line: str) -> int:
    return raw_line.count("{") - raw_line.count("}")
