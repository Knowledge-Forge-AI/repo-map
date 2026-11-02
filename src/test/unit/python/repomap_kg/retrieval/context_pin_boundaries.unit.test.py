"""W4 public-boundary regressions for publication pins and snapshot vectors.

These tests feed normalized, public-shaped identity mappings to the maintained
selection and revalidation APIs.  Raw SQLite/PostgreSQL normalization tests
remain an integration seam owned by the parent correction phase.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from common_lore_index.retrieval.context_assembly import select_context_sources
from common_lore_index.retrieval.context_contracts import (
    ContextRequestError,
    ExpectedPublicationPin,
)
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.retrieval.source_selection import (
    SourceBindingSelection,
    SourceSelectionRecord,
    revalidate_selection_record,
)


GRAPH_ID = "pin-boundary-graph"
REPOSITORY_ID = "repo1:pin-boundary-graph"
BINDING_CORE = "bind1:core"
BINDING_UNUSED = "bind1:unused"
SNAP_CORE = "snap1:core"

PIN = ExpectedPublicationPin(
    accepted_run_id=1,
    publication_bundle_id="bundle1:pin-boundary",
    snapshot_manifest_id="manifest1:pin-boundary",
    generation=1,
    job_id="job-pin-boundary",
    attempt=1,
    extraction_receipt_id="receipt1:pin-boundary",
)

CONFIGURED_BINDINGS: dict[str, dict[str, Any]] = {
    BINDING_CORE: {
        "revision": 1,
        "selection_policy_id": "select1:default",
        "source_definition_id": "src1:core",
    },
    BINDING_UNUSED: {
        "revision": 1,
        "selection_policy_id": "select1:default",
        "source_definition_id": "src1:unused",
    },
}

PIN_NUMERIC_ALIASES: dict[str, tuple[str, ...]] = {
    "generation": ("generation",),
    "run": ("accepted_run_id", "run_id"),
    "attempt": ("attempt", "publication_attempt"),
}

PIN_STRING_ALIASES: dict[str, tuple[str, ...]] = {
    "bundle": ("publication_bundle_id",),
    "manifest": ("snapshot_manifest_id",),
    "job": ("job_id", "publication_job_id"),
    "receipt": ("extraction_receipt_id",),
}

MISSING_PROVENANCE_ALIASES: tuple[tuple[str, ...], ...] = (
    ("generation",),
    ("accepted_run_id", "run_id"),
    ("publication_bundle_id",),
    ("snapshot_manifest_id",),
    ("job_id", "publication_job_id"),
    ("attempt", "publication_attempt"),
    ("extraction_receipt_id",),
)


class _ControlledContextPort(SqliteContextReadAdapter):
    """Small in-memory port so boundary tests do not open a database."""

    def __init__(self, accepted_publication: Mapping[str, Any]) -> None:
        super().__init__(graph_id=GRAPH_ID, repository_id=REPOSITORY_ID,
                         configured_bindings=CONFIGURED_BINDINGS)
        self._accepted_publication = dict(accepted_publication)

    def read_initial_identity(self, _ledger: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "graph_id": self.graph_id,
            "repository_id": self.repository_id,
            "accepted_publication": self._accepted_publication,
        }


def _valid_vector() -> list[list[Any]]:
    return [[BINDING_CORE, 1, SNAP_CORE]]


def _valid_accepted(*, snapshot_vector: Any | None = None) -> dict[str, Any]:
    return {
        "generation": 1,
        "accepted_run_id": 1,
        "run_id": 1,
        "publication_bundle_id": PIN.publication_bundle_id,
        "snapshot_manifest_id": PIN.snapshot_manifest_id,
        "extraction_receipt_id": PIN.extraction_receipt_id,
        "job_id": PIN.job_id,
        "publication_job_id": PIN.job_id,
        "attempt": 1,
        "publication_attempt": 1,
        "snapshot_vector": _valid_vector() if snapshot_vector is None else snapshot_vector,
    }


def _selection_record() -> SourceSelectionRecord:
    return SourceSelectionRecord.build(
        graph_id=GRAPH_ID,
        repository_id=REPOSITORY_ID,
        backend="sqlite",
        bindings=(
            SourceBindingSelection(
                binding_id=BINDING_CORE,
                revision=1,
                snapshot_id=SNAP_CORE,
                selection_policy_id="select1:default",
                source_definition_id="src1:core",
            ),
        ),
        expected_publication=PIN,
    )


def _revalidate(accepted: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return revalidate_selection_record(
        _selection_record(),
        live_graph_id=GRAPH_ID,
        live_repository_id=REPOSITORY_ID,
        live_backend="sqlite",
        live_bindings_by_id=CONFIGURED_BINDINGS,
        live_accepted=accepted,
    )


def _set_pin_aliases(accepted: dict[str, Any], field: str, value: Any) -> None:
    for alias in PIN_NUMERIC_ALIASES[field]:
        accepted[alias] = value


def test_expected_publication_pin_round_trips_and_validates() -> None:
    assert PIN.validate() is PIN
    assert PIN.matches_accepted(_valid_accepted())
    assert PIN.to_dict()["accepted_run_id"] == 1


@pytest.mark.parametrize("field", ("accepted_run_id", "generation", "attempt"))
@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
def test_expected_publication_pin_rejects_noncanonical_numeric_types(
    field: str, bad_value: Any
) -> None:
    values = PIN.to_dict()
    values[field] = bad_value
    with pytest.raises(ContextRequestError) as exc:
        ExpectedPublicationPin(**values).validate()
    assert exc.value.refusal_reason == "invalid_selection_record"


@pytest.mark.parametrize("field", tuple(PIN_NUMERIC_ALIASES))
@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
def test_pin_matching_rejects_noncanonical_live_numeric_types(
    field: str, bad_value: Any
) -> None:
    accepted = _valid_accepted()
    _set_pin_aliases(accepted, field, bad_value)
    assert PIN.matches_accepted(accepted) is False


def test_select_context_sources_accepts_valid_full_pin_and_vector() -> None:
    record = select_context_sources(
        port=_ControlledContextPort(_valid_accepted()),
        bindings=(BINDING_CORE,),
        path_prefixes={},
        pin_publication=True,
    )
    assert record.expected_publication == PIN
    assert record.bindings[0].binding_id == BINDING_CORE
    assert record.bindings[0].revision == 1
    assert record.bindings[0].snapshot_id == SNAP_CORE


@pytest.mark.parametrize("field", tuple(PIN_NUMERIC_ALIASES))
@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
def test_select_context_sources_refuses_noncanonical_pin_numbers(
    field: str, bad_value: Any
) -> None:
    accepted = _valid_accepted()
    _set_pin_aliases(accepted, field, bad_value)
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=_ControlledContextPort(accepted),
            bindings=(BINDING_CORE,),
            path_prefixes={},
            pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


@pytest.mark.parametrize("field", tuple(PIN_STRING_ALIASES))
@pytest.mark.parametrize("bad_value", (True, 1, 1.0, "", None))
def test_select_context_sources_refuses_malformed_pin_strings(
    field: str, bad_value: Any
) -> None:
    accepted = _valid_accepted()
    for alias in PIN_STRING_ALIASES[field]:
        accepted[alias] = bad_value
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=_ControlledContextPort(accepted),
            bindings=(BINDING_CORE,),
            path_prefixes={},
            pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


@pytest.mark.parametrize("missing_aliases", MISSING_PROVENANCE_ALIASES)
def test_select_context_sources_refuses_missing_asserted_provenance(
    missing_aliases: tuple[str, ...],
) -> None:
    accepted = _valid_accepted()
    for key in missing_aliases:
        accepted.pop(key)
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=_ControlledContextPort(accepted),
            bindings=(BINDING_CORE,),
            path_prefixes={},
            pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


def test_revalidation_accepts_valid_pin_and_reports_real_publication_drift() -> None:
    assert _revalidate(_valid_accepted()) == (None, None)

    advanced = _valid_accepted()
    advanced["generation"] = 2
    assert _revalidate(advanced) == ("stale", "selection_publication_advanced")


@pytest.mark.parametrize("field", tuple(PIN_NUMERIC_ALIASES))
@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
def test_revalidation_refuses_noncanonical_pin_numbers_not_stale(
    field: str, bad_value: Any
) -> None:
    accepted = _valid_accepted()
    _set_pin_aliases(accepted, field, bad_value)
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize("field", tuple(PIN_STRING_ALIASES))
@pytest.mark.parametrize("bad_value", (True, 1, 1.0, "", None))
def test_revalidation_refuses_malformed_pin_strings_not_stale(
    field: str, bad_value: Any
) -> None:
    accepted = _valid_accepted()
    for alias in PIN_STRING_ALIASES[field]:
        accepted[alias] = bad_value
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize("missing_aliases", MISSING_PROVENANCE_ALIASES)
def test_revalidation_refuses_missing_asserted_provenance_not_stale(
    missing_aliases: tuple[str, ...],
) -> None:
    accepted = _valid_accepted()
    for key in missing_aliases:
        accepted.pop(key)
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize(
    ("alias", "conflicting_value"),
    (
        ("run_id", 2),
        ("publication_job_id", "job-pin-boundary-other"),
        ("publication_attempt", 2),
    ),
)
def test_pin_aliases_must_agree_in_matching_and_revalidation(
    alias: str, conflicting_value: Any
) -> None:
    accepted = _valid_accepted()
    accepted[alias] = conflicting_value
    assert PIN.matches_accepted(accepted) is False
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=_ControlledContextPort(accepted), bindings=(BINDING_CORE,),
            path_prefixes={}, pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


def test_revalidation_rejects_disagreeing_snapshot_vector_aliases() -> None:
    accepted = _valid_accepted()
    accepted["snapshot_vector_json"] = [[BINDING_CORE, 2, SNAP_CORE]]
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize("empty_vector", ([], ()))
def test_revalidation_rejects_empty_snapshot_vector(empty_vector: Any) -> None:
    accepted = _valid_accepted(snapshot_vector=empty_vector)
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
@pytest.mark.parametrize("entry_style", ("sequence", "mapping"))
def test_revalidation_refuses_noncanonical_snapshot_vector_revisions(
    bad_value: Any, entry_style: str
) -> None:
    if entry_style == "sequence":
        entry: Any = [BINDING_CORE, bad_value, SNAP_CORE]
    else:
        entry = {
            "binding_id": BINDING_CORE,
            "revision": bad_value,
            "snapshot_id": SNAP_CORE,
        }
    accepted = _valid_accepted(snapshot_vector=[entry])
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


def test_revalidation_refuses_duplicate_snapshot_vector_ids_even_when_identical() -> None:
    accepted = _valid_accepted(
        snapshot_vector=[
            [BINDING_CORE, 1, SNAP_CORE],
            [BINDING_CORE, 1, SNAP_CORE],
        ]
    )
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


def test_revalidation_refuses_malformed_extra_vector_row_for_unselected_binding() -> None:
    accepted = _valid_accepted(
        snapshot_vector=[
            [BINDING_CORE, 1, SNAP_CORE],
            [BINDING_UNUSED],
        ]
    )
    assert _revalidate(accepted) == ("unavailable", "accepted_publication_unverified")


@pytest.mark.parametrize("bad_value", (True, 1.0, 1.5, "1"))
def test_select_context_sources_refuses_noncanonical_snapshot_vector_revision(
    bad_value: Any,
) -> None:
    accepted = _valid_accepted(snapshot_vector=[[BINDING_CORE, bad_value, SNAP_CORE]])
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=_ControlledContextPort(accepted),
            bindings=(BINDING_CORE,),
            path_prefixes={},
            pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


def test_select_context_sources_refuses_duplicate_vector_ids_and_malformed_extra_rows() -> None:
    duplicate = _valid_accepted(
        snapshot_vector=[
            [BINDING_CORE, 1, SNAP_CORE],
            [BINDING_CORE, 1, SNAP_CORE],
        ]
    )
    malformed_extra = _valid_accepted(
        snapshot_vector=[
            [BINDING_CORE, 1, SNAP_CORE],
            [BINDING_UNUSED],
        ]
    )
    for accepted in (duplicate, malformed_extra):
        with pytest.raises(ContextRequestError) as exc:
            select_context_sources(
                port=_ControlledContextPort(accepted),
                bindings=(BINDING_CORE,),
                path_prefixes={},
                pin_publication=True,
            )
        assert exc.value.refusal_reason == "accepted_publication_unverified"
