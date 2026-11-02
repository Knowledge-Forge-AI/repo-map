"""Unit tests for W4 source_selection (Epic C §5.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from dataclasses import replace

import pytest

from common_lore_index.retrieval.context_assembly import (
    build_compact_context,
    select_context_sources,
)
from common_lore_index.retrieval.context_contracts import (
    ContextRequest,
    ContextRequestError,
    ExpectedPublicationPin,
)
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.retrieval.source_selection import (
    MAX_SELECTION_FILE_BYTES,
    SourceBindingSelection,
    SourceSelectionRecord,
    read_selection_file,
    revalidate_selection_record,
    write_selection_file,
)
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    SNAP_CORE,
    build_sqlite_context_fixture,
)


def _sample_record(pin_pub: bool = True) -> SourceSelectionRecord:
    pin = (
        ExpectedPublicationPin(
            accepted_run_id=1,
            publication_bundle_id="bundle1:" + "c3" * 32,
            snapshot_manifest_id="manifest1:" + "a1" * 32,
            generation=1,
            job_id="job-ctx-1",
            attempt=1,
            extraction_receipt_id="receipt1:" + "b2" * 32,
        )
        if pin_pub
        else None
    )
    return SourceSelectionRecord.build(
        graph_id="polyglot-ctx",
        repository_id="repo1:polyglot-ctx",
        backend="sqlite",
        bindings=(
            SourceBindingSelection(
                binding_id=BINDING_CORE,
                revision=1,
                snapshot_id=SNAP_CORE if pin_pub else None,
                selection_policy_id="select1:pol",
                source_definition_id="src1:core",
                path_prefixes=("src/billing",),
            ),
        ),
        expected_publication=pin,
    )


def test_selection_record_fingerprint_sensitivity_and_strict_types(tmp_path: Path) -> None:
    rec1 = _sample_record(pin_pub=True)
    assert rec1.selection_fingerprint.startswith("select_ctx1:")
    assert len(rec1.selection_fingerprint) == len("select_ctx1:") + 64

    # Changing repository_id or any field changes fingerprint
    rec_repo = SourceSelectionRecord.build(
        graph_id=rec1.graph_id,
        repository_id="repo1:other",
        backend=rec1.backend,
        bindings=rec1.bindings,
        expected_publication=rec1.expected_publication,
    )
    assert rec_repo.selection_fingerprint != rec1.selection_fingerprint

    # Tampered fingerprint is rejected on read
    tampered_path = tmp_path / "tampered.json"
    d = rec1.to_dict()
    d["selection_fingerprint"] = "select_ctx1:" + "0" * 64
    tampered_path.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ContextRequestError) as exc:
        read_selection_file(tampered_path)
    assert exc.value.refusal_reason == "selection_fingerprint_mismatch"

    # Unknown top-level key rejected with invalid_selection_record
    unk_path = tmp_path / "unk.json"
    d_unk = rec1.to_dict()
    d_unk["trusted_caller"] = True
    unk_path.write_text(json.dumps(d_unk), encoding="utf-8")
    with pytest.raises(ContextRequestError) as exc2:
        read_selection_file(unk_path)
    assert exc2.value.refusal_reason == "invalid_selection_record"


def test_selection_file_write_o_excl_0600_and_read_guards(tmp_path: Path) -> None:
    rec = _sample_record(pin_pub=True)
    out_file = tmp_path / "sel.json"
    write_selection_file(rec, out_file)
    mode = stat.S_IMODE(os.lstat(out_file).st_mode)
    assert mode == 0o600

    # Second write refuses with selection_output_exists
    with pytest.raises(ContextRequestError) as exc:
        write_selection_file(rec, out_file)
    assert exc.value.refusal_reason == "selection_output_exists"

    loaded = read_selection_file(out_file)
    assert loaded == rec

    # Symlink rejected
    sym = tmp_path / "sym.json"
    sym.symlink_to(out_file)
    with pytest.raises(ContextRequestError) as exc_sym:
        read_selection_file(sym)
    assert exc_sym.value.refusal_reason == "invalid_selection_record"

    # Oversized file (> 64 KiB) rejected
    big = tmp_path / "big.json"
    big.write_bytes(b"{" + b" " * (MAX_SELECTION_FILE_BYTES + 10) + b"}")
    with pytest.raises(ContextRequestError) as exc_big:
        read_selection_file(big)
    assert exc_big.value.refusal_reason == "invalid_selection_record"


def test_selection_revalidation_and_stale_publication(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    sel_out = tmp_path / "pinned.json"
    rec = select_context_sources(
        port=adapter,
        bindings=(BINDING_CORE, BINDING_DOCS),
        path_prefixes={BINDING_CORE: ("src/billing",)},
        pin_publication=True,
        output_path=sel_out,
    )
    assert rec.scan_unit_count == 2

    # Valid pack with selection_file
    pkt = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="InvoiceService",
            intent="definition",
            selection_path=sel_out,
        ),
        adapter,
    )
    assert_valid_context_packet(pkt)
    assert pkt["scope"]["selection_source"] == "selection_file"
    assert len(pkt["items"]) >= 1

    # Simulate publication advancement -> status="stale", reason="selection_publication_advanced"
    live_cfg = adapter.configured_bindings_by_id()
    live_acc = dict(adapter.read_initial_identity(WorkLedger())["accepted_publication"])
    live_acc["generation"] = 2
    status, reason = revalidate_selection_record(
        rec,
        live_graph_id=adapter.graph_id,
        live_repository_id=adapter.repository_id,
        live_backend="sqlite",
        live_bindings_by_id=live_cfg,
        live_accepted=live_acc,
    )
    assert (status, reason) == ("stale", "selection_publication_advanced")


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (lambda rec: replace(rec, schema="other-v1"), "invalid_selection_record"),
        (lambda rec: replace(rec, backend="memory"), "invalid_selection_record"),
        (lambda rec: replace(rec, repository_id="private-repo"), "invalid_selection_record"),
        (lambda rec: replace(rec, bindings=()), "binding_limit_exceeded"),
        (lambda rec: replace(rec, scan_unit_count=99), "invalid_selection_record"),
        (lambda rec: replace(rec, bindings=(rec.bindings[0], rec.bindings[0])), "invalid_selection_record"),
    ],
)
def test_selection_record_rejects_header_binding_and_count_tampering(bad, reason: str) -> None:
    rec = _sample_record(pin_pub=True)
    candidate = bad(rec)
    with pytest.raises(ContextRequestError) as exc:
        candidate.validate()
    assert exc.value.refusal_reason == reason


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        (SourceBindingSelection("", 1, None, "select1:pol", "src1:core"), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", True, None, "select1:pol", "src1:core"), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 0, None, "select1:pol", "src1:core"), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 1, "", "select1:pol", "src1:core"), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 1, None, "", "src1:core"), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 1, None, "select1:pol", "",), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 1, None, "select1:pol", "src1:core", ("../src",)), "invalid_selection_record"),
        (SourceBindingSelection("bind1:core", 1, None, "select1:pol", "src1:core", tuple("src" + str(i) for i in range(5))), "prefix_limit_exceeded"),
    ],
)
def test_binding_validation_rejects_untrusted_fields(binding: SourceBindingSelection, reason: str) -> None:
    with pytest.raises(ContextRequestError) as exc:
        binding.validate()
    assert exc.value.refusal_reason == reason


def test_selection_revalidation_reports_configuration_and_publication_states() -> None:
    rec = _sample_record(pin_pub=True)
    assert revalidate_selection_record(
        rec, live_graph_id="other", live_repository_id=rec.repository_id,
        live_backend=rec.backend, live_bindings_by_id={}, live_accepted=None,
    ) == (
        "refused", "selection_graph_mismatch"
    )
    assert revalidate_selection_record(
        rec, live_graph_id=rec.graph_id, live_repository_id=rec.repository_id,
        live_backend=rec.backend, live_bindings_by_id={}, live_accepted=None,
    ) == ("refused", "selection_binding_missing")
    changed = {rec.bindings[0].binding_id: {
        "revision": 2,
        "snapshot_id": rec.bindings[0].snapshot_id,
        "selection_policy_id": rec.bindings[0].selection_policy_id,
        "source_definition_id": rec.bindings[0].source_definition_id,
    }}
    assert revalidate_selection_record(
        rec, live_graph_id=rec.graph_id, live_repository_id=rec.repository_id,
        live_backend=rec.backend, live_bindings_by_id=changed, live_accepted=None,
    ) == ("refused", "selection_binding_changed")
    live = {rec.bindings[0].binding_id: {
        "revision": rec.bindings[0].revision,
        "snapshot_id": rec.bindings[0].snapshot_id,
        "selection_policy_id": rec.bindings[0].selection_policy_id,
        "source_definition_id": rec.bindings[0].source_definition_id,
    }}
    assert revalidate_selection_record(
        rec, live_graph_id=rec.graph_id, live_repository_id=rec.repository_id,
        live_backend=rec.backend, live_bindings_by_id=live, live_accepted=None,
    ) == ("unavailable", "publication_absent")
    assert revalidate_selection_record(
        rec, live_graph_id=rec.graph_id, live_repository_id=rec.repository_id,
        live_backend=rec.backend, live_bindings_by_id=live, live_accepted={},
    ) == ("unavailable", "accepted_publication_unverified")
