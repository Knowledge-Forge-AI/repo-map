"""Supervised peers must not turn malformed terminal claims into success."""
import json
from pathlib import Path
import sys

import pytest

from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator.protocol import WorkerLaunchSpec, run_worker_spec
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


PEER = '''
import json, sys
terminal, portable = json.loads(sys.argv[1])
capabilities = ["refresh_graph"] + (["portable_snapshot_v1"] if portable else [])
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1],
    capabilities=capabilities, worker_generation="wg1:fixture", process_nonce="fixture")), flush=True)
json.loads(sys.stdin.readline())
print(json.dumps(terminal), flush=True)
assert sys.stdin.buffer.read() == b""
raise SystemExit(int(sys.argv[2]))
'''


def _terminal():
    return dict(schema_version=1, message_type="result", job_id="wire-fixture", attempt=1,
                job_kind="refresh_graph", graph_id="wire-graph", source_generation="sg1:fixture",
                config_generation="cg1:fixture", phase="complete",
                started_at="2026-09-23T12:00:00Z", finished_at="2026-09-23T12:01:00Z",
                extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
                files=1, observations=1, canonical_nodes=1, canonical_edges=0,
                warnings=[], diagnostics=[], status="succeeded", publication_state="committed",
                retryable=False, latest_run_identity="run-fixture", error_category=None)


def _run(terminal, context=None, exit_code=0):
    return run_worker_spec(
        WorkerLaunchSpec(argv=(sys.executable, "-c", PEER, json.dumps([terminal, context is not None]), str(exit_code)),
                         environment={"LANG": "C.UTF-8"}, cwd=Path(__file__).resolve().parents[6]),
        {"job_id": "wire-fixture", "attempt": 1},
        {"process_deadline_seconds": 5.0, "hello_deadline_seconds": 2.0,
         "heartbeat_seconds": 2.0, "cancel_deadline_seconds": 1.0,
         "process_termination_grace_seconds": 1.0},
        job_context=context or {"graph_id": "wire-graph", "source_generation": "sg1:fixture",
                                "config_generation": "cg1:fixture"})


def test_cancelled_terminal_does_not_excuse_abnormal_exit():
    terminal = _terminal()
    terminal.update(status="cancelled", publication_state="not_started", latest_run_identity=None)
    result = _run(terminal, exit_code=17)
    assert result.original_terminal == terminal and result.returncode == 17
    assert result.protocol_error is None and result.waited and result.process_group_cleaned
    assert result.synthesized_terminal and result.terminal["reason"] == "process_exit"


@pytest.mark.parametrize(("field", "value"), [
    ("job_kind", "other"), ("extractor_generation", "bad/path"),
    ("warnings", ["unregistered"]), ("retryable", 1),
    ("finished_at", "2026-02-30T12:00:00Z"),
    ("publication_state", "not_started"), ("latest_run_identity", None),
    ("status", "cancelled"), ("error_category", "semantic_workload"),
])
def test_invalid_terminal_claim_is_refused_and_next_attempt_recovers(field, value):
    terminal = _terminal()
    terminal[field] = value
    rejected = _run(terminal)
    assert rejected.protocol_error == "protocol_error:" + (
        "identity_mismatch" if field == "job_kind" else "invalid_value")
    assert rejected.synthesized_terminal and rejected.terminal["reason"] == "protocol"
    assert rejected.original_terminal is None
    assert rejected.waited and rejected.process_group_cleaned
    recovered = _run(_terminal())
    assert recovered.returncode == 0 and not recovered.synthesized_terminal
    assert recovered.terminal["status"] == "succeeded"
    assert recovered.waited and recovered.process_group_cleaned


@pytest.mark.parametrize("damage", [
    "shape", "version", "outcome-type", "cancel-status", "failure-status",
    "stored-diagnostic", "stored-no-receipt", "unknown-receipt-status",
    "unavailable-success", "legacy-no-receipt", "receipt-media", "bundle-type",
    "bundle-media", "receipt-malformed", "cancel-bundle", "portable-publication",
    "portable-cancel-publication", "portable-failure-publication",
    "legacy-success", "unavailable-cancellation",
])
def test_portable_receipt_claims_are_validated_across_the_supervised_wire(tmp_path, damage):
    store = FileSystemArtifactStore(tmp_path / "store")
    def reference(media):
        return store.put(b"{}", media_type=media, record_format="canonical-json-v1",
                         privacy=PrivacyClassification.PUBLIC).to_mapping()

    receipt = reference("application/x-repomap-extraction-receipt-v1+json")
    bundle = reference("application/x-repomap-publication-bundle-v1+jsonl")
    context = dict(graph_id="wire-graph", source_generation="sg1:fixture", config_generation="cg1:fixture",
                   portable_snapshot=dict(contract_version="1.0", required=True,
                                          snapshot_manifest=reference("application/x-repomap-snapshot-manifest-v1+json")))
    terminal = _terminal()
    terminal.update(publication_state="not_started", latest_run_identity=None)
    extension = dict(contract_version="1.0", outcome="completed", receipt=receipt,
                     receipt_status="stored", receipt_diagnostic=None, bundle=bundle)
    terminal["portable_snapshot"] = extension
    if damage == "shape":
        extension["extra"] = True
    elif damage == "version":
        extension["contract_version"] = "2.0"
    elif damage == "outcome-type":
        extension["outcome"] = []
    elif damage == "cancel-status":
        extension["outcome"] = "cancelled"
    elif damage == "failure-status":
        extension["outcome"] = "semantic_workload"
    elif damage == "stored-diagnostic":
        extension["receipt_diagnostic"] = "write_failed"
    elif damage == "stored-no-receipt":
        extension["receipt"] = None
    elif damage == "unknown-receipt-status":
        extension["receipt_status"] = "unknown"
    elif damage == "unavailable-success":
        extension.update(receipt_status="unavailable", receipt=None, receipt_diagnostic="write_failed")
    elif damage.startswith("legacy"):
        del extension["receipt_status"], extension["receipt_diagnostic"]
        if damage == "legacy-no-receipt":
            extension["receipt"] = None
    elif damage == "receipt-media":
        extension["receipt"] = bundle
    elif damage == "bundle-type":
        extension["bundle"] = []
    elif damage == "bundle-media":
        extension["bundle"] = receipt
    elif damage == "receipt-malformed":
        extension["receipt"] = {"invalid": True}
    elif damage in {"cancel-bundle", "portable-cancel-publication", "unavailable-cancellation"}:
        terminal["status"] = "cancelled"
        extension["outcome"] = "cancelled"
        if damage != "cancel-bundle":
            extension["bundle"] = None
        if damage == "portable-cancel-publication":
            terminal["publication_state"] = "committed"
        elif damage == "unavailable-cancellation":
            extension.update(receipt_status="unavailable", receipt=None, receipt_diagnostic="write_failed")
    elif damage == "portable-failure-publication":
        terminal.update(message_type="error", status="failed", error_category="semantic_workload",
                        publication_state="rolled_back")
        extension.update(outcome="semantic_workload", bundle=None)
    else:
        terminal["publication_state"] = "committed"
    result = _run(terminal, context)
    assert result.waited and result.process_group_cleaned
    if damage in {"legacy-success", "unavailable-cancellation"}:
        assert result.returncode == 0 and result.protocol_error is None
        assert not result.synthesized_terminal and result.terminal == terminal
    else:
        code = ("unsupported_extension" if damage == "version" else
                "invalid_value" if damage.startswith("portable-") else "invalid_extension")
        assert result.protocol_error == "protocol_error:" + code
        assert result.synthesized_terminal and result.terminal["reason"] == "protocol"
        assert result.original_terminal is None
