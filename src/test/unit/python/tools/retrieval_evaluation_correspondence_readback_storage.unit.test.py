"""Storage publication parser and readback shape boundaries for W5 correspondence."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch
from typing import cast

import pytest

from common_lore_index.storage.authority import AttemptNumber, JobId
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
    publication_generations_from_mapping,
    publication_receipt_from_mapping,
)
from common_lore_index.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_test_support.w5_publication_readback import (
    all_null_receipt_mapping,
    legacy_receipt_mapping,
    mapping_process,
    portable_json_mutation,
    portable_receipt_mapping,
)


def _generations() -> RunPublicationGenerations:
    return RunPublicationGenerations(
        "sg1:readback-source",
        "cg1:readback-config",
        "eg1:readback-extractor",
        "kg1:readback-canonicalizer",
    )


def _attempt() -> RunPublicationAttempt:
    return RunPublicationAttempt(JobId("job-readback-1"), AttemptNumber(1))


def test_publication_generation_parser_preserves_all_null_and_rejects_shape_boundaries() -> None:
    """Legacy NULL rows remain absent; partial, non-mapping, and typed rows refuse."""
    assert publication_generations_from_mapping(all_null_receipt_mapping()) is None
    bad_payloads: tuple[object, ...] = (None, [], "not-a-mapping")
    for payload in bad_payloads:
        with pytest.raises(ValueError, match="invalid publication generations"):
            publication_generations_from_mapping(payload)

    partial = all_null_receipt_mapping()
    partial["source_generation"] = "sg1:readback-source"
    with pytest.raises(ValueError, match="invalid publication generations"):
        publication_generations_from_mapping(partial)

    wrong_type = all_null_receipt_mapping()
    wrong_type.update(
        {
            "source_generation": 1,
            "config_generation": "cg1:readback-config",
            "extractor_generation": "eg1:readback-extractor",
            "canonicalizer_generation": "kg1:readback-canonicalizer",
        }
    )
    with pytest.raises(ValueError, match="invalid publication generations"):
        publication_generations_from_mapping(wrong_type)


def test_publication_receipt_parser_rejects_partial_portable_and_malformed_json() -> None:
    """Receipt rows are all-null or complete, including both JSON subdocuments."""
    assert publication_receipt_from_mapping(all_null_receipt_mapping()) is None
    bad_payloads: tuple[object, ...] = (None, [], {"publication_job_id": "job-readback-1"})
    for payload in bad_payloads:
        with pytest.raises(ValueError, match="invalid publication"):
            publication_receipt_from_mapping(payload)

    partial_portable = portable_receipt_mapping()
    partial_portable["family_receipts_json"] = None
    with pytest.raises(ValueError, match="invalid portable publication binding"):
        publication_receipt_from_mapping(partial_portable)

    for field, value in (
        ("snapshot_vector_json", "["),
        ("family_receipts_json", "{"),
        ("family_receipts_json", "[]"),
    ):
        with pytest.raises(ValueError, match="invalid portable publication binding"):
            publication_receipt_from_mapping(portable_json_mutation(field, value))

    with pytest.raises(ValueError, match="invalid portable publication binding"):
        publication_receipt_from_mapping(
            portable_json_mutation("portable_singleton_fencing_epoch", True)
        )


def test_publication_receipt_validation_rejects_wrong_component_instances() -> None:
    """Dataclass validation does not accept untyped receipt components."""
    with pytest.raises(ValueError, match="invalid publication receipt"):
        RunPublicationReceipt(cast(RunPublicationAttempt, object()), _generations()).validate()
    with pytest.raises(ValueError, match="invalid publication receipt"):
        RunPublicationReceipt(_attempt(), cast(RunPublicationGenerations, object())).validate()
    with pytest.raises(ValueError, match="invalid publication receipt"):
        RunPublicationReceipt(
            _attempt(), _generations(), cast(PortablePublicationBinding, object())
        ).validate()

def _readback_call(reader: Callable[..., object]) -> object:
    if reader is read_run_publication:
        return reader(
            psql_args=("-d", "readback"),
            job_id="job-readback-1",
            attempt=1,
        )
    return reader(psql_args=("-d", "readback"))


@pytest.mark.parametrize(
    "reader",
    (read_run_publication, read_latest_receipt_bearing_publication),
)
@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"run_id": 1, **all_null_receipt_mapping()},
        {"run_id": 0, **legacy_receipt_mapping()},
        {"run_id": 1, **portable_json_mutation("snapshot_vector_json", "[")},
    ),
)
def test_publication_readback_rejects_non_object_missing_receipt_bad_run_and_json(
    reader, payload: object
) -> None:
    """Exact and latest readers expose one bounded schema error for malformed rows."""
    with patch(
        "common_lore_index.storage.publication_readback.run_psql",
        return_value=mapping_process(payload),
    ):
        with pytest.raises(StorageSchemaError, match="malformed publication receipt"):
            _readback_call(reader)


def test_publication_readback_accepts_a_complete_legacy_row_without_portable_columns() -> None:
    """A complete legacy receipt remains readable when portable fields are NULL."""
    payload = {"run_id": 17, **legacy_receipt_mapping()}
    with patch(
        "common_lore_index.storage.publication_readback.run_psql",
        return_value=mapping_process(payload),
    ):
        record = read_run_publication(
            ("-d", "readback"), job_id="job-readback-1", attempt=1
        )
    assert record is not None
    assert record.run_id == 17
    assert record.receipt.portable is None
