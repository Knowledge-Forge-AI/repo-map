"""Unit tests for W4 advisory_freshness (Epic C §5.2)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import unicodedata

from common_lore_index.retrieval.advisory_freshness import (
    FreshnessCheckConfig,
    evaluate_packet_freshness,
    is_valid_freshness_relative_path,
    reserve_freshness_observation,
)
from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.context_fixture import BINDING_CORE, BINDING_DOCS, build_sqlite_context_fixture
from portable_handoff import _relative as handoff_relative


def test_relative_path_grammar_parity_with_portable_handoff() -> None:
    nfd = unicodedata.normalize("NFD", "café/résumé.py")
    nfc = unicodedata.normalize("NFC", "café/résumé.py")
    samples = (
        "src/billing/invoice.py",
        "README.md",
        nfd,
        nfc,
        "",
        ".",
        "..",
        "../secret.py",
        "src/../../secret.py",
        "/etc/passwd",
        "src//invoice.py",
        "src/./invoice.py",
        "src\\invoice.py",
        "bad\x00name.py",
        "bad\nname.py",
    )
    for sample in samples:
        try:
            handoff_relative(sample)
            handoff_ok = True
        except Exception:
            handoff_ok = False
        assert is_valid_freshness_relative_path(sample) == handoff_ok, f"mismatch on {sample!r}"


def test_worst_case_reservation_never_grows_on_actual_observation(tmp_path: Path) -> None:
    reserved = reserve_freshness_observation({"start_line": 1, "end_line": 6})
    res_bytes = len(serialize_compact_json(reserved))
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    pkt = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="InvoiceService",
            intent="definition",
            expand_depth=1,
            freshness="check",
            source_roots={
                BINDING_CORE: tmp_path / "src_core",
                BINDING_DOCS: tmp_path / "src_docs",
            },
        ),
        adapter,
    )
    assert_valid_context_packet(pkt)
    assert pkt["freshness"]["state"] == "checked"
    assert pkt["freshness"]["files_checked"] >= 1
    for item in (*pkt["items"], *pkt["neighbors"]):
        for loc in item["locations"]:
            if loc["freshness"] is not None:
                obs_bytes = len(serialize_compact_json(loc["freshness"]))
                loc_res_bytes = len(serialize_compact_json(reserve_freshness_observation(loc)))
                assert obs_bytes <= loc_res_bytes
                assert res_bytes > 0


def test_structural_only_no_lexical_anchor_and_line_limit_before_open(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    # Overwrite src/billing/invoice.py with 6 lines that do NOT contain "InvoiceService"
    # Structural-only v1 must report no_change_observed_with_limits, never false drift!
    inv_path = tmp_path / "src_core" / "src/billing/invoice.py"
    inv_path.write_text("line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n", encoding="utf-8")

    pkt = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="exact_identity",
            canonical_key="py:pkg.billing.InvoiceService",
            freshness="check",
            source_roots={BINDING_CORE: tmp_path / "src_core"},
        ),
        adapter,
    )
    assert_valid_context_packet(pkt)
    obs = pkt["items"][0]["locations"][0]["freshness"]
    assert obs == {
        "state": "no_change_observed_with_limits",
        "reason": "structural_span_only_no_lexical_anchor",
        "limits": ["structural_span_only", "no_lexical_anchor", "no_body_text"],
        "inspected_span": {"start_line": 1, "end_line": 6},
    }

    # Span > 80 lines is rejected with not_checked/line_limit BEFORE opening any source file
    pkt["items"][0]["locations"][0]["start_line"] = 1
    pkt["items"][0]["locations"][0]["end_line"] = 95
    evaluate_packet_freshness(
        pkt,
        FreshnessCheckConfig(enabled=True, source_roots={BINDING_CORE: tmp_path / "src_core"}),
    )
    assert pkt["freshness"]["files_checked"] == 0
    assert pkt["items"][0]["locations"][0]["freshness"]["state"] == "not_checked"
    assert pkt["items"][0]["locations"][0]["freshness"]["reason"] == "line_limit"


def test_changed_observed_and_descriptor_anchored_symlink_rejection(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    inv_path = tmp_path / "src_core" / "src/billing/invoice.py"

    # Truncate file to 2 lines -> span 1..6 is span_beyond_eof
    inv_path.write_text("only_one\nonly_two\n", encoding="utf-8")
    pkt_eof = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="exact_identity",
            canonical_key="py:pkg.billing.InvoiceService",
            freshness="check",
            source_roots={BINDING_CORE: tmp_path / "src_core"},
        ),
        adapter,
    )
    assert pkt_eof["items"][0]["locations"][0]["freshness"]["state"] == "changed_observed"
    assert pkt_eof["items"][0]["locations"][0]["freshness"]["reason"] == "span_beyond_eof"

    # Replace file with symlink to outside secret -> unavailable/symlink_rejected, item preserved
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("TOP_SECRET_OUTSIDE_CONTENT\n" * 10, encoding="utf-8")
    inv_path.unlink()
    inv_path.symlink_to(outside)
    pkt_sym = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="exact_identity",
            canonical_key="py:pkg.billing.InvoiceService",
            freshness="check",
            source_roots={BINDING_CORE: tmp_path / "src_core"},
        ),
        adapter,
    )
    assert_valid_context_packet(pkt_sym, forbidden_substrings=("TOP_SECRET_OUTSIDE_CONTENT",))
    assert len(pkt_sym["items"]) == 1
    assert pkt_sym["items"][0]["locations"][0]["freshness"]["state"] == "unavailable"
    assert pkt_sym["items"][0]["locations"][0]["freshness"]["reason"] == "symlink_or_traversal_rejected"

    # Component swap mid-traversal via step_hook
    inv_path.unlink()
    inv_path.write_text("line1\n" * 10, encoding="utf-8")
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "invoice.py").write_text("OUTSIDE_SWAP_SECRET\n" * 10, encoding="utf-8")

    def _swap_hook(step: str) -> None:
        if step == "billing":
            billing_dir = tmp_path / "src_core" / "src/billing"
            if billing_dir.is_dir() and not billing_dir.is_symlink():
                shutil.rmtree(billing_dir)
                os.symlink(outside_dir, billing_dir)

    pkt_swap = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="exact_identity",
            canonical_key="py:pkg.billing.InvoiceService",
            freshness="check",
            source_roots={BINDING_CORE: tmp_path / "src_core"},
        ),
        adapter,
        freshness_step_hook=_swap_hook,
    )
    assert_valid_context_packet(pkt_swap, forbidden_substrings=("OUTSIDE_SWAP_SECRET",))
    assert pkt_swap["items"][0]["locations"][0]["freshness"]["state"] == "unavailable"
    assert pkt_swap["items"][0]["locations"][0]["freshness"]["reason"] == "symlink_or_traversal_rejected"
