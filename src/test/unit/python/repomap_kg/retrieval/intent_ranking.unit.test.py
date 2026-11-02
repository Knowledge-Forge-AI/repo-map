"""Unit tests for W4 intent_ranking (Epic A §3.3)."""

from __future__ import annotations

from common_lore_index.retrieval.intent_ranking import (
    CandidateRankingInput,
    classify_match_class,
    first_verified_destination_tuple,
    order_candidates_canonical_key_asc,
    rank_candidates,
)


def _cand(
    ck: str,
    kind: str,
    dn: str | None,
    family: str,
    *,
    has_direct: bool = True,
    has_verified: bool = True,
    withheld: bool = False,
    current_pub: bool = True,
    path: str = "src/a.py",
) -> CandidateRankingInput:
    dest_tuple = first_verified_destination_tuple(
        [
            {
                "source_binding_id": "bind1:core",
                "binding_revision": 1,
                "snapshot_id": "snap1:11",
                "source_relative_path": path,
                "run_id": 1,
                "publication_relation": "accepted_run",
                "path_namespace": "source_relative",
                "graph_path": f"core/{path}",
                "start_line": 1,
                "end_line": 5,
            }
        ]
        if has_verified
        else []
    )
    return CandidateRankingInput(
        canonical_key=ck,
        kind=kind,
        display_name=dn,
        subject_family=family,
        has_direct_evidence=has_direct,
        has_verified_direct_location=has_verified,
        identity_withheld=withheld,
        is_current_publication=current_pub,
        first_verified_destination=dest_tuple,
    )


def test_classify_match_class_all_seven_tiers() -> None:
    assert classify_match_class(
        query_text="InvoiceService",
        canonical_key="py:pkg.InvoiceService",
        display_name="InvoiceService",
    ) == (0, "display_exact")
    assert classify_match_class(
        query_text="invoiceservice",
        canonical_key="py:pkg.InvoiceService",
        display_name="InvoiceService",
    ) == (1, "display_casefold_exact")
    assert classify_match_class(
        query_text="InvoiceService",
        canonical_key="py:pkg.InvoiceService",
        display_name="Other Label",
    ) == (2, "key_terminal_exact")
    assert classify_match_class(
        query_text="Invoice",
        canonical_key="py:pkg.InvoiceService",
        display_name="InvoiceService",
    ) == (3, "display_prefix")
    assert classify_match_class(
        query_text="Service",
        canonical_key="py:pkg.x",
        display_name="MyInvoiceService",
    ) == (4, "display_substring")
    assert classify_match_class(
        query_text="billing",
        canonical_key="py:pkg.billing.Invoice",
        display_name="Invoice",
    ) == (5, "key_substring")
    assert classify_match_class(
        query_text="",
        canonical_key="py:pkg.billing.Invoice",
        display_name="Invoice",
    ) == (6, "kind_only")


def test_six_tier_lexicographic_ordering_and_intent_switching() -> None:
    c_code = _cand(
        "py:pkg.InvoiceService", "python.class", "InvoiceService", "code_definition"
    )
    c_test = _cand(
        "bats.test_case:t#InvoiceService", "bats.test_case", "InvoiceService", "test_subject"
    )
    c_doc = _cand(
        "doc:adr/InvoiceService", "doc.adr", "InvoiceService", "doc_artifact"
    )

    ranked_def, amb_def = rank_candidates(
        [c_test, c_doc, c_code], query="InvoiceService", intent="definition"
    )
    assert [r.candidate.canonical_key for r in ranked_def] == [
        "py:pkg.InvoiceService",
        "bats.test_case:t#InvoiceService",
        "doc:adr/InvoiceService",
    ]
    assert amb_def.status == "unambiguous"

    ranked_docs, _ = rank_candidates(
        [c_test, c_doc, c_code], query="InvoiceService", intent="docs"
    )
    assert ranked_docs[0].candidate.canonical_key == "doc:adr/InvoiceService"

    ranked_tests, _ = rank_candidates(
        [c_test, c_doc, c_code], query="InvoiceService", intent="tests"
    )
    assert ranked_tests[0].candidate.canonical_key == "bats.test_case:t#InvoiceService"


def test_evidence_publication_and_tiebreak_tiers() -> None:
    c_ver = _cand("py:b", "python.class", "Target", "code_definition", has_verified=True)
    c_unver = _cand(
        "py:a", "python.class", "Target", "code_definition", has_verified=False, has_direct=True
    )
    c_withheld = _cand(
        "py:0", "python.class", "Target", "code_definition", has_verified=False, withheld=True
    )
    c_hist = _cand(
        "py:aa", "python.class", "Target", "code_definition", has_verified=True, current_pub=False
    )

    ranked, amb = rank_candidates(
        [c_withheld, c_unver, c_hist, c_ver], query="Target", intent="definition"
    )
    assert [r.candidate.canonical_key for r in ranked] == [
        "py:b",
        "py:aa",
        "py:a",
        "py:0",
    ]
    assert amb.status == "ambiguous"
    assert amb.tied_top_count == 4


def test_ambiguity_and_canonical_key_asc_ordering() -> None:
    c1 = _cand("py:pkg.b.Handler", "python.class", "Handler", "code_definition", path="b.py")
    c2 = _cand("py:pkg.a.Handler", "python.class", "Handler", "code_definition", path="a.py")
    ranked, amb = rank_candidates([c1, c2], query="Handler", intent="definition")
    assert [r.candidate.canonical_key for r in ranked] == [
        "py:pkg.a.Handler",
        "py:pkg.b.Handler",
    ]
    assert amb.status == "ambiguous"
    assert amb.tied_top_count == 2

    asc, asc_amb = order_candidates_canonical_key_asc([c1, c2])
    assert [r.candidate.canonical_key for r in asc] == [
        "py:pkg.a.Handler",
        "py:pkg.b.Handler",
    ]
    assert asc_amb.status == "unambiguous"
