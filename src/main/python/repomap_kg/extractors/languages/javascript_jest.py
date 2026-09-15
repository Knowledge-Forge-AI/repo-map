"""Jest observation helpers for JavaScript extraction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re

from repomap_kg.graph.keys import js_test_case_key, js_test_suite_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_detection import _is_jest_profile
from repomap_kg.extractors.languages.javascript_observations import (
    PARSER,
    _definition_observation,
    _framework_observation,
    _observation,
)
from repomap_kg.extractors.languages.javascript_references import _safe_summary


JEST_TEST_CALLS = frozenset(("it", "test"))
JEST_HOOK_CALLS = frozenset(("beforeEach", "afterEach", "beforeAll", "afterAll"))
JEST_SUITE_RE = re.compile(
    r"""\bdescribe\s*\(\s*(?P<quote>["'])(?P<name>.+?)(?P=quote)"""
)
JEST_CASE_RE = re.compile(
    r"""\b(?P<call>it|test)\s*\(\s*(?P<quote>["'])(?P<name>.+?)(?P=quote)"""
)
JEST_MOCK_RE = re.compile(r"""\bjest\.(?P<kind>mock|fn|spyOn)\s*\(""")
JEST_MATCHER_RE = re.compile(
    r"""\bexpect\s*\([^)]*\)\s*\.\s*(?P<matcher>[A-Za-z_$][\w$]*)\b"""
)


@dataclass
class JestScanState:
    suite_count: int = 0
    current_suite_key: str | None = None
    case_count_by_owner: dict[str, int] = field(default_factory=dict)


def _add_jest_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    content: str,
    line_number: int,
    stripped: str,
    file_canonical_key: str,
    module_canonical_key: str,
    observations: list[RawObservation],
    state: JestScanState,
    add_framework_observation: Callable[[RawObservation], None],
) -> None:
    if not _is_jest_profile(profile, relative_path, content):
        return

    suite_match = JEST_SUITE_RE.search(stripped)
    if suite_match:
        state.suite_count += 1
        pointer = f"/tests/describe[{state.suite_count}]"
        suite_key = js_test_suite_key(relative_path, pointer)
        state.current_suite_key = suite_key
        observations.append(
            _definition_observation(
                "js.test_suite",
                relative_path,
                js_format,
                "jest",
                line_number,
                f"describe[{state.suite_count}]",
                suite_key,
                source_key=module_canonical_key,
                metadata={
                    "test_framework": "jest",
                    "test_name_summary": _safe_summary(suite_match.group("name")),
                    "identity_strength": "structural",
                },
            )
        )
        add_framework_observation(
            _framework_observation(
                "jest.suite",
                relative_path,
                js_format,
                "jest",
                line_number,
                f"describe[{state.suite_count}]",
                module_canonical_key,
                metadata={
                    "test_framework": "jest",
                    "test_name_summary": _safe_summary(suite_match.group("name")),
                    "suite_key": suite_key,
                },
            )
        )

    case_match = JEST_CASE_RE.search(stripped)
    if case_match:
        owner_key = state.current_suite_key or file_canonical_key
        count = state.case_count_by_owner.get(owner_key, 0) + 1
        state.case_count_by_owner[owner_key] = count
        pointer = f"/tests/{case_match.group('call')}[{count}]"
        test_key = js_test_case_key(owner_key, pointer)
        observations.append(
            _definition_observation(
                "js.test_case",
                relative_path,
                js_format,
                "jest",
                line_number,
                f"{case_match.group('call')}[{count}]",
                test_key,
                source_key=owner_key,
                metadata={
                    "test_framework": "jest",
                    "test_name_summary": _safe_summary(case_match.group("name")),
                    "identity_strength": "structural",
                },
            )
        )
        add_framework_observation(
            _framework_observation(
                "jest.test",
                relative_path,
                js_format,
                "jest",
                line_number,
                f"{case_match.group('call')}[{count}]",
                module_canonical_key,
                metadata={
                    "test_framework": "jest",
                    "test_call": case_match.group("call"),
                    "test_name_summary": _safe_summary(case_match.group("name")),
                    "suite_key": owner_key,
                    "test_key": test_key,
                },
            )
        )

    if "expect(" in stripped:
        matchers = tuple(
            dict.fromkeys(
                match.group("matcher") for match in JEST_MATCHER_RE.finditer(stripped)
            )
        )
        observations.append(
            _observation(
                kind="js.test_expectation",
                relative_path=relative_path,
                source_id=f"{relative_path}#js-expectation:{line_number}",
                start_line=line_number,
                name="expect",
                metadata={
                    "format": js_format,
                    "profile": "jest",
                    "parser": PARSER,
                    "test_framework": "jest",
                    "expectation_count": stripped.count("expect("),
                    "source_key": state.current_suite_key or module_canonical_key,
                },
            )
        )
        add_framework_observation(
            _framework_observation(
                "jest.expectation",
                relative_path,
                js_format,
                "jest",
                line_number,
                "expect",
                module_canonical_key,
                metadata={
                    "test_framework": "jest",
                    "expectation_count": stripped.count("expect("),
                    "matchers": list(matchers),
                    "source_key": state.current_suite_key or module_canonical_key,
                },
            )
        )

    for mock_match in JEST_MOCK_RE.finditer(stripped):
        add_framework_observation(
            _framework_observation(
                "jest.mock",
                relative_path,
                js_format,
                "jest",
                line_number,
                mock_match.group("kind"),
                module_canonical_key,
                metadata={
                    "test_framework": "jest",
                    "mock_kind": mock_match.group("kind"),
                },
            )
        )
