from __future__ import annotations

import json
from dataclasses import replace
from itertools import count
from typing import TypedDict, cast

import pytest

from repomap_kg.storage import staged_publication, staging_cleanup
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staged_publication import _execute_measured_merge
from repomap_kg.storage.staged_validation import validate_stage
from repomap_kg.storage.staging_cleanup import CleanupRequest
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope
from repomap_kg.storage.staging_observability import (
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_kg.storage.staging_family_contracts import StageFamily
from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
    StagingOperationGroup,
    operation_code_for_merge,
    operation_descriptor,
)
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from repomap_kg.storage.staging_ownership import StageOwner


FAMILIES = (
    "files", "raw_observations", "canonical_nodes", "canonical_edges",
    "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
)

EXPECTED_CODES = (
    "statistics.canonical_node_evidence",
    *(f"completeness.{family}" for family in FAMILIES),
    "guard.publication_prepare", "transaction.mark_merging",
    "guard.source_index_stage", "guard.source_index_proposals",
    "merge.files", "merge.raw_observations",
    "guard.canonical_stage", "guard.canonical_proposals",
    "guard.canonical_raw_reference", "merge.canonical_nodes",
    "merge.canonical_evidence", "guard.canonical_edge_reference",
    "merge.canonical_edges", "guard.canonical_node_evidence_reference",
    "merge.canonical_node_evidence", "guard.canonical_edge_evidence_reference",
    "merge.canonical_edge_evidence", "guard.publication_finalize",
    "receipt.finalize", "transaction.commit", "cleanup.stage",
)

_SOURCE_INDEX_CODES = [
    "guard.source_index_stage", "guard.source_index_proposals",
    "merge.files", "merge.raw_observations",
]
_CANONICAL_CODES = [
    "guard.canonical_stage", "guard.canonical_proposals",
    "guard.canonical_raw_reference", "merge.canonical_nodes",
    "merge.canonical_evidence", "guard.canonical_edge_reference",
    "merge.canonical_edges", "guard.canonical_node_evidence_reference",
    "merge.canonical_node_evidence", "guard.canonical_edge_evidence_reference",
    "merge.canonical_edge_evidence",
]


def _clock(*values: int):
    current = iter(values)
    return lambda: next(current)


def test_scale12_operation_registry_is_closed_stable_and_source_owned() -> None:
    assert tuple(STAGING_OPERATION_DESCRIPTORS) == EXPECTED_CODES
    assert len(set(EXPECTED_CODES)) == len(EXPECTED_CODES)
    for group in (StagingOperationGroup.COMPLETENESS_VALIDATION, StagingOperationGroup.MERGE):
        assert {
            d.family for d in STAGING_OPERATION_DESCRIPTORS.values()
            if d.operation_group is group
        } == set(FAMILIES)
    assert all(
        d.source_module.startswith("repomap_kg.storage.")
        and d.source_symbol and d.expected_parent is None
        for d in STAGING_OPERATION_DESCRIPTORS.values()
    )
    assert all("legacy" not in code for code in EXPECTED_CODES)


def test_scale12_operation_registry_public_projection_is_structural_only() -> None:
    payloads = [
        descriptor.to_public_payload()
        for descriptor in STAGING_OPERATION_DESCRIPTORS.values()
    ]
    assert set(payloads[0]) == {
        "schema_version", "operation_code", "operation_group", "family",
        "transaction_scope", "expected_parent", "repeat_policy",
        "cancellable", "public_description_category",
    }
    encoded = json.dumps(payloads, sort_keys=True)
    for forbidden in (
        "source_module", "source_symbol", "SELECT ", "INSERT ", "UPDATE ", "DELETE ",
        "/Users/", "backend_pid", "database_name", "receipt_id", "stage_id", "run_id",
    ):
        assert forbidden not in encoded


def test_scale12_unknown_operation_code_fails_closed() -> None:
    with pytest.raises(ValueError, match="operation code"):
        operation_descriptor("merge.legacy_nodes")


_DescriptorChanges = TypedDict("_DescriptorChanges", {
    "schema_version": int, "operation_code": str, "operation_group": StagingOperationGroup,
    "family": StageFamily | None, "transaction_scope": str, "expected_parent": str | None,
    "repeat_policy": str, "cancellable": bool, "public_description_category": str,
    "source_module": str, "source_symbol": str,
}, total=False)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": 2}, "schema version"),
        ({"operation_code": ""}, "operation code"),
        ({"operation_group": "merge"}, "operation group"),
        ({"family": "legacy_nodes"}, "operation family"),
        ({"transaction_scope": "unknown"}, "transaction scope"),
        ({"expected_parent": "publication"}, "nested"),
        ({"repeat_policy": "unbounded"}, "repeat policy"),
        ({"cancellable": 1}, "cancellation flag"),
        ({"public_description_category": "guard"}, "description category"),
        ({"source_module": "external.module"}, "source module"),
        ({"source_symbol": ""}, "source symbol"),
    ),
)
def test_scale12_operation_descriptor_rejects_invalid_contract_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    descriptor = operation_descriptor("merge.files")

    with pytest.raises(ValueError, match=message):
        replace(descriptor, **cast(_DescriptorChanges, changes))


def test_scale12_lifecycle_emits_start_and_completion_with_one_sequence() -> None:
    aggregate_events: list[StagingMeasurementEvent] = []
    operation_events: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(
        aggregate_events.append,
        operation_sink=operation_events.append,
        monotonic_ns=_clock(100, 110, 160, 170),
    )

    with measurements.operation("merge.files"):
        pass

    assert aggregate_events == []
    assert [event.event_category for event in operation_events] == [
        StagingOperationEventCategory.STARTED,
        StagingOperationEventCategory.COMPLETED,
    ]
    assert [event.attempt_local_sequence for event in operation_events] == [1, 1]
    assert operation_events[0].monotonic_offset_ns == 10
    assert operation_events[0].duration_ns is None
    assert operation_events[1].monotonic_offset_ns == 60
    assert operation_events[1].duration_ns == 50
    assert operation_events[1].terminal_category == "completed"


@pytest.mark.parametrize(
    ("raised", "expected"),
    (
        (RuntimeError("boom"), StagingOperationEventCategory.FAILED),
        (KeyboardInterrupt(), StagingOperationEventCategory.CANCELLED),
    ),
)
def test_scale12_lifecycle_emits_one_terminal_when_operation_unwinds(
    raised: BaseException,
    expected: StagingOperationEventCategory,
) -> None:
    events: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(
        lambda _event: None,
        operation_sink=events.append,
        monotonic_ns=_clock(100, 110, 160, 170),
    )

    with pytest.raises(type(raised)):
        with measurements.operation("guard.canonical_proposals"):
            raise raised

    assert [event.event_category for event in events] == [
        StagingOperationEventCategory.STARTED,
        expected,
    ]
    assert events[1].terminal_category == expected.value


def test_scale12_operation_sink_failure_is_non_authoritative() -> None:
    calls = 0

    def reject(_event: object) -> None:
        nonlocal calls
        calls += 1
        raise OSError("closed")

    measurements = StagingMeasurements(
        lambda _event: None,
        operation_sink=reject,
        monotonic_ns=_clock(100, 110, 120),
    )

    with measurements.operation("receipt.finalize"):
        pass
    assert calls == 1
    assert measurements.failed is True
    assert measurements.operation_event_count == 0


def test_scale12_lifecycle_is_inactive_without_operation_sink() -> None:
    measurements = StagingMeasurements(
        lambda _event: None,
        monotonic_ns=_clock(100),
    )

    with measurements.operation("merge.files"):
        pass

    assert measurements.operation_event_count == 0


class _Cursor:
    def __init__(self, row: tuple[object, ...] = (1,)) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...]:
        return self._row


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str, *_args: object) -> _Cursor:
        self.statements.append(statement)
        return _Cursor((True,) if "advisory" in statement else (1,))


def _operation_measurements(
    events: list[StagingOperationEvent],
) -> StagingMeasurements:
    ticks = count(0, 10)
    return StagingMeasurements(
        lambda _event: None,
        operation_sink=events.append,
        monotonic_ns=lambda: next(ticks),
    )


def _started_codes(events: list[StagingOperationEvent]) -> list[str]:
    return [
        event.operation_code
        for event in events
        if event.event_category is StagingOperationEventCategory.STARTED
    ]


def test_scale12_merge_operation_mapping_is_exhaustive_and_stable() -> None:
    assert tuple(operation_code_for_merge(op) for op in MergeOperation) == (
        "merge.files", "merge.raw_observations", "guard.canonical_raw_reference",
        "merge.canonical_nodes", "merge.canonical_evidence", "guard.canonical_edge_reference",
        "merge.canonical_edges", "guard.canonical_node_evidence_reference",
        "merge.canonical_node_evidence", "guard.canonical_edge_evidence_reference",
        "merge.canonical_edge_evidence",
    )


def test_scale12_completeness_queries_emit_exact_family_operations() -> None:
    events: list[StagingOperationEvent] = []
    connection = _Connection()
    measurements = _operation_measurements(events)

    validate_stage(
        connection,
        "public-stage",
        {family: 1 for family in FAMILIES},
        staging_measurements=measurements,
    )

    assert _started_codes(events) == [
        f"completeness.{family}" for family in FAMILIES
    ]
    assert len(connection.statements) == len(FAMILIES)


@pytest.mark.parametrize(
    ("scope", "statement_count", "expected"),
    (
        (MergeScope.SOURCE_INDEX, 4, _SOURCE_INDEX_CODES),
        (MergeScope.CANONICAL, 11, _CANONICAL_CODES),
    ),
)
def test_scale12_measured_merge_preserves_statement_order_with_exact_operations(
    scope: MergeScope,
    statement_count: int,
    expected: list[str],
) -> None:
    events: list[StagingOperationEvent] = []
    connection = _Connection()
    statements = tuple(f"statement-{index}" for index in range(statement_count))

    _execute_measured_merge(
        connection,
        statements,
        scope,
        _operation_measurements(events),
    )

    assert connection.statements == list(statements)
    assert _started_codes(events) == expected


def _owner() -> StageOwner:
    return StageOwner(1, OperationId("scale12"), AttemptNumber(1), "direct", "sg", "cg", "eg", "kg")


def test_scale12_final_transaction_attributes_prepare_merge_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[StagingOperationEvent] = []
    connection = _Connection()
    owner = _owner()
    handoff = PublicationHandoff(
        MergeContext("stage-scale12", owner, 1),
        RunPublicationReceipt(
            RunPublicationAttempt(JobId("scale12"), AttemptNumber(1)),
            RunPublicationGenerations("sg", "cg", "eg", "kg"),
        ),
    )
    monkeypatch.setattr(
        staged_publication, "build_publication_prepare_statements",
        lambda _h: ("prepare-guard", "mark-merging"),
    )
    monkeypatch.setattr(
        staged_publication, "build_source_index_merge_statements",
        lambda _m: tuple(f"source-{index}" for index in range(4)),
    )
    monkeypatch.setattr(
        staged_publication, "build_canonical_merge_statements",
        lambda _m: tuple(f"canonical-{index}" for index in range(11)),
    )
    monkeypatch.setattr(
        staged_publication, "build_publication_finalize_statements",
        lambda _h: ("finalize-guard", "receipt"),
    )

    staged_publication.execute_final_transaction(
        connection,
        handoff,
        staging_measurements=_operation_measurements(events),
    )

    assert _started_codes(events) == [
        "guard.publication_prepare", "transaction.mark_merging",
        *_SOURCE_INDEX_CODES, *_CANONICAL_CODES,
        "guard.publication_finalize", "receipt.finalize",
    ]


def test_scale12_cleanup_emits_exact_operation_without_changing_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[StagingOperationEvent] = []
    connection = _Connection()
    request = CleanupRequest(_owner(), "stage-scale12", False)
    monkeypatch.setattr(
        staging_cleanup, "build_stage_cleanup_statements",
        lambda _request: ("cleanup-statement",),
    )

    staging_cleanup.execute_stage_cleanup(
        connection,
        request,
        staging_measurements=_operation_measurements(events),
    )

    assert connection.statements == ["cleanup-statement"]
    assert _started_codes(events) == ["cleanup.stage"]
