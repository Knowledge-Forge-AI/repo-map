"""Direct contracts for accepted-publication and snapshot-vector identity."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    attach_vector_status,
    normalize_accepted_publication,
    parse_snapshot_vector,
    validate_accepted_pin_mapping,
)


BINDING = "bind1:context-identity"
SNAPSHOT = "snap1:context-identity"


def _accepted(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "generation": 1,
        "accepted_run_id": 1,
        "run_id": 1,
        "publication_bundle_id": "bundle1:context-identity",
        "snapshot_manifest_id": "manifest1:context-identity",
        "extraction_receipt_id": "receipt1:context-identity",
        "job_id": "job-context-identity",
        "publication_job_id": "job-context-identity",
        "attempt": 1,
        "publication_attempt": 1,
        "snapshot_vector": [[BINDING, 1, SNAPSHOT]],
    }
    value.update(overrides)
    return value


def test_parse_snapshot_vector_accepts_equal_compatibility_aliases() -> None:
    raw = [{
        "binding_id": BINDING,
        "source_binding_id": BINDING,
        "revision": 3,
        "binding_revision": 3,
        "snapshot_id": SNAPSHOT,
    }]
    assert parse_snapshot_vector(raw) == ((BINDING, 3, SNAPSHOT),)


@pytest.mark.parametrize(
    "raw",
    [
        [{"binding_id": BINDING, "source_binding_id": "bind1:other", "revision": 1, "snapshot_id": SNAPSHOT}],
        [{"binding_id": BINDING, "revision": 1, "binding_revision": 2, "snapshot_id": SNAPSHOT}],
        [{"binding_id": BINDING, "revision": 1, "snapshot_id": SNAPSHOT, "extra": True}],
        [[BINDING, True, SNAPSHOT]],
        [[BINDING, 0, SNAPSHOT]],
        [[BINDING, 1, ""]],
    ],
)
def test_parse_snapshot_vector_refuses_conflicting_or_noncanonical_entries(raw: Any) -> None:
    with pytest.raises(ContextIdentityError):
        parse_snapshot_vector(raw)


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [[BINDING, 1, SNAPSHOT], [BINDING, 1, SNAPSHOT]],
        {"binding_id": BINDING},
        "not-a-vector",
    ],
)
def test_parse_snapshot_vector_refuses_empty_duplicate_and_wrong_shapes(raw: Any) -> None:
    with pytest.raises(ContextIdentityError):
        parse_snapshot_vector(raw)


def test_normalize_accepted_publication_canonicalizes_json_and_optional_provenance() -> None:
    accepted = _accepted(
        snapshot_vector_json=json.dumps([[BINDING, 1, SNAPSHOT]], separators=(",", ":")),
    )
    accepted.pop("snapshot_vector")
    normalized = normalize_accepted_publication(accepted)
    assert normalized["accepted_run_id"] == normalized["run_id"] == 1
    assert normalized["job_id"] == normalized["publication_job_id"] == "job-context-identity"
    assert normalized["attempt"] == normalized["publication_attempt"] == 1
    assert normalized["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)

    unpinned = _accepted()
    for key in ("job_id", "publication_job_id", "attempt", "publication_attempt"):
        unpinned.pop(key)
    optional = normalize_accepted_publication(unpinned)
    assert optional["job_id"] is None and optional["attempt"] is None
    assert optional["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)


def test_normalize_accepted_publication_requires_strong_pin_and_preserves_no_vector_mode() -> None:
    unpinned = _accepted()
    for key in ("job_id", "publication_job_id", "attempt", "publication_attempt"):
        unpinned.pop(key)
    with pytest.raises(ContextIdentityError, match="job/attempt provenance"):
        normalize_accepted_publication(unpinned, require_pin=True)

    no_vector = _accepted()
    no_vector.pop("snapshot_vector")
    no_vector.pop("job_id")
    no_vector.pop("publication_job_id")
    no_vector.pop("attempt")
    no_vector.pop("publication_attempt")
    normalized = validate_accepted_pin_mapping(_accepted())
    assert normalized["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)
    assert normalize_accepted_publication(no_vector, require_vector=False)["snapshot_vector"] == ()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("generation", True), ("accepted_run_id", 1.0), ("run_id", 0), ("publication_bundle_id", "")],
)
def test_normalize_accepted_publication_refuses_invalid_required_fields(
    field: str, bad_value: Any,
) -> None:
    accepted = _accepted(**{field: bad_value})
    with pytest.raises(ContextIdentityError):
        normalize_accepted_publication(accepted)


def test_normalize_accepted_publication_refuses_non_mapping_input() -> None:
    with pytest.raises(ContextIdentityError, match="must be a mapping"):
        normalize_accepted_publication(cast(Any, []))


def test_normalize_accepted_publication_refuses_alias_and_vector_disagreement() -> None:
    aliases = _accepted(run_id=2)
    with pytest.raises(ContextIdentityError, match="disagrees with run_id"):
        normalize_accepted_publication(aliases)

    vectors = _accepted(snapshot_vector_json=[[BINDING, 2, SNAPSHOT]])
    with pytest.raises(ContextIdentityError, match="snapshot_vector_json"):
        normalize_accepted_publication(vectors)


def test_attach_vector_status_backfills_matching_revision_and_accepts_mapping_aliases() -> None:
    location: dict[str, Any] = {
        "source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT},
    }
    result = attach_vector_status(
        location,
        [{
            "source_binding_id": BINDING,
            "binding_revision": 4,
            "snapshot_id": SNAPSHOT,
        }],
    )
    assert result["source_identity_status"] == "verified_vector"
    assert result["source"]["binding_revision"] == 4


@pytest.mark.parametrize(
    "location",
    [
        {"source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT, "binding_revision": 2}},
        {"source": {"binding_id": BINDING, "snapshot_id": "snap1:other", "binding_revision": 1}},
        {"source": {"binding_id": "bind1:other", "snapshot_id": SNAPSHOT, "binding_revision": 1}},
        {"source": [BINDING, 1, SNAPSHOT]},
    ],
)
def test_attach_vector_status_refuses_conflicting_source_identity(location: dict[str, Any]) -> None:
    result = attach_vector_status(location, [(BINDING, 1, SNAPSHOT)])
    assert result["source_identity_status"] == "unbound_or_conflicting_vector"


def test_attach_vector_status_preserves_existing_status_and_malformed_vectors() -> None:
    existing: dict[str, Any] = {
        "source_identity_status": "withheld",
        "source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT},
    }
    assert attach_vector_status(existing, [(BINDING, 1, SNAPSHOT)]) is existing
    assert existing["source_identity_status"] == "withheld"

    malformed = attach_vector_status(
        {"source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT}},
        [[BINDING, True, SNAPSHOT]],
    )
    assert malformed["source_identity_status"] == "unbound_or_conflicting_vector"
