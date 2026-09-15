from __future__ import annotations

from dataclasses import replace
import json

import pytest

from repomap_kg.storage.authority import PublicationGenerations
from scale15_terminal_contracts import FINAL_FAMILY_CODES
from scale20_prelaunch_handoff import (
    FinalFamilyCountRecord,
    OrderedFinalFamilyCounts,
    ProtectedPrelaunchResult,
)
from scale25_prelaunch_reporting import (
    PrelaunchExecutionResult,
    PrelaunchReportingError,
    PublicSafePrelaunchProjection,
    decode_public_prelaunch_projection,
    encode_public_prelaunch_projection,
    operational_report_header,
    validate_projection_agreement,
)


_COMPLETE_PHASES = (
    "worker_result",
    "process_rss_attached",
    "resource_limits_validated",
    "ordered_family_handoff_validated",
    "expected_authority_validated",
)


def _protected_result() -> ProtectedPrelaunchResult:
    return ProtectedPrelaunchResult(
        category="complete",
        repository_identity="repo1:private-identity",
        repository_name="private-name",
        generations=PublicationGenerations(
            "sg1:private-source",
            "cg1:private-config",
            "eg1:private-extractor",
            "kg1:private-canonicalizer",
        ),
        execution_mode="direct",
        zero_state_first_publication=True,
        family_counts=OrderedFinalFamilyCounts(
            tuple(
                FinalFamilyCountRecord(code, index + 101)
                for index, code in enumerate(FINAL_FAMILY_CODES)
            )
        ),
        structural_digest="a" * 64,
    ).validate()


def _result(outcome: str = "accepted") -> PrelaunchExecutionResult:
    cases = {
        "accepted": PrelaunchExecutionResult(
            outcome="accepted",
            terminal_category="prelaunch_complete",
            completed_phases=_COMPLETE_PHASES,
            resource_status="accepted",
            process_settled=True,
            artifact_cleanup_status="clean",
            source_cleanliness_status="clean",
            expectation_status="accepted",
            protected_result=_protected_result(),
        ),
        "bounded_stop": PrelaunchExecutionResult(
            outcome="bounded_stop",
            terminal_category="resource_limit_reached",
            completed_phases=_COMPLETE_PHASES[:3],
            resource_status="bounded_stop",
            process_settled=True,
            artifact_cleanup_status="clean",
            source_cleanliness_status="clean",
            expectation_status="rejected",
            protected_result=None,
        ),
        "worker_failure": PrelaunchExecutionResult(
            outcome="worker_failure",
            terminal_category="worker_failed",
            completed_phases=(),
            resource_status="unavailable",
            process_settled=True,
            artifact_cleanup_status="clean",
            source_cleanliness_status="clean",
            expectation_status="not_evaluated",
            protected_result=None,
        ),
        "result_validation_failure": PrelaunchExecutionResult(
            outcome="result_validation_failure",
            terminal_category="result_invalid",
            completed_phases=_COMPLETE_PHASES[:4],
            resource_status="accepted",
            process_settled=True,
            artifact_cleanup_status="clean",
            source_cleanliness_status="clean",
            expectation_status="rejected",
            protected_result=None,
        ),
        "launch_refusal": PrelaunchExecutionResult(
            outcome="launch_refusal",
            terminal_category="launch_refused",
            completed_phases=_COMPLETE_PHASES,
            resource_status="accepted",
            process_settled=True,
            artifact_cleanup_status="clean",
            source_cleanliness_status="clean",
            expectation_status="accepted",
            protected_result=_protected_result(),
        ),
    }
    return cases[outcome].validate()


@pytest.mark.parametrize(
    "outcome",
    (
        "accepted",
        "bounded_stop",
        "worker_failure",
        "result_validation_failure",
        "launch_refusal",
    ),
)
def test_public_projection_preserves_closed_internal_outcomes(outcome: str) -> None:
    internal = _result(outcome)

    projection = PublicSafePrelaunchProjection.from_internal(internal)
    decoded = decode_public_prelaunch_projection(
        encode_public_prelaunch_projection(projection)
    )

    validate_projection_agreement(internal, decoded)
    assert decoded.outcome == outcome


def test_public_projection_is_deterministic_bounded_and_private_value_free() -> None:
    projection = PublicSafePrelaunchProjection.from_internal(_result())

    first = encode_public_prelaunch_projection(projection)
    second = encode_public_prelaunch_projection(projection)

    assert first == second
    assert len(first) < 4096
    for forbidden in (
        b"private-identity",
        b"private-name",
        b"private-source",
        b"private-config",
        b"private-extractor",
        b"private-canonicalizer",
        b"structural_digest",
        b"family_counts",
        b"repository_identity",
        b"temporary_artifact_peak_run_count",
        b"/private/",
    ):
        assert forbidden not in first


@pytest.mark.parametrize(
    "mutator",
    (
        lambda payload: payload.pop("process_settled"),
        lambda payload: payload.update(extra="forbidden"),
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(outcome="unknown"),
        lambda payload: payload.update(terminal_category="unknown"),
        lambda payload: payload.update(process_settled=1),
        lambda payload: payload.update(completed_phases="worker_result"),
        lambda payload: payload.update(outcome=[]),
        lambda payload: payload.update(resource_status={}),
    ),
)
def test_public_projection_rejects_malformed_or_unknown_fields(mutator) -> None:
    payload = json.loads(encode_public_prelaunch_projection(
        PublicSafePrelaunchProjection.from_internal(_result())
    ))
    mutator(payload)

    with pytest.raises(PrelaunchReportingError):
        decode_public_prelaunch_projection(json.dumps(payload))


def test_public_projection_rejects_duplicate_json_keys() -> None:
    encoded = encode_public_prelaunch_projection(
        PublicSafePrelaunchProjection.from_internal(_result())
    ).decode("utf-8")
    duplicate = encoded.replace(
        '"outcome":"accepted"',
        '"outcome":"accepted","outcome":"accepted"',
    )

    with pytest.raises(PrelaunchReportingError, match="duplicate"):
        decode_public_prelaunch_projection(duplicate)


def test_public_projection_rejects_oversized_payload() -> None:
    with pytest.raises(PrelaunchReportingError, match="oversized"):
        decode_public_prelaunch_projection(" " * 4097)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("outcome", "bounded_stop"),
        ("terminal_category", "launch_refused"),
        ("completed_phases", _COMPLETE_PHASES[:-1]),
        ("process_settled", False),
        ("resource_status", "bounded_stop"),
        ("artifact_cleanup_status", "unproved"),
        ("source_cleanliness_status", "unproved"),
        ("expectation_status", "rejected"),
    ),
)
def test_projection_agreement_rejects_internal_public_mismatch(
    field: str,
    value,
) -> None:
    internal = _result()
    projection = replace(
        PublicSafePrelaunchProjection.from_internal(internal),
        **{field: value},
    )

    with pytest.raises(PrelaunchReportingError, match="agreement"):
        validate_projection_agreement(internal, projection)


def test_complete_projection_cannot_be_built_from_partial_internal_state() -> None:
    internal = replace(_result(), completed_phases=_COMPLETE_PHASES[:-1])

    with pytest.raises(PrelaunchReportingError):
        PublicSafePrelaunchProjection.from_internal(internal)


def test_operational_report_header_is_a_separate_canonical_envelope() -> None:
    header = operational_report_header(
        phase="SCALE25",
        outcome="accepted",
        primary_commit="7fe3d1d33e85f436acce3e6d21c90232dbf8d4c7",
    )

    assert header == (
        "report_schema: operational-report-v1\n"
        "phase: SCALE25\n"
        "outcome: accepted\n"
        "primary_commit: 7fe3d1d33e85f436acce3e6d21c90232dbf8d4c7\n"
    )
    assert b"report_schema" not in encode_public_prelaunch_projection(
        PublicSafePrelaunchProjection.from_internal(_result())
    )


@pytest.mark.parametrize(
    "arguments",
    (
        {
            "phase": "scale25",
            "outcome": "accepted",
            "primary_commit": "7fe3d1d33e85f436acce3e6d21c90232dbf8d4c7",
        },
        {
            "phase": "SCALE25",
            "outcome": "complete",
            "primary_commit": "7fe3d1d33e85f436acce3e6d21c90232dbf8d4c7",
        },
        {
            "phase": "SCALE25",
            "outcome": "accepted",
            "primary_commit": "not-a-commit",
        },
    ),
)
def test_operational_report_header_rejects_open_vocabulary(arguments) -> None:
    with pytest.raises(PrelaunchReportingError):
        operational_report_header(**arguments)
