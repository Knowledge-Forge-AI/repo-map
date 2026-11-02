"""Unit tests for W4 intent_policy (Epic A §3.1-3.2)."""

from __future__ import annotations

import sqlite3

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
