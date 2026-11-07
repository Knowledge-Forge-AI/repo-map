"""Filesystem integration tests for opt-in structural advisory freshness over SQLite and PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from common_lore_index.retrieval.advisory_freshness import FreshnessCheckConfig
from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_contracts import ContextRequest
from repomap_test_support.context_assertions import (
    assert_valid_context_packet,
    build_postgres_context_fixture,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    CTX_GRAPH_ID,
    SNAP_CORE,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_default_freshness_none_succeeds_after_local_source_tree_deleted(
    tmp_path: Path,
) -> None:
    """Verify --freshness none performs zero source reads even if local source directories are deleted."""
    _sq_path, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    shutil.rmtree(tmp_path / "src_core")
    shutil.rmtree(tmp_path / "src_docs")

    with adapter:
        pkt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent="definition",
                freshness="none",
            ),
            adapter,
        )
    assert_valid_context_packet(pkt)
    assert pkt["freshness"]["files_checked"] == 0
    assert pkt["freshness"]["bytes_read"] == 0
    assert all(
        loc["freshness"] is None
        for item in pkt["items"]
        for loc in item["locations"]
    )


def test_filesystem_freshness_across_sqlite_neighbors_and_postgres_seeds(
    tmp_path: Path,
) -> None:
    """Verify descriptor-anchored structural freshness across SQLite seeds+neighbors and PostgreSQL seeds."""
    require_postgres_binaries()
    extra_subjs = [
        {
            "canonical_key": "py:pkg.billing.LongSpan",
            "kind": "python.function",
            "display_name": "LongSpan",
            "raw_kind": "python.function",
            "binding_id": BINDING_CORE,
            "snapshot_id": SNAP_CORE,
            "path": "src/billing/long_span.py",
            "start_line": 1,
            "end_line": 95,
        }
    ]
    sq_dir = tmp_path / "sq"
    sq_dir.mkdir(parents=True, exist_ok=True)
    _sq_path, _cfg, _graph, _binding, sq_adapter = build_sqlite_context_fixture(
        sq_dir, extra_subjects=extra_subjs
    )
    core_root = sq_dir / "src_core"
    docs_root = sq_dir / "src_docs"

    # 1. Seed + depth-1 neighbor structural freshness on unchanged files
    with sq_adapter:
        pkt_ok = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
                intent="implementation",
                expand_depth=1,
                freshness="check",
                source_roots={BINDING_CORE: core_root, BINDING_DOCS: docs_root},
            ),
            sq_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True,
                source_roots={BINDING_CORE: core_root, BINDING_DOCS: docs_root},
            ),
        )
    assert_valid_context_packet(pkt_ok)
    assert pkt_ok["freshness"]["files_checked"] >= 1
    seed_f = pkt_ok["items"][0]["locations"][0]["freshness"]
    assert seed_f["state"] == "no_change_observed_with_limits"
    assert seed_f["reason"] == "structural_span_only_no_lexical_anchor"
    assert any(
        loc["freshness"] is not None
        and loc["freshness"]["state"] == "no_change_observed_with_limits"
        for nbr in pkt_ok["neighbors"]
        for loc in nbr["locations"]
    )

    # 2. Span > 80 lines skipped BEFORE opening file (files_checked == 0)
    with sq_adapter:
        pkt_long = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.LongSpan",
                freshness="check",
                source_roots={BINDING_CORE: core_root},
            ),
            sq_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: core_root}
            ),
        )
    assert_valid_context_packet(pkt_long)
    assert pkt_long["freshness"]["files_checked"] == 0
    assert pkt_long["items"][0]["locations"][0]["freshness"]["state"] == "not_checked"
    assert pkt_long["items"][0]["locations"][0]["freshness"]["reason"] == "line_limit"
    assert pkt_long["items"][0]["locations"][0]["freshness"]["inspected_span"] == {
        "start_line": 1,
        "end_line": 95,
    }

    # 3. Truncate invoice.py to 1 line -> changed_observed / span_beyond_eof, item preserved
    (core_root / "src/billing/invoice.py").write_text("# truncated\n", encoding="utf-8")
    with sq_adapter:
        pkt_trunc = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: core_root},
            ),
            sq_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: core_root}
            ),
        )
    assert_valid_context_packet(pkt_trunc)
    assert len(pkt_trunc["items"]) == 1
    assert pkt_trunc["items"][0]["locations"][0]["freshness"]["state"] == "changed_observed"
    assert pkt_trunc["items"][0]["locations"][0]["freshness"]["reason"] == "span_beyond_eof"

    # 4. Symlink replacement -> symlink_or_traversal_rejected
    outside = tmp_path / "outside_secret.py"
    outside.write_text("SECRET_OUTSIDE_CONTENT\n" * 10, encoding="utf-8")
    (core_root / "src/billing/invoice.py").unlink()
    (core_root / "src/billing/invoice.py").symlink_to(outside)
    with sq_adapter:
        pkt_sym = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: core_root},
            ),
            sq_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: core_root}
            ),
        )
    assert_valid_context_packet(pkt_sym, forbidden_substrings=("SECRET_OUTSIDE_CONTENT",))
    assert pkt_sym["items"][0]["locations"][0]["freshness"]["state"] == "unavailable"
    assert pkt_sym["items"][0]["locations"][0]["freshness"]["reason"] == "symlink_or_traversal_rejected"

    # 5. FIFO replacement -> unsafe_or_nonregular_file without blocking
    (core_root / "src/billing/invoice.py").unlink()
    os.mkfifo(core_root / "src/billing/invoice.py")
    with sq_adapter:
        pkt_fifo = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: core_root},
            ),
            sq_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: core_root}
            ),
        )
    assert_valid_context_packet(pkt_fifo)
    assert pkt_fifo["items"][0]["locations"][0]["freshness"]["state"] == "unavailable"
    assert pkt_fifo["items"][0]["locations"][0]["freshness"]["reason"] == "unsafe_or_nonregular_file"

    # 6. PostgreSQL packet with freshness=check on binary/NUL and >64 KiB files
    with temporary_postgres() as postgres:
        pg_dir = tmp_path / "pg"
        pg_dir.mkdir(parents=True, exist_ok=True)
        _pg_home, pg_adapter = build_postgres_context_fixture(pg_dir, postgres)
        pg_core = pg_dir / "src_core"
        (pg_core / "src/billing/invoice.py").write_bytes(b"class InvoiceService:\x00\n")
        pkt_bin = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: pg_core},
            ),
            pg_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: pg_core}
            ),
        )
        assert_valid_context_packet(pkt_bin)
        assert pkt_bin["items"][0]["locations"][0]["freshness"]["reason"] == "invalid_utf8"

        (pg_core / "src/billing/invoice.py").write_bytes(b"a = 1\n" * 12000)
        pkt_big = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="exact_identity",
                canonical_key="py:pkg.billing.InvoiceService",
                freshness="check",
                source_roots={BINDING_CORE: pg_core},
            ),
            pg_adapter,
            freshness=FreshnessCheckConfig(
                enabled=True, source_roots={BINDING_CORE: pg_core}
            ),
        )
        assert_valid_context_packet(pkt_big)
        assert pkt_big["items"][0]["locations"][0]["freshness"]["reason"] == "file_size_limit"
