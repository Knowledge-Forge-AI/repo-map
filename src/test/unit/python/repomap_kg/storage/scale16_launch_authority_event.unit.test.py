from __future__ import annotations

import pytest

from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staged_ingestion import new_direct_authority
from repomap_kg.storage.staging_launch_authority import DirectLaunchAuthorityEvent


def _attempt() -> RunPublicationAttempt:
    authority = new_direct_authority(
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )
    return authority.receipt().attempt


def test_direct_launch_event_uses_exact_receipt_attempt() -> None:
    attempt = _attempt()

    event = DirectLaunchAuthorityEvent.from_attempt(attempt, 17)

    assert event.publication_attempt is attempt
    assert event.to_payload() == {
        "schema_version": 1,
        "authority_kind": "direct_publication_attempt",
        "event_category": "bound",
        "execution_mode": "direct",
        "publication_identity": attempt.job_id,
        "publication_attempt": attempt.attempt,
        "monotonic_offset_ns": 17,
    }
    assert DirectLaunchAuthorityEvent.from_payload(event.to_payload()) == event


@pytest.mark.parametrize(
    "change",
    (
        {"schema_version": 2},
        {"authority_kind": "coordinator_publication_attempt"},
        {"event_category": "changed"},
        {"execution_mode": "coordinator"},
        {"publication_identity": "bad identity"},
        {"publication_attempt": 0},
        {"monotonic_offset_ns": -1},
        {"unknown": "value"},
    ),
)
def test_direct_launch_event_rejects_nonclosed_payload(change) -> None:
    payload = DirectLaunchAuthorityEvent.from_attempt(_attempt(), 0).to_payload()
    payload.update(change)

    with pytest.raises(ValueError, match="direct launch authority event"):
        DirectLaunchAuthorityEvent.from_payload(payload)


def test_direct_launch_event_error_does_not_expose_identity() -> None:
    private_identity = _attempt().job_id
    payload = DirectLaunchAuthorityEvent.from_attempt(_attempt(), 0).to_payload()
    payload["publication_identity"] = private_identity + "!"

    with pytest.raises(ValueError) as caught:
        DirectLaunchAuthorityEvent.from_payload(payload)

    assert private_identity not in str(caught.value)
