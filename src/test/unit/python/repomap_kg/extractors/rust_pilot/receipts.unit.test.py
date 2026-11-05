"""Pilot receipts and run report: audit-only, schema-valid, path-free (spec 13)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from common_lore_index.extractors.contracts.receipt_codec import decode_receipt, encode_receipt
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot import receipts
from common_lore_index.extractors.rust_pilot.component_lock import LOCK_SHA256

RUN = "rp1.0123456789abcdef"
SHA = "b" * 64


@pytest.mark.parametrize(("outcome", "completeness", "achieved"), [
    ("succeeded", "complete", ("syntax.tree",)), ("succeeded", "partial", ("syntax.error_tolerant",)),
    ("succeeded", "truncated", ("syntax.error_tolerant",)), ("parse_rejected", "none", ()),
    ("resource_bound_exceeded", "none", ()), ("crashed", "none", ())])
def test_attempt_receipts_round_trip_and_never_carry_verification(outcome: str, completeness: str,
                                                                   achieved: tuple[str, ...]) -> None:
    receipt = receipts.attempt_receipt(run_id=RUN, seq=4, input_sha256=SHA, profile_sha256="c" * 64,
                                       artifact_sha256="d" * 64, outcome=outcome, completeness=completeness,
                                       achieved=achieved, resource_events=("time_bound",) if achieved == () else (),
                                       exit_status=0 if achieved else 137, cleanup_proven=True)
    assert decode_receipt(encode_receipt(receipt)) == receipt
    payload = receipt.to_dict()
    assert payload["state"] == "complete" and payload["run_id"] == f"{RUN}.4"
    assert payload["observed"]["verification"] == "unverified"
    assert payload["declared"]["dependency_sha256"] == LOCK_SHA256
    assert payload["declared"]["effects"] == {"target_code_evaluated": "none", "execution_boundary": "subprocess",
                                              "filesystem_read_scope": "selected-input",
                                              "filesystem_write_scope": "scratch", "network": "none"}
    assert payload["observed"]["attempts"][0]["exercised"] == ["syntax.error_tolerant", "syntax.tree"]


def test_incomplete_cleanup_and_out_of_range_exits_stay_incomplete() -> None:
    receipt = receipts.attempt_receipt(run_id=RUN, seq=1, input_sha256=SHA, profile_sha256="c" * 64,
                                       artifact_sha256=None, outcome="crashed", completeness="none", achieved=(),
                                       resource_events=(), exit_status=-9999, cleanup_proven=False)
    assert receipt.state == "incomplete" and receipt.observed is not None
    assert (receipt.observed.cleanup, receipt.observed.exit_status) == ("incomplete", -255)
    with pytest.raises(ContractError):
        receipts.attempt_receipt(run_id=RUN, seq=1, input_sha256=SHA, profile_sha256="c" * 64, artifact_sha256=None,
                                 outcome="crashed", completeness="none", achieved=("syntax.tree",),
                                 resource_events=(), exit_status=1, cleanup_proven=True)


def test_refused_and_unavailable_receipts_are_distinct_states() -> None:
    refused = receipts.refusal_receipt(run_id=RUN, seq=2, source_sha256=SHA, profile_sha256=None,
                                       code="resource_bound_exceeded", resource_events=("input_bound",))
    unavailable = receipts.unavailable_receipt(run_id=RUN, source_sha256=receipts.run_source_sha256([SHA]))
    assert (refused.state, refused.refusal) == ("refused", "resource_bound_exceeded")
    assert (unavailable.state, unavailable.refusal) == ("unavailable", "dependency_unavailable")
    for receipt in (refused, unavailable):
        assert receipt.observed is not None and receipt.observed.attempts == ()
        assert decode_receipt(encode_receipt(receipt)) == receipt
    assert receipts.run_source_sha256([SHA, "a" * 64]) == receipts.run_source_sha256(["a" * 64, SHA])


def test_report_and_audit_storage_are_path_free_and_owner_only(tmp_path: Path) -> None:
    report = receipts.run_report(run_id=RUN, platform="aarch64", image_id="sha256:" + "a" * 64,
                                 server={"os": "linux", "arch": "arm64"}, runtime={"version": "3.13.12"},
                                 profile_sha256="c" * 64, helper_closure_sha256="e" * 64,
                                 files=[{"seq": 2, "input_sha256": SHA, "outcome": "succeeded"}],
                                 residue={"observed": True}, timings={"parse": 0.0123}, receipt_digests=(),
                                 run_outcome="processed")
    encoded = json.dumps(report)
    assert '"path"' not in encoded and "lib.rs" not in encoded
    assert report["timings_ms"] == {"parse": 12} and report["verification"] == "unverified"
    audit = tmp_path / "audit"
    audit.mkdir(mode=0o700)
    receipt = receipts.unavailable_receipt(run_id=RUN, source_sha256=SHA)
    digests = receipts.store_audit(audit, [receipt], report)
    names = sorted(os.listdir(audit))
    assert names[0] == f"receipt-{digests[0]}.json" and names[1].startswith("run-report-")
    for name in names:
        info = os.lstat(audit / name)
        assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    stored = json.loads((audit / names[1]).read_bytes())
    assert stored["receipt_sha256"] == list(digests) and "files" in stored
    with pytest.raises(ContractError):
        receipts.store_audit(audit, [receipt], report)


def test_report_projects_closed_runtime_facts_without_native_text() -> None:
    marker = "synthetic-private-native-payload"
    runtime = {
        "version": "3.13.12", "machine": "aarch64", "lc_all": marker,
        "kernel": marker, "fs_encoding": marker, "unexpected": marker,
        "flags": {"isolated": 1, "no_site": True, "unexpected": marker},
        "kind_ids": {marker: marker}, "field_ids": {marker: marker},
        "abi_version": 15, "language_version": True, "probe_parse_ok": True,
        "libc": ["glibc", "2.41"],
    }
    report = receipts.run_report(
        run_id=RUN, platform="aarch64", image_id="sha256:" + "a" * 64,
        server={"os": "linux", "arch": "arm64"}, runtime=runtime,
        profile_sha256=SHA, helper_closure_sha256=SHA, files=(), residue={},
        timings={}, receipt_digests=(), run_outcome="processed",
    )
    observed = report["runtime_observed"]
    assert marker not in json.dumps(report)
    assert observed["version"] == "3.13.12" and observed["machine"] == "aarch64"
    assert observed["flags"] == {"isolated": 1}
    assert observed["abi_version"] == 15 and "language_version" not in observed
    assert observed["libc"] == ["glibc", "2.41"] and observed["probe_parse_ok"] is True
    assert observed["probe_sha256"] == receipts.digest_json(runtime)
    for key in ("kernel", "kind_ids", "field_ids"):
        assert key not in observed and observed[key + "_sha256"] == receipts.digest_json(runtime[key])


@pytest.mark.parametrize("libc", [["glibc", "2.41-native"], ["other", "2.41"], ["glibc"], None])
def test_report_omits_unvalidated_libc_versions(libc: object) -> None:
    assert "libc" not in receipts._runtime_report({"libc": libc})
