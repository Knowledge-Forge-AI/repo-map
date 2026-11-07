"""Unit tests for W4 intent_policy (Epic A §3.1-3.2)."""

from __future__ import annotations

import sqlite3

import pytest

from common_lore_index.graph.edge_kinds import CANONICAL_EDGE_KINDS
from common_lore_index.retrieval.intent_policy import (
    CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
    DIRECT_EVIDENCE_RULE_SPECS_V1,
    DIRECT_LOCATABLE_CANONICAL_KINDS_V1,
    INTENT_DEFAULT_EDGE_KINDS,
    NAVIGATION_INTENTS,
    classify_subject_intent_family,
    compute_affinity_tier,
    evaluate_context_evidence_role,
    unlocatable_patterns,
    DirectEvidenceRuleSpec,
    build_context_direct_evidence_role_sql,
)


def test_navigation_intents_and_canonical_edge_subsets() -> None:
    assert NAVIGATION_INTENTS == (
        "definition", "implementation", "tests", "docs", "messages", "general",
    )
    for intent in NAVIGATION_INTENTS:
        edges = INTENT_DEFAULT_EDGE_KINDS[intent]
        assert len(edges) > 0
        assert set(edges).issubset(CANONICAL_EDGE_KINDS)
    assert "contains" in INTENT_DEFAULT_EDGE_KINDS["tests"]
    assert set(INTENT_DEFAULT_EDGE_KINDS["messages"]) == {"defines", "references"}


def test_direct_locatable_canonical_kinds_derived_and_sql_parity() -> None:
    expected = {k for r in DIRECT_EVIDENCE_RULE_SPECS_V1 for k in r.subject_kinds}
    assert DIRECT_LOCATABLE_CANONICAL_KINDS_V1 == expected
    for must_have in (
        "python.class", "doc.adr", "doc.skill", "email.message", "email.address",
        "feed.item", "bats.test_case", "bats.expectation", "zunit.test_case",
        "zunit.hook", "zunit.command_under_test", "nix.check",
    ):
        assert must_have in DIRECT_LOCATABLE_CANONICAL_KINDS_V1
    assert "tool" not in DIRECT_LOCATABLE_CANONICAL_KINDS_V1

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE subject (kind TEXT)")
    conn.execute("CREATE TABLE e (raw_kind TEXT)")
    conn.execute("CREATE TABLE link (link_kind TEXT)")
    cases = (
        ("observed", "python.class", "python.class", "direct"),
        ("observed", "doc.adr", "markdown.adr_metadata", "direct"),
        ("observed", "doc.skill", "markdown.skill_metadata", "direct"),
        ("inferred_from_edge", "bats.test_case", "bats.test_case", "direct"),
        ("inferred_from_edge", "bats.expectation", "bats.assertion", "direct"),
        ("inferred_from_edge", "zunit.hook", "zunit.setup", "direct"),
        ("inferred_from_edge", "nix.check", "nix.check", "direct"),
        ("inferred_from_edge", "python.class", "python.class", "reference"),
        ("observed", "tool", "file", "unknown"),
    )
    for lk, sk, rk, expected_role in cases:
        conn.execute("DELETE FROM subject")
        conn.execute("DELETE FROM e")
        conn.execute("DELETE FROM link")
        conn.execute("INSERT INTO subject VALUES (?)", (sk,))
        conn.execute("INSERT INTO e VALUES (?)", (rk,))
        conn.execute("INSERT INTO link VALUES (?)", (lk,))
        sql_role = conn.execute(
            f"SELECT {CONTEXT_DIRECT_EVIDENCE_ROLE_V1} FROM subject, e, link"
        ).fetchone()[0]
        py_role = evaluate_context_evidence_role(
            link_kind=lk, subject_kind=sk, raw_kind=rk
        )
        assert sql_role == py_role == expected_role
    conn.close()


def test_subject_intent_family_and_affinity_tiers() -> None:
    f_test = classify_subject_intent_family(
        "python.function",
        "py:tests.test_billing.test_total",
        source_relative_path="tests/test_billing.py",
    )
    assert f_test == "python_test_subject"
    assert compute_affinity_tier("tests", "python.function", f_test) == (
        0, "intent_kind_affine"
    )
    assert compute_affinity_tier("definition", "python.function", f_test) == (
        1, "intent_kind_neutral"
    )

    f_code = classify_subject_intent_family(
        "python.class",
        "py:pkg.billing.InvoiceService",
        source_relative_path="src/billing/invoice.py",
    )
    assert f_code == "code_definition"
    assert compute_affinity_tier("definition", "python.class", f_code) == (
        0, "intent_kind_affine"
    )
    assert compute_affinity_tier("implementation", "python.class", f_code) == (
        0, "intent_kind_affine"
    )

    f_doc = classify_subject_intent_family("doc.adr", "doc:adr/0010")
    assert f_doc == "doc_artifact"
    assert compute_affinity_tier("docs", "doc.adr", f_doc) == (0, "intent_kind_affine")
    assert compute_affinity_tier("docs", "doc.other", "other") == (
        1, "intent_kind_neutral"
    )


def test_unlocatable_patterns_for_scoped_requests() -> None:
    assert unlocatable_patterns("definition", (), scoped=False) == ((), False)

    for closed_intent in ("docs", "tests", "messages"):
        excl, all_unloc = unlocatable_patterns(closed_intent, (), scoped=True)
        assert excl == ()
        assert not all_unloc

    gen_excl, gen_unloc = unlocatable_patterns("general", (), scoped=True)
    assert gen_excl == ("*",)
    assert not gen_unloc

    def_excl, def_unloc = unlocatable_patterns("definition", (), scoped=True)
    assert "go.*" in def_excl and "python.class" not in def_excl
    assert not def_unloc

    tool_excl, tool_unloc = unlocatable_patterns("definition", ("tool",), scoped=True)
    assert tool_excl == ("tool",)
    assert tool_unloc


def test_direct_rule_sql_uses_closed_single_and_multi_value_predicates() -> None:
    single = DirectEvidenceRuleSpec(
        family="single", link_kinds=("observed",), subject_kinds=("python.class",), raw_kinds=("python.class",)
    )
    multi = DirectEvidenceRuleSpec(
        family="multi", link_kinds=("observed", "inferred_from_edge"),
        subject_kinds=("bats.expectation", "zunit.hook"), raw_kinds=None,
    )
    assert "link.link_kind = 'observed'" in single.sql_predicate()
    assert "subject.kind = 'python.class'" in single.sql_predicate()
    assert "e.raw_kind = 'python.class'" in single.sql_predicate()
    sql = build_context_direct_evidence_role_sql((single, multi))
    assert "link.link_kind IN ('observed', 'inferred_from_edge')" in sql
    assert "subject.kind IN ('bats.expectation', 'zunit.hook')" in sql
    assert "e.raw_kind = subject.kind" in sql
    assert "ELSE 'unknown'" in sql


@pytest.mark.parametrize(
    ("kind", "key", "display", "path", "expected"),
    [
        ("python.function", "py:pkg.test_total", "total", "src/test_billing.py", "python_test_subject"),
        ("python.function", "py:pkg.total", "test_total", None, "python_test_subject"),
        ("python.class", "py:pkg.TestBilling", "Billing", None, "code_definition"),
        ("python.class", "py:pkg.TestBilling", None, None, "python_test_subject"),
        ("python.class", "py:pkg.Billing", "Billing", "src/billing.py", "code_definition"),
        ("doc.page", "doc:README", "README", None, "doc_artifact"),
        ("email.message", "mail:1", "Subject", None, "message_artifact"),
        ("bats.test_case", "bats:case", "case", None, "test_subject"),
        ("css.selector", "css:.button", ".button", None, "code_definition"),
        ("mystery", "mystery:1", "Mystery", None, "other"),
    ],
)
def test_subject_family_uses_kind_symbol_and_verified_path(
    kind: str, key: str, display: str | None, path: str | None, expected: str,
) -> None:
    assert classify_subject_intent_family(
        kind, key, display_name=display, source_relative_path=path,
    ) == expected


@pytest.mark.parametrize(
    ("intent", "kind", "family", "expected"),
    [
        (None, "python.class", "code_definition", (1, "intent_kind_neutral")),
        ("general", "python.class", "code_definition", (1, "intent_kind_neutral")),
        ("definition", "doc.page", "doc_artifact", (1, "intent_kind_neutral")),
        ("definition", "python.function", "python_test_subject", (1, "intent_kind_neutral")),
        ("implementation", "python.function", "code_definition", (0, "intent_kind_affine")),
        ("tests", "python.class", "code_definition", (1, "intent_kind_neutral")),
        ("tests", "python.class", "python_test_subject", (0, "intent_kind_affine")),
        ("docs", "doc.adr", "doc_artifact", (0, "intent_kind_affine")),
        ("messages", "email.message", "message_artifact", (0, "intent_kind_affine")),
        ("messages", "python.class", "code_definition", (1, "intent_kind_neutral")),
        ("unrecognized", "python.class", "code_definition", (1, "intent_kind_neutral")),
    ],
)
def test_affinity_tiers_cover_each_navigation_intent_branch(
    intent: str | None, kind: str, family: str, expected: tuple[int, str],
) -> None:
    assert compute_affinity_tier(intent, kind, family) == expected


def test_unlocatable_patterns_distinguishes_partial_and_all_explicit_kinds() -> None:
    excluded, all_unlocatable = unlocatable_patterns(
        "general", ("tool", "python.class"), scoped=True,
    )
    assert excluded == ("tool",)
    assert all_unlocatable is False
    excluded, all_unlocatable = unlocatable_patterns("general", ("tool",), scoped=True)
    assert excluded == ("tool",)
    assert all_unlocatable is True
    assert unlocatable_patterns("definition", (), scoped=False) == ((), False)
