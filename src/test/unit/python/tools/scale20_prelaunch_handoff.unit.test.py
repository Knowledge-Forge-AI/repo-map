from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
import json
import operator
from typing import Any, cast
import pytest

from repomap_kg.storage.authority import PublicationGenerations
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
    FINAL_FAMILY_CODES,
)
from scale20_prelaunch_handoff import (
    FinalFamilyCountRecord,
    MAX_FAMILY_ROW_COUNT,
    MAX_PRELAUNCH_RESULT_BYTES,
    OrderedFinalFamilyCounts,
    PrelaunchHandoffError,
    ProtectedPrelaunchResult,
    decode_ordered_family_worker_payload,
    decode_prelaunch_result,
    encode_ordered_family_worker_payload,
    encode_prelaunch_result,
    receive_prelaunch_result,
)


def _counts(value: int = 0) -> dict[object, object]:
    return {family_code: value for family_code in FINAL_FAMILY_CODES}


def _result(
    counts: Mapping[object, object] | None = None,
) -> ProtectedPrelaunchResult:
    return ProtectedPrelaunchResult(
        category="complete",
        repository_identity="repo1:public-fixture",
        repository_name="public-fixture",
        generations=PublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer",
        ),
        execution_mode="direct",
        zero_state_first_publication=True,
        family_counts=OrderedFinalFamilyCounts.from_mapping(
            _counts() if counts is None else counts
        ),
        structural_digest="a" * 64,
    )


def _payload() -> dict[str, Any]:
    return _result().to_payload()


def _decode_payload(payload: Any) -> ProtectedPrelaunchResult:
    return decode_prelaunch_result(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _assert_category(category: str, operation) -> None:
    with pytest.raises(PrelaunchHandoffError) as raised:
        operation()
    assert raised.value.category == category
    assert str(raised.value) == category


def test_exact_seven_family_round_trip_preserves_typed_order() -> None:
    result = _result(
        {
            family_code: row_count
            for row_count, family_code in enumerate(FINAL_FAMILY_CODES)
        }
    )

    decoded = decode_prelaunch_result(encode_prelaunch_result(result))
    mapping = decoded.family_counts.to_mapping()

    assert tuple(mapping) == FINAL_FAMILY_CODES
    assert dict(mapping) == dict(result.family_counts.to_mapping())


def test_sorted_outer_json_preserves_family_array_order() -> None:
    payload = _payload()

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    decoded = json.loads(encoded)

    assert [
        record["family_code"] for record in decoded["family_counts"]
    ] == list(FINAL_FAMILY_CODES)


def test_worker_payload_reconstructs_exact_mapping_order() -> None:
    encoded = encode_ordered_family_worker_payload(
        {"schema_version": 1, "family_counts": _counts()}
    )

    decoded = decode_ordered_family_worker_payload(encoded)
    family_counts = decoded["family_counts"]
    assert isinstance(family_counts, dict)
    assert tuple(family_counts) == FINAL_FAMILY_CODES


def test_unchanged_results_encode_to_identical_bytes() -> None:
    assert encode_prelaunch_result(_result()) == encode_prelaunch_result(_result())


def test_legacy_family_count_object_is_rejected() -> None:
    payload = _payload()
    payload["family_counts"] = _counts()

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


def test_alphabetically_sorted_family_sequence_is_rejected() -> None:
    payload = _payload()
    payload["family_counts"] = sorted(
        payload["family_counts"],
        key=lambda record: record["family_code"],
    )

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


@pytest.mark.parametrize("index", [0, 3, 6])
def test_missing_first_middle_or_final_family_is_rejected(index: int) -> None:
    payload = _payload()
    del payload["family_counts"][index]

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


def test_extra_family_is_rejected() -> None:
    payload = _payload()
    payload["family_counts"].append(
        {"family_code": "extra_family", "row_count": 0}
    )

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


def test_unknown_family_is_rejected() -> None:
    payload = _payload()
    payload["family_counts"][3]["family_code"] = "unknown_family"

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


@pytest.mark.parametrize("changed_count", [0, 19])
def test_duplicate_identical_or_changed_family_is_rejected(
    changed_count: int,
) -> None:
    payload = _payload()
    payload["family_counts"][3] = {
        "family_code": payload["family_counts"][2]["family_code"],
        "row_count": changed_count,
    }

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


@pytest.mark.parametrize("count", [0, MAX_FAMILY_ROW_COUNT])
def test_zero_and_maximum_family_counts_are_accepted(count: int) -> None:
    decoded = decode_prelaunch_result(
        encode_prelaunch_result(_result(_counts(count)))
    )

    assert set(decoded.family_counts.to_mapping().values()) == {count}


@pytest.mark.parametrize("count", [MAX_FAMILY_ROW_COUNT + 1, True, -1, 1.5, "1", None])
def test_invalid_family_count_values_are_rejected(count: object) -> None:
    payload = _payload()
    payload["family_counts"][0]["row_count"] = count

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


@pytest.mark.parametrize(
    "record",
    [{"family_code": "files"}, {"row_count": 0}, {"family_code": "files", "row_count": 0, "extra": False}],
)
def test_missing_or_extra_record_fields_are_rejected(
    record: dict[str, object],
) -> None:
    payload = _payload()
    payload["family_counts"][0] = record

    _assert_category(
        "prelaunch_result.family_counts_invalid",
        lambda: _decode_payload(payload),
    )


def test_duplicate_top_level_json_key_is_rejected() -> None:
    encoded = encode_prelaunch_result(_result()).decode("utf-8")
    duplicated = encoded[:-1] + ',"category":"complete"}'

    _assert_category(
        "prelaunch_result.duplicate_key",
        lambda: decode_prelaunch_result(duplicated),
    )


def test_duplicate_record_json_key_is_rejected() -> None:
    encoded = encode_prelaunch_result(_result()).decode("utf-8")
    duplicated = encoded.replace(
        '"family_code":"files"',
        '"family_code":"files","family_code":"files"',
        1,
    )

    _assert_category(
        "prelaunch_result.duplicate_key",
        lambda: decode_prelaunch_result(duplicated),
    )


def test_unsupported_schema_is_rejected() -> None:
    payload = _payload()
    payload["schema_version"] = 2

    _assert_category(
        "prelaunch_result.schema_unsupported",
        lambda: _decode_payload(payload),
    )


@pytest.mark.parametrize("payload", ["{", "{} trailing", b"\xff"])
def test_malformed_truncated_or_trailing_result_is_rejected(
    payload: bytes | str,
) -> None:
    _assert_category(
        "prelaunch_result.invalid_json",
        lambda: decode_prelaunch_result(payload),
    )


def test_oversized_result_is_rejected() -> None:
    payload = "{" + (" " * MAX_PRELAUNCH_RESULT_BYTES) + "}"

    _assert_category(
        "prelaunch_result.oversized",
        lambda: decode_prelaunch_result(payload),
    )


def test_non_success_category_is_not_a_complete_expectation() -> None:
    payload = _payload()
    payload["category"] = "worker_failed"

    _assert_category(
        "prelaunch_result.category_invalid",
        lambda: _decode_payload(payload),
    )


def test_nonzero_worker_exit_is_rejected_without_decoding_payload() -> None:
    _assert_category(
        "prelaunch_worker.failed",
        lambda: receive_prelaunch_result(
            returncode=7,
            stdout=encode_prelaunch_result(_result()),
        ),
    )


def test_successful_worker_exit_without_payload_is_rejected() -> None:
    _assert_category(
        "prelaunch_worker.result_missing",
        lambda: receive_prelaunch_result(returncode=0, stdout=b""),
    )


def test_cancellation_during_result_handoff_accepts_no_expectation() -> None:
    checks = 0

    def cancel_after_decode() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("private cancellation detail")

    _assert_category(
        "prelaunch_worker.cancelled",
        lambda: receive_prelaunch_result(
            returncode=0,
            stdout=encode_prelaunch_result(_result()),
            cancellation_check=cancel_after_decode,
        ),
    )


@pytest.mark.parametrize(
    "field",
    ["repository_identity", "generations", "structural_digest"],
)
def test_missing_expectation_authority_field_is_rejected(field: str) -> None:
    payload = _payload()
    del payload[field]

    _assert_category(
        "prelaunch_result.fields_invalid",
        lambda: _decode_payload(payload),
    )


def test_unknown_top_level_field_is_rejected() -> None:
    payload = _payload()
    payload["private_value"] = "must-not-leak"

    _assert_category(
        "prelaunch_result.fields_invalid",
        lambda: _decode_payload(payload),
    )


def test_errors_do_not_expose_private_values() -> None:
    payload = _payload()
    payload["repository_identity"] = "private-sensitive-value"

    with pytest.raises(PrelaunchHandoffError) as raised:
        _decode_payload(payload)

    assert "private-sensitive-value" not in str(raised.value)
    assert len(str(raised.value)) < 80


def test_family_contract_and_mapping_are_immutable() -> None:
    counts = OrderedFinalFamilyCounts.from_mapping(_counts())
    mapping = counts.to_mapping()

    with pytest.raises(TypeError):
        operator.setitem(cast(dict[str, int], mapping), "files", 1)
    with pytest.raises(FrozenInstanceError):
        setattr(counts.records[0], "row_count", 1)


def test_existing_authority_accepts_reconstructed_exact_order() -> None:
    authority = decode_prelaunch_result(
        encode_prelaunch_result(_result())
    ).to_expected_refresh_authority()

    assert authority.validate() is authority
    assert tuple(authority.expected_family_counts) == FINAL_FAMILY_CODES


def test_existing_authority_rejects_deliberately_reordered_mapping() -> None:
    result = _result()
    reordered = dict(reversed(tuple(result.family_counts.to_mapping().items())))
    authority = ExpectedRefreshAuthority(
        repository_identity=result.repository_identity,
        repository_name=result.repository_name,
        generations=result.generations,
        execution_mode=result.execution_mode,
        zero_state_first_publication=result.zero_state_first_publication,
        expected_family_counts=reordered,
        expected_structural_digest=result.structural_digest,
    )

    with pytest.raises(ValueError, match="expected family counts are invalid"):
        authority.validate()


def test_direct_record_construction_rejects_non_tuple_storage() -> None:
    records = [FinalFamilyCountRecord(code, 0) for code in FINAL_FAMILY_CODES]
    with pytest.raises(PrelaunchHandoffError):
        OrderedFinalFamilyCounts(cast(tuple[FinalFamilyCountRecord, ...], records))
