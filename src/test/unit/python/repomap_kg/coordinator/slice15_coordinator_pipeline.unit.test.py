"""Migrated Slice15 isolated regressions; no integration campaign credit."""

from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import tempfile
from repomap_kg.coordinator.service import CoordinatorService
from typing import Any, cast
import unittest
from repomap_kg.artifacts.receipt import ExtractionReceipt, _validate_receipt
from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.coordinator._protocol_core import PROTOCOL_VERSION, ProtocolError, ProtocolSession
from repomap_kg.coordinator._protocol_validation import _validate_portable_snapshot_result_extension
from repomap_kg.storage._staging_measurement_records import (
    SCHEMA_VERSION,
    StagingMeasurementAvailability,
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurementUnit,
)
from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
    PrivacyClassification,
    ValidationRule,
)


def _sample_receipt(
    outcome: str = "completed", *, diagnostic_category: str | None = "source_invalid",
    cancellation: str | None = None,
) -> ExtractionReceipt:
    completed = outcome == "completed"
    bundle = ArtifactReference(
        "sha256:" + "0" * 64, 100, "application/x-repomap-publication-bundle-v1+jsonl",
        "canonical-jsonl-v1", PrivacyClassification.PUBLIC, ArtifactLocator("filesystem", "bundle.jsonl"),
    ) if completed else None
    return ExtractionReceipt.create(
        request_id="req-1", job_id="job-1", attempt=1, graph_id="graph-1",
        worker_capability_identity="worker-v1", contract_version="1.0",
        source_generation="sg1:abc", config_generation="cg1:def",
        extractor_generation="eg1:1", canonicalizer_generation="cg1:1",
        snapshot_manifest_id="snap-1", snapshot_vector=(("file", 10, "sha256:" + "0" * 64),),
        resolver_identity="res-1", extractor_capability_identity="ext-cap-1",
        canonicalizer_identity="canon-1", semantic_contract_identity="sem-1",
        quality_rule_identity="qual-1", outcome=outcome,
        cancellation=cancellation or ("coordinator-requested" if outcome == "cancelled" else "not-requested"),
        bundle_reference=bundle, bundle_id="bun-1" if completed else None,
        family_counts={}, diagnostic_category=None if completed else diagnostic_category,
        diagnostic_summary=(), producer_identity="prod-1", attestation_class="attest-1",
    )


class Slice15CoordinatorPipelineUnitTests(unittest.TestCase):
    def test_s15_c03_protocol_session_validate_terminal(self) -> None:
        """ProtocolSession._validate_terminal validates terminal payload fields, status, and publication states."""
        session = ProtocolSession({"job_id": "job-1", "attempt": 1})
        valid = {
            "job_kind": "refresh_graph", "graph_id": "graph-1", "source_generation": "sg1:gen1",
            "config_generation": "cg1:gen2", "phase": "extraction",
            "started_at": "2026-09-22T12:00:00Z", "finished_at": "2026-09-22T12:05:00Z",
            "extractor_generation": "eg1:ext1", "canonicalizer_generation": "cg1:can1",
            "files": 10, "observations": 50, "canonical_nodes": 20, "canonical_edges": 30,
            "warnings": ["synthetic_warning"], "diagnostics": ["synthetic_diagnostic"],
            "publication_state": "committed", "retryable": False, "status": "succeeded",
            "error_category": None, "latest_run_identity": "run-001",
        }
        session._validate_terminal("result", valid)
        invalids: list[dict[str, Any]] = [
            {"job_kind": "bad_kind"}, {"graph_id": "bad/id"},
            {"source_generation": "invalid_prefix"}, {"config_generation": "invalid_prefix"},
            {"started_at": "2026-09-22T13:00:00Z", "finished_at": "2026-09-22T12:00:00Z"},
            {"extractor_generation": "bad/generation"}, {"files": -1},
            {"publication_state": "unknown_state"}, {"retryable": "not_bool"},
            {"status": "succeeded", "publication_state": "not_started"},
            {"status": "cancelled", "publication_state": "committed"},
        ]
        for patch in invalids:
            with self.assertRaises(ProtocolError):
                session._validate_terminal("result", {**valid, **patch})
        with self.assertRaises(ProtocolError):
            session._validate_terminal("error", {
                **valid, "status": "failed", "error_category": "source_error",
                "publication_state": "not_started", "latest_run_identity": "should_be_none",
            })


    def test_s15_c04_protocol_session_validate_values(self) -> None:
        """ProtocolSession._validate_values enforces constraints on hello, job_start, progress, and heartbeat."""
        session = ProtocolSession({"job_id": "job-1", "attempt": 1})
        for bh in [
            {"protocol_versions": "not_a_list"}, {"protocol_versions": [999]},
            {"protocol_versions": [PROTOCOL_VERSION], "capabilities": ["unsupported_capability"]},
            {"protocol_versions": [PROTOCOL_VERSION], "capabilities": ["refresh_graph"], "worker_generation": "bad/worker", "process_nonce": "nonce1"},
        ]:
            with self.assertRaises(ProtocolError):
                session._validate_values("worker_hello", cast(dict[str, Any], bh))
        for bs in [
            {"job_kind": "unsupported_job", "graph_id": "graph-1", "source_generation": "sg1:a", "config_generation": "cg1:b"},
            {"job_kind": "refresh_graph", "graph_id": "bad/slash", "source_generation": "sg1:a", "config_generation": "cg1:b"},
        ]:
            with self.assertRaises(ProtocolError):
                session._validate_values("job_start", cast(dict[str, Any], bs))
        for bp in [
            {"completed": -1, "total": 10, "phase": "extraction", "unit": "files", "message_category": "info", "heartbeat_at": "2026-09-22T12:00:00Z"},
            {"completed": 15, "total": 10, "phase": "extraction", "unit": "files", "message_category": "info", "heartbeat_at": "2026-09-22T12:00:00Z"},
            {"completed": 5, "total": 10, "phase": "invalid_phase", "unit": "files", "message_category": "info", "heartbeat_at": "2026-09-22T12:00:00Z"},
        ]:
            with self.assertRaises(ProtocolError):
                session._validate_values("progress", cast(dict[str, Any], bp))
        with self.assertRaises(ProtocolError):
            session._validate_values("heartbeat", {"heartbeat_at": "not_a_valid_timestamp"})
        session._validate_values("heartbeat", {"heartbeat_at": "2026-09-22T12:00:00Z"})
        with self.assertRaises(ProtocolError):
            session._validate_values("cancel_ack", {"status": "unrecognized_status"})
        session._validate_values("cancel_ack", {"status": "accepted"})


    def test_s15_c05_protocol_validation_snapshot_extension(self) -> None:
        """_validate_portable_snapshot_result_extension enforces contract versions, outcomes, receipts, and bundles."""
        receipt_ref = ArtifactReference(
            "sha256:" + "0" * 64, 50, "application/x-repomap-extraction-receipt-v1+json",
            "canonical-json-v1", PrivacyClassification.PUBLIC, ArtifactLocator("filesystem", "receipt.json"),
        )
        bundle_ref = ArtifactReference(
            "sha256:" + "0" * 64, 200, "application/x-repomap-publication-bundle-v1+jsonl",
            "canonical-jsonl-v1", PrivacyClassification.PUBLIC, ArtifactLocator("filesystem", "bundle.jsonl"),
        )
        bundle_map = bundle_ref.to_mapping()
        valid_ext = {
            "contract_version": "1.0", "outcome": "completed",
            "receipt": receipt_ref.to_mapping(), "bundle": bundle_map,
        }
        ok_payload = {"status": "succeeded", "error_category": None}
        _validate_portable_snapshot_result_extension(valid_ext, "result", ok_payload)
        for bad_ext in [{"unknown_key": 1}, {**valid_ext, "contract_version": "2.0"}, {**valid_ext, "outcome": 123}]:
            with self.assertRaises(ProtocolError):
                _validate_portable_snapshot_result_extension(bad_ext, "result", ok_payload)
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension(valid_ext, "result", {"status": "failed"})
        cancelled_ext = {**valid_ext, "outcome": "cancelled", "bundle": None}
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension(cancelled_ext, "result", {"status": "succeeded"})
        error_ext = {**valid_ext, "outcome": "source_error", "bundle": None}
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension(error_ext, "error", {"status": "failed", "error_category": "other_error"})
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({**cancelled_ext, "bundle": bundle_map}, "result", {"status": "cancelled"})
        current_ext = {
            "contract_version": "1.0", "outcome": "source_error", "receipt": None,
            "receipt_status": "unavailable", "receipt_diagnostic": "write_failed", "bundle": None,
        }
        _validate_portable_snapshot_result_extension(current_ext, "error", {"status": "failed", "error_category": "source_error"})
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({**current_ext, "receipt_status": "corrupt"}, "error", {"status": "failed", "error_category": "source_error"})


    def test_s15_c06_staging_measurement_event_post_init(self) -> None:
        """StagingMeasurementEvent.__post_init__ verifies schema version, units, families, and bound flags."""
        valid = StagingMeasurementEvent(
            schema_version=SCHEMA_VERSION, category=StagingMeasurementCategory.FAMILY_ROW_COUNT,
            family="files", value=42, unit=StagingMeasurementUnit.ROWS,
            availability=StagingMeasurementAvailability.MEASURED, upper_bound=False,
        )
        self.assertEqual(valid.value, 42)
        for patch in [
            {"schema_version": 99}, {"category": "family_row_count"}, {"unit": "rows"},
            {"unit": StagingMeasurementUnit.BYTES}, {"family": None}, {"value": -1}, {"value": True},
            {"availability": StagingMeasurementAvailability.UNAVAILABLE, "value": 10},
        ]:
            with self.assertRaises(ValueError):
                replace(valid, **cast(dict[str, Any], patch))
        with self.assertRaises(ValueError):
            StagingMeasurementEvent(
                schema_version=SCHEMA_VERSION, category=StagingMeasurementCategory.POSTGRESQL_MEMORY,
                family="files", value=1024, unit=StagingMeasurementUnit.BYTES,
                availability=StagingMeasurementAvailability.MEASURED, upper_bound=False,
            )
        wal_event = StagingMeasurementEvent(
            schema_version=SCHEMA_VERSION, category=StagingMeasurementCategory.WAL_UPPER_BOUND,
            family=None, value=2048, unit=StagingMeasurementUnit.BYTES,
            availability=StagingMeasurementAvailability.MEASURED, upper_bound=True,
        )
        self.assertTrue(wal_event.upper_bound)
        with self.assertRaises(ValueError):
            replace(wal_event, upper_bound=False)


    def test_s15_c07_stage_family_descriptor_post_init(self) -> None:
        """StageFamilyDescriptor.__post_init__ verifies copy columns, ordinals, merge operations, and validation rules."""
        base = STAGING_FAMILY_DESCRIPTORS["files"]
        for patch, err_substr in [
            ({"copy_columns": ("other_col", "stage_id")}, "invalid staging family columns"),
            ({"copy_columns": ("stage_id", "stage_id")}, "invalid staging family columns"),
            ({"technical_ordinal": "missing_column"}, "staging technical ordinal is missing"),
            ({"semantic_ordinal": "missing_column"}, "staging semantic ordinal is missing"),
            ({"identity_columns": ("ghost_column",)}, "staging identity columns are invalid"),
            ({"payload_columns": ()}, "staging payload columns are invalid"),
            ({"merge_dependencies": ("raw_observations", "raw_observations")}, "staging merge dependencies are invalid"),
            ({"merge_dependencies": ("files",)}, "staging family cannot depend on itself"),
            ({"validation_rules": (ValidationRule.ROW_COUNT,)}, "staging validation rules are incomplete"),
        ]:
            with self.assertRaises(ValueError) as ctx:
                replace(base, **cast(dict[str, Any], patch))
            self.assertIn(err_substr, str(ctx.exception))


    def test_s15_c08_receipt_validation(self) -> None:
        """_validate_receipt validates identity string bounds, outcome consistency, and bundle constraints."""
        valid_completed = _sample_receipt("completed")
        _validate_receipt(valid_completed)
        for patch, err_substr in [
            ({"request_id": ""}, "receipt identity field is invalid"),
            ({"job_id": "x" * 257}, "receipt identity field is invalid"),
            ({"attempt": 0}, "receipt attempt is invalid"),
            ({"attempt": True}, "receipt attempt is invalid"),
            ({"outcome": "unknown_outcome"}, "receipt outcome is invalid"),
            ({"diagnostic_category": "bogus_category"}, "receipt diagnostic category is invalid"),
            ({"diagnostic_summary": tuple(f"d-{i}" for i in range(33))}, "receipt diagnostics exceed bounds"),
            ({"diagnostic_summary": ("y" * 257,)}, "receipt diagnostics exceed bounds"),
            ({"bundle_reference": None}, "completed receipt is inconsistent"),
            ({"diagnostic_category": "source_invalid"}, "completed receipt is inconsistent"),
        ]:
            with self.assertRaises(ValueError) as ctx:
                _validate_receipt(replace(valid_completed, **cast(dict[str, Any], patch)))
            self.assertIn(err_substr, str(ctx.exception))

        failed_receipt = _sample_receipt("failed", diagnostic_category="source_invalid")
        _validate_receipt(failed_receipt)
        with self.assertRaises(ValueError) as ctx:
            _validate_receipt(replace(failed_receipt, bundle_id="bun-1"))
        self.assertIn("non-completed receipt cannot accept a bundle", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            _validate_receipt(replace(failed_receipt, diagnostic_category=None))
        self.assertIn("terminal receipt diagnostic is missing", str(ctx.exception))

        cancelled_receipt = _sample_receipt("cancelled", diagnostic_category=None, cancellation="coordinator-requested")
        _validate_receipt(cancelled_receipt)
        with self.assertRaises(ValueError) as ctx:
            _validate_receipt(replace(cancelled_receipt, cancellation="not-requested"))
        self.assertIn("cancelled receipt cancellation state is invalid", str(ctx.exception))


class _FakeStore:
    pass


class _FakeCoordinator:
    def __init__(self, startup_return: object = 1) -> None:
        self.startup_return = startup_return
        self.started = False
        self.shutdown_called = False
        self.shutdown_error: BaseException | None = None

    def startup(self, reconcile_cb: object) -> object:
        self.started = True
        if callable(reconcile_cb):
            reconcile_cb()
        return self.startup_return

    def run_once(self) -> str:
        return "idle"
    def heartbeat(self) -> bool:
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True
        if self.shutdown_error is not None:
            raise self.shutdown_error


class _FakeTransport:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.entered = False
        self.exited = False
        self.enter_error: BaseException | None = None
        self.exit_error: BaseException | None = None

    def __enter__(self) -> _FakeTransport:
        self.entered = True
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.exited = True
        if self.exit_error is not None:
            raise self.exit_error


class _FakeReconciler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.stop_error: BaseException | None = None

    def start(self) -> None:
        self.started = True
    def stop(self) -> None:
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error


class Slice15ServiceLifecycleUnitTests(unittest.TestCase):
    """Slice 15 Group S15-C integration tests for coordinator, protocol, staging, and receipts."""

    def test_s15_c01_coordinator_service_start(self) -> None:
        """CoordinatorService.start handles epoch fencing, descriptor endpoints, double-start refusal, and errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            fake_coord = _FakeCoordinator(startup_return=5)
            service = CoordinatorService(
                cast(Any, fake_coord), cast(Any, _FakeStore()), temp_path,
                transport_factory=lambda *a, **kw: _FakeTransport(*a, **kw),
                idle_poll_seconds=0.01, heartbeat_seconds=0.01,
            )
            reconciled = []
            service.start(lambda: reconciled.append(True))
            self.assertEqual(fake_coord.startup_return, 5)
            self.assertEqual(service._fencing_epoch, 5)
            self.assertTrue(reconciled)
            self.assertEqual(service._state, "ready")

            with self.assertRaises(RuntimeError) as ctx:
                service.start(lambda: None)
            self.assertIn("already started", str(ctx.exception))
            service.stop()
            self.assertEqual(service._state, "stopped")

            service_desc = CoordinatorService(
                cast(Any, _FakeCoordinator(startup_return=None)), cast(Any, _FakeStore()), temp_path,
                transport_factory=lambda *a, **kw: _FakeTransport(*a, **kw),
                idle_poll_seconds=0.01, heartbeat_seconds=0.01,
            )
            service_desc.token_path = service_desc.socket_path
            service_desc.start(lambda: None)
            self.assertEqual(service_desc._fencing_epoch, 1)
            service_desc.stop()

            reconciler = _FakeReconciler()
            bad_transport = _FakeTransport()
            bad_transport.enter_error = RuntimeError("transport fail")
            failing_service = CoordinatorService(
                cast(Any, _FakeCoordinator(startup_return=1)), cast(Any, _FakeStore()), temp_path,
                desired_reconciler=cast(Any, reconciler), transport_factory=lambda *a, **kw: bad_transport,
                idle_poll_seconds=0.01, heartbeat_seconds=0.01,
            )
            with self.assertRaises(RuntimeError) as ctx:
                failing_service.start(lambda: None)
            self.assertIn("transport fail", str(ctx.exception))
            self.assertEqual(failing_service._state, "stopped")
            self.assertTrue(reconciler.stopped)

    def test_s15_c02_coordinator_service_stop(self) -> None:
        """CoordinatorService.stop supports double-stop idempotency, reconciler failures, and endpoint cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            reconciler = _FakeReconciler()
            transport = _FakeTransport()
            service = CoordinatorService(
                cast(Any, _FakeCoordinator(startup_return=1)), cast(Any, _FakeStore()), temp_path,
                desired_reconciler=cast(Any, reconciler), transport_factory=lambda *a, **kw: transport,
                idle_poll_seconds=0.01, heartbeat_seconds=0.01,
            )
            self.assertEqual(service._state, "stopped")
            service.stop()
            self.assertEqual(service._state, "stopped")

            service.start(lambda: None)
            service.stop()
            self.assertEqual(service._state, "stopped")
            self.assertTrue(transport.exited)
            self.assertTrue(reconciler.stopped)

            service.start(lambda: None)
            reconciler.stop_error = RuntimeError("reconciler stop failure")
            with self.assertRaises(RuntimeError) as ctx:
                service.stop()
            self.assertIn("reconciler stop failure", str(ctx.exception))
            self.assertEqual(service._state, "stopped")

            service.start(lambda: None)
            reconciler.stop_error = None
            transport.exit_error = RuntimeError("transport exit failure")
            with self.assertRaises(RuntimeError) as ctx:
                service.stop()
            self.assertIn("transport exit failure", str(ctx.exception))

            service_desc = CoordinatorService(
                cast(Any, _FakeCoordinator(startup_return=1)), cast(Any, _FakeStore()), temp_path,
                transport_factory=lambda *a, **kw: _FakeTransport(*a, **kw),
                idle_poll_seconds=0.01, heartbeat_seconds=0.01,
            )
            service_desc.token_path = service_desc.socket_path
            service_desc.start(lambda: None)
            service_desc.stop()
            self.assertEqual(service_desc._state, "stopped")
