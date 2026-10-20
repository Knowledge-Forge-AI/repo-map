"""Integration contracts for Order 3: streaming bundle parser/encoder/links/sorter, receipt, bundle, and validator."""

from __future__ import annotations

from dataclasses import replace
import io
import threading
from typing import Any, cast
import unittest

from repomap_kg.artifacts._bundle_stream_encode import (
    PublicationExpectation,
    StreamingBundleEncoder,
)
from repomap_kg.artifacts._bundle_stream_links import DiskFamilyLinkValidator
from repomap_kg.artifacts._bundle_stream_parse import StreamingBundleParser
from repomap_kg.artifacts._bundle_stream_sort import BoundedExternalRowSorter
from repomap_kg.artifacts._canonical import canonical_json, decode_canonical_json
from repomap_kg.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES,
    PUBLICATION_FAMILIES,
    PublicationBundle,
)
from repomap_kg.artifacts.receipt import ExtractionReceipt, _int, _str, _vector
from repomap_kg.artifacts.store import InMemoryArtifactStore
from repomap_kg.artifacts.validator import PublisherBundleValidator, _validate_family_links
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def _meta() -> dict[str, Any]:
    return {
        "request_id": "req-nav33",
        "job_id": "job-nav33",
        "attempt": 1,
        "graph_id": "graph_nav33",
        "candidate_id": "cand1:" + "a" * 64,
        "snapshot_manifest_id": "snapmanifest1:" + "b" * 64,
        "snapshot_vector": (("bind1:" + "c" * 64, 1, "snap1:" + "d" * 64),),
        "source_generation": "sg1:" + "e" * 64,
        "config_generation": "cg1:" + "f" * 64,
        "extractor_generation": "eg1:v1",
        "canonicalizer_generation": "kg1:v1",
        "extractor_capability_identity": "cap1:v1",
        "resolver_identity": "resolver1:v1",
        "canonicalizer_identity": "canon1:v1",
        "semantic_contract_identity": "semantic1:v1",
        "quality_rule_identity": "quality1:v1",
    }


def _empty_families() -> dict[str, tuple[dict[str, object], ...]]:
    return {f: () for f in PUBLICATION_FAMILIES}


def _make_bundle(
    *,
    row_stage_contract: str = "stage-unassigned-v1",
    families: dict[str, Any] | None = None,
) -> PublicationBundle:
    return PublicationBundle.create(
        **_meta(),
        privacy=PrivacyClassification.PUBLIC,
        row_stage_contract=row_stage_contract,
        families=cast(Any, families or _empty_families()),
    )


def _make_receipt(
    bundle: PublicationBundle,
    store: InMemoryArtifactStore,
    *,
    outcome: str = "completed",
    cancellation: str = "not-requested",
    diagnostic_category: str | None = None,
) -> tuple[ExtractionReceipt, Any, Any]:
    b_bytes = bundle.canonical_bytes()
    b_ref = store.put(
        b_bytes,
        media_type="application/vnd.repomap.publication-bundle.v1+jsonl",
        record_format="jsonl-v1",
        privacy=PrivacyClassification.PUBLIC,
    )
    meta = _meta()
    meta.pop("candidate_id")
    receipt = ExtractionReceipt.create(
        **meta,
        worker_capability_identity="cap1:portable-worker-v1",
        contract_version="1.0",
        outcome=outcome,
        cancellation=cancellation,
        bundle_reference=b_ref if outcome == "completed" else None,
        bundle_id=bundle.bundle_id if outcome == "completed" else None,
        family_counts=bundle.family_counts if outcome == "completed" else {},
        diagnostic_category=diagnostic_category,
        diagnostic_summary=(),
        producer_identity="producer1:nav33",
        attestation_class="worker-sealed-v1",
    )
    r_ref = store.put(
        receipt.canonical_bytes(),
        media_type="application/vnd.repomap.extraction-receipt.v1+json",
        record_format="json-v1",
        privacy=PrivacyClassification.PUBLIC,
    )
    return receipt, b_ref, r_ref


class Navigation33StreamingBundleValidationIntegrationTests(unittest.TestCase):
    """Integration contracts for streaming bundle parsing, encoding, links, sorting, receipts, and validation."""

    def test_streaming_bundle_parser_framing_ordering_stage_and_authority_contracts(self) -> None:
        """StreamingBundleParser enforces framing, ordering, stage contracts, and receipt/expectation parity."""
        store = InMemoryArtifactStore()
        fams = _empty_families()
        fams["files"] = (
            {"path": "a.py", "stage_id": "stage-unassigned"},
            {"path": "b.py", "stage_id": "stage-unassigned"},
        )
        bundle = _make_bundle(row_stage_contract="stage-unassigned-v1", families=fams)
        receipt, _b_ref, _r_ref = _make_receipt(bundle, store)
        expect = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
        raw = bundle.canonical_bytes()

        # Valid parse without stage_id (family_spools is None -> families empty, to_prepared_stage_rows raises)
        parser = StreamingBundleParser()
        desc_no_stage = parser.parse_and_validate(io.BytesIO(raw), expect, receipt, stage_id=None)
        self.assertEqual(desc_no_stage.families["files"], ())
        with self.assertRaisesRegex(ValueError, "stage rows were not prepared"):
            desc_no_stage.to_prepared_stage_rows()

        # Valid parse with stage_id -> exercises stage-unassigned-v1 families property & to_prepared_stage_rows
        desc_staged = parser.parse_and_validate(io.BytesIO(raw), expect, receipt, stage_id="stg-1")
        self.assertEqual(len(desc_staged.families["files"]), 2)
        prepared = desc_staged.to_prepared_stage_rows()
        self.assertEqual(prepared.files, 2)
        desc_staged.close()

        # Valid parse with legacy-absent-v1 + stage_id -> exercises legacy families property
        fams_leg = _empty_families()
        fams_leg["files"] = ({"path": "a.py"},)
        b_leg = _make_bundle(row_stage_contract="legacy-absent-v1", families=fams_leg)
        r_leg, _, _ = _make_receipt(b_leg, store)
        exp_leg = PublicationExpectation.from_bundle(b_leg, mutating_owner_count=1)
        desc_leg = parser.parse_and_validate(io.BytesIO(b_leg.canonical_bytes()), exp_leg, r_leg, stage_id="stg-2")
        self.assertNotIn("stage_id", desc_leg.families["files"][0])
        desc_leg.close()

        # Mutating owner count != 1
        with self.assertRaisesRegex(ValueError, "exactly one mutating owner"):
            parser.parse_and_validate(io.BytesIO(raw), replace(expect, mutating_owner_count=2), receipt)

        # Header framing, version, row_stage_contract, and extra key errors
        with self.assertRaisesRegex(ValueError, "publication bundle framing is invalid"):
            parser.parse_and_validate(io.BytesIO(b""), expect, receipt)
        lines = raw.splitlines(keepends=True)
        hdr = decode_canonical_json(lines[0])
        for mut_hdr, pat in (
            ({**hdr, "frame": "not-header"}, "framing is invalid"),
            ({**hdr, "schema_version": 2}, "unsupported publication bundle version"),
            ({**hdr, "row_stage_contract": "bad-v1"}, "bundle row stage contract is invalid"),
            ({**hdr, "extra_key": "x"}, "framing is invalid"),
        ):
            with self.assertRaisesRegex(ValueError, pat):
                parser.parse_and_validate(io.BytesIO(canonical_json(mut_hdr) + b"".join(lines[1:])), expect, receipt)

        # Expectation and receipt header mismatches
        with self.assertRaisesRegex(ValueError, "bundle semantic authority mismatch"):
            parser.parse_and_validate(io.BytesIO(raw), replace(expect, graph_id="other"), receipt)
        with self.assertRaisesRegex(ValueError, "receipt semantic authority mismatch"):
            parser.parse_and_validate(io.BytesIO(raw), expect, replace(receipt, graph_id="other"))
        with self.assertRaisesRegex(ValueError, "receipt contract version mismatch"):
            parser.parse_and_validate(io.BytesIO(raw), replace(expect, contract_version="2.0"), receipt)
        with self.assertRaisesRegex(ValueError, "bundle privacy mismatch"):
            parser.parse_and_validate(io.BytesIO(raw), replace(expect, expected_privacy="internal"), receipt)
        with self.assertRaisesRegex(ValueError, "receipt and bundle terminal state is inconsistent"):
            parser.parse_and_validate(io.BytesIO(raw), expect, replace(receipt, cancellation="requested"))

        # Record bounds, family ordering, intra-family ordering, stage ambiguity, trailer & EOF errors
        with self.assertRaisesRegex(ValueError, "publication bundle byte bounds exceeded"):
            StreamingBundleParser(max_bundle_bytes=len(lines[0]) + 5).parse_and_validate(
                io.BytesIO(raw), expect, receipt, stage_id="stg-err",
            )
        bad_fam = canonical_json({"family": "unknown_fam", "frame": "record", "record": {}})
        with self.assertRaisesRegex(ValueError, "publication bundle family is invalid"):
            parser.parse_and_validate(io.BytesIO(lines[0] + bad_fam + lines[-1]), expect, receipt)

        # Out-of-order family: canonical_nodes followed by files
        rec_node = canonical_json({"family": "canonical_nodes", "frame": "record", "record": {"canonical_key": "n1", "stage_id": "stage-unassigned"}})
        with self.assertRaisesRegex(ValueError, "publication bundle family ordering is invalid"):
            parser.parse_and_validate(io.BytesIO(lines[0] + rec_node + lines[1] + lines[-1]), expect, receipt)

        # Out-of-order intra-family: b.py before a.py
        with self.assertRaisesRegex(ValueError, "intra-family ordering is invalid"):
            parser.parse_and_validate(io.BytesIO(lines[0] + lines[2] + lines[1] + lines[-1]), expect, receipt)

        # Stage ambiguity
        rec_no_stg = canonical_json({"family": "files", "frame": "record", "record": {"path": "a.py"}})
        with self.assertRaisesRegex(ValueError, "bundle stage representation is ambiguous"):
            parser.parse_and_validate(io.BytesIO(lines[0] + rec_no_stg + lines[-1]), expect, receipt)
        leg_lines = b_leg.canonical_bytes().splitlines(keepends=True)
        with self.assertRaisesRegex(ValueError, "legacy bundle stage representation is ambiguous"):
            parser.parse_and_validate(io.BytesIO(leg_lines[0] + lines[1] + leg_lines[-1]), exp_leg, r_leg)

        # Missing trailer, bad trailer summary, extra bytes after trailer, bundle_id/digest mismatch
        with self.assertRaisesRegex(ValueError, "publication bundle framing is invalid"):
            parser.parse_and_validate(io.BytesIO(lines[0] + lines[1]), expect, receipt)
        with self.assertRaisesRegex(ValueError, "publication bundle summary is inconsistent"):
            parser.parse_and_validate(io.BytesIO(lines[0] + lines[-1]), expect, receipt)
        with self.assertRaisesRegex(ValueError, "publication bundle framing is invalid"):
            parser.parse_and_validate(io.BytesIO(raw + b"\n"), expect, receipt)
        with self.assertRaisesRegex(ValueError, "receipt and bundle terminal state is inconsistent"):
            parser.parse_and_validate(io.BytesIO(raw), expect, replace(receipt, bundle_id="bundle1:" + "0" * 64))
        with self.assertRaisesRegex(ValueError, "receipt and bundle terminal state is inconsistent"):
            parser.parse_and_validate(io.BytesIO(raw), expect, replace(receipt, bundle_reference=None))

    def test_streaming_encoder_links_and_external_sorter_contracts(self) -> None:
        """StreamingBundleEncoder, DiskFamilyLinkValidator, and BoundedExternalRowSorter enforce bounds and links."""
        meta = _meta()
        with self.assertRaisesRegex(ValueError, "bundle privacy is invalid"):
            StreamingBundleEncoder(**meta, privacy=cast(Any, "bad"), family_rows=_empty_families())
        with self.assertRaisesRegex(ValueError, "bundle row stage contract is invalid"):
            StreamingBundleEncoder(**meta, privacy=PrivacyClassification.PUBLIC, row_stage_contract="bad", family_rows=_empty_families())
        with self.assertRaisesRegex(ValueError, "bundle terminal completeness is invalid"):
            StreamingBundleEncoder(**meta, privacy=PrivacyClassification.PUBLIC, terminal_complete=cast(Any, "yes"), family_rows=_empty_families())
        with self.assertRaisesRegex(ValueError, "publication bundle family inventory is invalid"):
            StreamingBundleEncoder(**meta, privacy=PrivacyClassification.PUBLIC, family_rows={"files": ()})

        enc = StreamingBundleEncoder(
            **meta, privacy=PrivacyClassification.PUBLIC,
            row_stage_contract="legacy-absent-v1", family_rows=_empty_families(),
        )
        with self.assertRaisesRegex(ValueError, "streaming encoding has not completed"):
            enc.descriptor()
        _ = b"".join(enc.stream_chunks())
        self.assertNotIn("row_stage_contract", enc.descriptor().header_mapping())
        self.assertEqual(enc.descriptor().trailer_mapping()["frame"], "trailer")

        # Cancellation before and during family records
        ev = threading.Event()
        ev.set()
        enc_cancel = StreamingBundleEncoder(
            **meta, privacy=PrivacyClassification.PUBLIC, family_rows=_empty_families(), cancel_event=ev,
        )
        with self.assertRaisesRegex(ValueError, "cancelled"):
            list(enc_cancel.stream_chunks())

        ev2 = threading.Event()

        def _cancelling_rows() -> Any:
            ev2.set()
            yield {"path": "a.py"}

        fams_gen: dict[str, Any] = _empty_families()
        fams_gen["files"] = _cancelling_rows()
        enc_cancel2 = StreamingBundleEncoder(
            **meta, privacy=PrivacyClassification.PUBLIC, family_rows=fams_gen, cancel_event=ev2,
        )
        with self.assertRaisesRegex(ValueError, "cancelled"):
            list(enc_cancel2.stream_chunks())

        # BoundedExternalRowSorter spill runs + trailing buffer + line bound
        sorter = BoundedExternalRowSorter(max_buffer_bytes=64)
        rows = [{"path": f"file_{i:02d}.py"} for i in (3, 1, 2)]
        sorted_lines = list(sorter.sort_family_records("files", rows))
        self.assertEqual(len(sorted_lines), 3)
        self.assertGreaterEqual(sorter.spill_run_count, 2)
        with self.assertRaisesRegex(ValueError, "publication bundle line bounds exceeded"):
            list(sorter.sort_family_records("files", [{"blob": "x" * (MAX_BUNDLE_LINE_BYTES + 10)}]))

        # DiskFamilyLinkValidator batch_size=1 flushes & link errors
        lv = DiskFamilyLinkValidator()
        lv._batch_size = 1
        try:
            lv.record_raw_observation({"source_ordinal": 1})
            lv.record_canonical_node({"canonical_key": "node:1"})
            lv.record_canonical_edge({"source_canonical_key": "node:1", "edge_kind": "calls", "target_canonical_key": "node:1", "identity_metadata_hash": "h1"})
            with self.assertRaisesRegex(ValueError, "evidence reference is invalid"):
                lv.record_and_validate_evidence({"raw_observation_ordinal": 999, "evidence_key": "ev:1"})
            lv.record_and_validate_evidence({"raw_observation_ordinal": 1, "evidence_key": "ev:1"})
            with self.assertRaisesRegex(ValueError, "node evidence reference is invalid"):
                lv.validate_node_evidence({"canonical_key": "node:missing", "evidence_key": "ev:1"})
            with self.assertRaisesRegex(ValueError, "node evidence reference is invalid"):
                lv.validate_node_evidence({"canonical_key": "node:1", "evidence_key": "ev:missing"})
            with self.assertRaisesRegex(ValueError, "edge evidence reference is invalid"):
                lv.validate_edge_evidence({"source_canonical_key": "node:missing", "edge_kind": "calls", "target_canonical_key": "node:1", "identity_metadata_hash": "h1", "evidence_key": "ev:1"})
            with self.assertRaisesRegex(ValueError, "edge evidence reference is invalid"):
                lv.validate_edge_evidence({"source_canonical_key": "node:1", "edge_kind": "calls", "target_canonical_key": "node:1", "identity_metadata_hash": "h1", "evidence_key": "ev:missing"})
        finally:
            lv.close()

    def test_bundle_receipt_and_validator_malformed_and_semantic_refusals(self) -> None:
        """PublicationBundle, ExtractionReceipt, and PublisherBundleValidator enforce canonical and link rules."""
        store = InMemoryArtifactStore()
        fams = _empty_families()
        fams["files"] = ({"path": "a.py", "stage_id": "stage-unassigned"},)
        bundle = _make_bundle(families=fams)
        raw = bundle.canonical_bytes()
        for mut in ("truncated", "duplicate", "partial", "unknown-family"):
            self.assertNotEqual(PublicationBundle.malformed_for_test(raw, mut), raw)
        with self.assertRaisesRegex(ValueError, "unknown test mutation"):
            PublicationBundle.malformed_for_test(raw, "other")

        # ExtractionReceipt validation & parsing
        receipt, b_ref, r_ref = _make_receipt(bundle, store)
        with self.assertRaisesRegex(ValueError, "receipt identity field is invalid"):
            replace(receipt, request_id="").reidentify()
        with self.assertRaisesRegex(ValueError, "receipt attempt is invalid"):
            replace(receipt, attempt=0).reidentify()
        with self.assertRaisesRegex(ValueError, "receipt outcome is invalid"):
            replace(receipt, outcome="bad").reidentify()
        with self.assertRaisesRegex(ValueError, "receipt diagnostic category is invalid"):
            replace(receipt, diagnostic_category="bad_cat").reidentify()
        with self.assertRaisesRegex(ValueError, "receipt diagnostics exceed bounds"):
            replace(receipt, diagnostic_summary=("x" * 300,)).reidentify()
        with self.assertRaisesRegex(ValueError, "completed receipt is inconsistent"):
            replace(receipt, bundle_id=None).reidentify()
        with self.assertRaisesRegex(ValueError, "non-completed receipt cannot accept a bundle"):
            replace(receipt, outcome="failed", diagnostic_category="source_unavailable").reidentify()
        with self.assertRaisesRegex(ValueError, "terminal receipt diagnostic is missing"):
            replace(receipt, outcome="failed", bundle_reference=None, bundle_id=None, family_counts={}, diagnostic_category=None).reidentify()
        with self.assertRaisesRegex(ValueError, "cancelled receipt cancellation state is invalid"):
            replace(receipt, outcome="cancelled", bundle_reference=None, bundle_id=None, family_counts={}, cancellation="not-requested").reidentify()
        with self.assertRaisesRegex(ValueError, "snapshot vector is invalid"):
            _vector("not-a-list")
        with self.assertRaisesRegex(ValueError, "snapshot vector is invalid"):
            _vector([["only-two", 1]])
        with self.assertRaisesRegex(ValueError, "receipt string field is invalid"):
            _str(123)
        with self.assertRaisesRegex(ValueError, "receipt integer field is invalid"):
            _int(True)

        # PublisherBundleValidator semantic & link checks
        val = PublisherBundleValidator()
        with self.assertRaisesRegex(ValueError, "terminal receipt is not a non-completed attempt"):
            val.validate_terminal_receipt(store=store, receipt_reference=r_ref)
        expect = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
        res = val.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=expect)
        self.assertTrue(res.byte_integrity_valid)

        bad_node_ev = _empty_families()
        bad_node_ev["canonical_node_evidence"] = ({"canonical_key": "missing", "evidence_key": "missing"},)
        with self.assertRaisesRegex(ValueError, "node evidence reference is invalid"):
            _validate_family_links(bad_node_ev)
        bad_edge_ev = _empty_families()
        bad_edge_ev["canonical_edge_evidence"] = ({"source_canonical_key": "m", "edge_kind": "k", "target_canonical_key": "t", "identity_metadata_hash": "h", "evidence_key": "e"},)
        with self.assertRaisesRegex(ValueError, "edge evidence reference is invalid"):
            _validate_family_links(bad_edge_ev)
