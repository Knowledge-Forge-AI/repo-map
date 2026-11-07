"""Closed navigation intents, direct-evidence role SQL, and affinity tables (W4 Epic A §3.1-3.2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from common_lore_index.graph.edge_kinds import CANONICAL_EDGE_KINDS

INTENT_RANK_VERSION = "cloe-intent-rank-v1"
INTENT_TIEBREAK_VERSION = "cloe-intent-tiebreak-v1"
INTENT_TABLES_VERSION = "cloe-intent-tables-v1"
INTENT_RANKING_PROFILE = INTENT_RANK_VERSION
INTENT_TIE_BREAK_RULE_ID = INTENT_TIEBREAK_VERSION
INTENT_TABLE_VERSION = INTENT_TABLES_VERSION


class NavigationIntent(StrEnum):
    DEFINITION = "definition"
    IMPLEMENTATION = "implementation"
    TESTS = "tests"
    DOCS = "docs"
    MESSAGES = "messages"
    GENERAL = "general"


NAVIGATION_INTENTS: tuple[str, ...] = tuple(item.value for item in NavigationIntent)


@dataclass(frozen=True, slots=True)
class DirectEvidenceRuleSpec:
    """One declarative rule in CONTEXT_DIRECT_EVIDENCE_ROLE_V1."""

    family: str
    link_kinds: tuple[str, ...]
    subject_kinds: tuple[str, ...]
    raw_kinds: tuple[str, ...] | None = None

    def sql_predicate(self) -> str:
        if len(self.link_kinds) == 1:
            link_sql = f"link.link_kind = '{self.link_kinds[0]}'"
        else:
            joined_links = ", ".join(f"'{lk}'" for lk in self.link_kinds)
            link_sql = f"link.link_kind IN ({joined_links})"

        if len(self.subject_kinds) == 1:
            subj_sql = f"subject.kind = '{self.subject_kinds[0]}'"
        else:
            joined_subj = ", ".join(f"'{sk}'" for sk in self.subject_kinds)
            subj_sql = f"subject.kind IN ({joined_subj})"

        if self.raw_kinds is None:
            raw_sql = "e.raw_kind = subject.kind"
        elif len(self.raw_kinds) == 1:
            raw_sql = f"e.raw_kind = '{self.raw_kinds[0]}'"
        else:
            joined_raw = ", ".join(f"'{rk}'" for rk in self.raw_kinds)
            raw_sql = f"e.raw_kind IN ({joined_raw})"

        return f"({link_sql} AND {subj_sql} AND {raw_sql})"


DIRECT_EVIDENCE_RULE_SPECS_V1: tuple[DirectEvidenceRuleSpec, ...] = (
    DirectEvidenceRuleSpec(
        family="python_code",
        link_kinds=("observed",),
        subject_kinds=("python.module", "python.class", "python.function", "python.method"),
        raw_kinds=None,
    ),
    DirectEvidenceRuleSpec(
        family="doc_page", link_kinds=("observed",),
        subject_kinds=("doc.page",), raw_kinds=("markdown.document",),
    ),
    DirectEvidenceRuleSpec(
        family="doc_section", link_kinds=("observed",),
        subject_kinds=("doc.section",), raw_kinds=("markdown.heading",),
    ),
    DirectEvidenceRuleSpec(
        family="doc_adr", link_kinds=("observed",),
        subject_kinds=("doc.adr",), raw_kinds=("markdown.adr_metadata",),
    ),
    DirectEvidenceRuleSpec(
        family="doc_skill", link_kinds=("observed",),
        subject_kinds=("doc.skill",), raw_kinds=("markdown.skill_metadata",),
    ),
    DirectEvidenceRuleSpec(
        family="email_messages",
        link_kinds=("observed",),
        subject_kinds=(
            "email.mailbox", "email.message", "email.part",
            "email.attachment_stub", "email.thread_hint", "email.address",
        ),
        raw_kinds=None,
    ),
    DirectEvidenceRuleSpec(
        family="feed_messages",
        link_kinds=("observed",),
        subject_kinds=("feed.document", "feed.channel", "feed.item", "feed.author", "feed.category"),
        raw_kinds=None,
    ),
    DirectEvidenceRuleSpec(
        family="explicit_test_observed",
        link_kinds=("observed",),
        subject_kinds=(
            "js.test_suite", "js.test_case", "ruby.test_case", "ruby.test_method",
            "bats.file", "zunit.file", "zunit.command_under_test", "nix.check",
        ),
        raw_kinds=None,
    ),
    DirectEvidenceRuleSpec(
        family="shell_test_children",
        link_kinds=("observed", "inferred_from_edge"),
        subject_kinds=(
            "bats.test_case", "zunit.suite", "zunit.test_case", "zunit.assertion",
            "zunit.expectation", "zunit.mock", "zunit.stub",
            "zunit.command_under_test", "nix.check",
        ),
        raw_kinds=None,
    ),
    DirectEvidenceRuleSpec(
        family="bats_expectation",
        link_kinds=("observed", "inferred_from_edge"),
        subject_kinds=("bats.expectation",),
        raw_kinds=("bats.assertion", "bats.refutation"),
    ),
    DirectEvidenceRuleSpec(
        family="zunit_hook",
        link_kinds=("observed", "inferred_from_edge"),
        subject_kinds=("zunit.hook",),
        raw_kinds=(
            "zunit.setup", "zunit.teardown", "zunit.before_each",
            "zunit.after_each", "zunit.hook",
        ),
    ),
)


def build_context_direct_evidence_role_sql(
    rules: Sequence[DirectEvidenceRuleSpec] = DIRECT_EVIDENCE_RULE_SPECS_V1,
) -> str:
    """Build CASE expression evaluating direct rules before inferred_from_edge fallback."""
    direct_branches = "\n        OR ".join(rule.sql_predicate() for rule in rules)
    return (
        "CASE\n"
        f"    WHEN (\n        {direct_branches}\n    ) THEN 'direct'\n"
        "    WHEN link.link_kind = 'inferred_from_edge' THEN 'reference'\n"
        "    ELSE 'unknown' END"
    )


CONTEXT_DIRECT_EVIDENCE_ROLE_V1: str = build_context_direct_evidence_role_sql()

DIRECT_LOCATABLE_CANONICAL_KINDS_V1: frozenset[str] = frozenset(
    kind for rule in DIRECT_EVIDENCE_RULE_SPECS_V1 for kind in rule.subject_kinds
)


def evaluate_context_evidence_role(
    *, link_kind: str, subject_kind: str, raw_kind: str
) -> str:
    """Pure-Python mirror of CONTEXT_DIRECT_EVIDENCE_ROLE_V1 for parity tests."""
    for rule in DIRECT_EVIDENCE_RULE_SPECS_V1:
        if link_kind not in rule.link_kinds or subject_kind not in rule.subject_kinds:
            continue
        if rule.raw_kinds is None:
            if raw_kind == subject_kind:
                return "direct"
        elif raw_kind in rule.raw_kinds:
            return "direct"
    if link_kind == "inferred_from_edge":
        return "reference"
    return "unknown"


_PYTHON_CODE_KINDS: frozenset[str] = frozenset(
    {"python.module", "python.class", "python.function", "python.method"}
)

_CODE_AFFINITY_PATTERNS: tuple[str, ...] = (
    "python.module", "python.class", "python.function", "python.method",
    "go.*", "js.file", "js.module", "js.function", "js.class", "js.method",
    "js.component", "js.route", "ruby.file", "ruby.module", "ruby.class",
    "ruby.method", "ruby.singleton_method", "ruby.constant", "ruby.route",
    "bash.*", "zsh.*", "awk.*", "powershell.*", "nix.app", "nix.package",
    "nix.devShell", "config.*", "css.*", "html.*", "xml.*",
)

_TEST_AFFINITY_PATTERNS: tuple[str, ...] = (
    "python_test_subject", "bats.file", "bats.test_case", "bats.expectation",
    "zunit.file", "zunit.suite", "zunit.test_case", "zunit.hook",
    "zunit.assertion", "zunit.expectation", "zunit.command_under_test",
    "zunit.mock", "zunit.stub", "js.test_suite", "js.test_case",
    "ruby.test_case", "ruby.test_method", "nix.check",
)

_DOC_AFFINITY_PATTERNS: tuple[str, ...] = (
    "doc.page", "doc.section", "doc.adr", "doc.skill",
)

_MESSAGE_AFFINITY_PATTERNS: tuple[str, ...] = (
    "email.mailbox", "email.message", "email.part", "email.attachment_stub",
    "email.thread_hint", "email.address", "feed.document", "feed.channel",
    "feed.item", "feed.author", "feed.category",
)

INTENT_AFFINITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "definition": _CODE_AFFINITY_PATTERNS,
    "implementation": _CODE_AFFINITY_PATTERNS,
    "tests": _TEST_AFFINITY_PATTERNS,
    "docs": _DOC_AFFINITY_PATTERNS,
    "messages": _MESSAGE_AFFINITY_PATTERNS,
    "general": ("*",),
}


def _matches_pattern(kind: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return kind.startswith(pattern[:-1])
    return kind == pattern


def _is_test_path(path_str: str) -> bool:
    posix = PurePosixPath(path_str)
    if any(part in {"test", "tests"} for part in posix.parts[:-1]):
        return True
    name = posix.name
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.py")


def _extract_symbol_tail(canonical_key: str) -> str:
    tail = canonical_key
    for sep in (":", "#", "/", "."):
        if sep in tail:
            tail = tail.rsplit(sep, 1)[-1]
    return tail


def classify_subject_intent_family(
    kind: str,
    canonical_key: str = "",
    verified_direct_locations: Sequence[Mapping[str, Any]] = (),
    *,
    display_name: str | None = None,
    source_relative_path: str | None = None,
) -> str:
    """Classify a candidate node into its deterministic W4 subject family."""
    if kind in _PYTHON_CODE_KINDS:
        if isinstance(source_relative_path, str) and _is_test_path(source_relative_path):
            return "python_test_subject"
        for loc in verified_direct_locations:
            rel = loc.get("source_relative_path") or loc.get("path")
            if isinstance(rel, str) and _is_test_path(rel):
                return "python_test_subject"
        symbol = display_name or _extract_symbol_tail(canonical_key)
        if kind in {"python.function", "python.method"} and symbol.startswith("test_"):
            return "python_test_subject"
        if kind == "python.class" and symbol.startswith("Test"):
            return "python_test_subject"
        return "code_definition"
    if kind in _DOC_AFFINITY_PATTERNS:
        return "doc_artifact"
    if kind in _MESSAGE_AFFINITY_PATTERNS:
        return "message_artifact"
    if kind in _TEST_AFFINITY_PATTERNS:
        return "test_subject"
    if any(_matches_pattern(kind, p) for p in _CODE_AFFINITY_PATTERNS):
        return "code_definition"
    return "other"


def compute_affinity_tier(
    intent: str | None, kind: str, subject_family: str
) -> tuple[int, str]:
    """Return (affinity_tier, explanation_code) with no universal test penalty."""
    if intent is None or intent == "general":
        return 1, "intent_kind_neutral"
    if intent in {"definition", "implementation"}:
        if subject_family == "python_test_subject":
            return 1, "intent_kind_neutral"
        if any(_matches_pattern(kind, p) for p in _CODE_AFFINITY_PATTERNS):
            return 0, "intent_kind_affine"
        return 1, "intent_kind_neutral"
    if intent == "tests":
        if subject_family == "python_test_subject" or kind in _TEST_AFFINITY_PATTERNS:
            return 0, "intent_kind_affine"
        return 1, "intent_kind_neutral"
    if intent == "docs":
        return (0, "intent_kind_affine") if kind in _DOC_AFFINITY_PATTERNS else (1, "intent_kind_neutral")
    if intent == "messages":
        return (0, "intent_kind_affine") if kind in _MESSAGE_AFFINITY_PATTERNS else (1, "intent_kind_neutral")
    return 1, "intent_kind_neutral"


_DEF_IMPL_EDGES: tuple[str, ...] = (
    "calls", "contains", "declares", "defines", "depends_on", "exposes_script",
    "imports", "includes", "loads", "method_of", "references", "replaces_module",
    "requires_module", "sources", "workspace_uses",
)

INTENT_DEFAULT_EDGE_KINDS: dict[str, tuple[str, ...]] = {
    "definition": _DEF_IMPL_EDGES,
    "implementation": _DEF_IMPL_EDGES,
    "tests": (
        "asserts", "command_under_test", "contains", "defines", "expects",
        "has_assertion", "has_hook", "has_test_case", "imports", "loads",
        "references", "refutes", "tests_command", "uses_fixture",
        "uses_helper", "uses_mock", "uses_stub",
    ),
    "docs": ("contains", "defines", "embeds", "links_to", "references", "styles"),
    "messages": ("defines", "references"),
    "general": tuple(sorted(CANONICAL_EDGE_KINDS)),
}

for _intent_key, _edge_tuple in INTENT_DEFAULT_EDGE_KINDS.items():
    if not _edge_tuple or not set(_edge_tuple).issubset(CANONICAL_EDGE_KINDS):
        raise RuntimeError(f"invalid default edge kinds for {_intent_key}")


def unlocatable_patterns(
    intent: str | None,
    kinds: Sequence[str] = (),
    *,
    scoped: bool = True,
) -> tuple[tuple[str, ...], bool]:
    """Return (sorted_excluded_pattern_tokens, all_requested_kinds_unlocatable)."""
    if not scoped:
        return (), False
    if kinds:
        unique = sorted(set(kinds))
        excluded = tuple(k for k in unique if k not in DIRECT_LOCATABLE_CANONICAL_KINDS_V1)
        return excluded, len(excluded) == len(unique)
    tokens = ("*",) if intent in (None, "general") else INTENT_AFFINITY_PATTERNS.get(intent or "general", ("*",))
    excluded_tokens: set[str] = set()
    for token in tokens:
        if token == "python_test_subject":
            if not _PYTHON_CODE_KINDS.issubset(DIRECT_LOCATABLE_CANONICAL_KINDS_V1):
                excluded_tokens.add(token)
        elif token == "*" or token.endswith(".*"):
            excluded_tokens.add(token)
        elif token not in DIRECT_LOCATABLE_CANONICAL_KINDS_V1:
            excluded_tokens.add(token)
    return tuple(sorted(excluded_tokens)), False
