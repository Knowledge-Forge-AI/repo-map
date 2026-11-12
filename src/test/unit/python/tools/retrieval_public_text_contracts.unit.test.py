"""Closed public-text contracts refuse inexact, unknown, private and inconsistent values."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from types import MappingProxyType
from typing import Any

# Assemble inert negative-test strings; these contain no usable credential or key.
import pytest

from common_lore_index.retrieval.projection_policy import ExclusionReason
from retrieval_public_text_contracts import (
    DESCRIPTOR_CONSTRUCTION_REFUSED, DESCRIPTOR_FIELDS, EXCERPT_CREDENTIAL_SHAPE_EXCLUDED, EXCERPT_PRIVACY_REFUSED,
    PAIR_REASONS, PREPARATION_REFUSALS, PRIVATE_MARKER_SCOPE_INVALID, SPAN_INVALID, PairExclusion, PrivateMarkerScope,
    PublicTextDescriptor, PublicTextQueryDecision, PublicTextRefusal, is_pair_reason, maintained_reason,
    require_scope, validate_accepted_reference,
)

CANARY = "CANARY-PRIVATE-HOME-7731"


def _reference(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "graph_id": "graph-a", "repository_id": "repo1:graph-a", "backend": "sqlite", "run_id": 3,
        "publication_bundle_id": "bundle1:" + "b" * 64, "job_id": "job-1", "attempt": 1,
        "accepted_generation": 1, "snapshot_manifest_id": "snapmanifest1:" + "c" * 64,
        "extraction_receipt_id": "receipt1:" + "d" * 64, "trusted_caller": True,
    }
    value.update(changes)
    return value


def _descriptor(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": "cloe-public-text-descriptor-v1", "representation_version": "canonical-node-public-text-v2",
        "model_text_version": "cloe-public-text-model-text-v1", "admission_policy_version": "cloe-public-text-admission-v1",
        "graph_id": "graph-a", "repository_identity": "repo1:graph-a", "backend": "sqlite", "run_id": 3, "generation": 1,
        "receipt_identity": "sha256:" + "1" * 64, "policy_digest": "sha256:" + "2" * 64,
        "privacy_scope_id": "ptscope1:" + "e" * 64, "accepted_reference": _reference(),
        "publication_bundle_id": "bundle1:" + "b" * 64, "snapshot_manifest_id": "snapmanifest1:" + "c" * 64,
        "extraction_receipt_id": "receipt1:" + "d" * 64, "candidate_id": "cand1:" + "f" * 64,
        "source_binding_id": "bind1:" + "1" * 64, "binding_revision": 1, "snapshot_id": "snap1:" + "a" * 64,
        "canonical_key": "py:mod.f", "kind": "function", "display_name": "f", "v1_input_digest": "sha256:" + "3" * 64,
        "evidence_key": "ev1:f", "source_relative_path": "src/m.py", "start_line": 2, "end_line": 2,
        "artifact_content_digest": "sha256:" + "4" * 64, "artifact_size_bytes": 7, "artifact_privacy": "raw_source",
        "span_start_byte": 2, "span_end_byte": 5, "excerpt_end_byte": 5, "excerpt_bytes": 3,
        "excerpt_digest": "sha256:" + "5" * 64, "span_cut": False, "utf8_tail_dropped_bytes": 0, "lf_count": 1,
        "crlf_count": 0, "final_line_without_lf": False, "model_text_bytes": 120, "input_digest": "sha256:" + "6" * 64,
    }
    value.update(changes)
    return value


def test_valid_descriptor_has_sorted_compact_identity_and_exact_field_set() -> None:
    descriptor = PublicTextDescriptor.from_mapping(_descriptor())
    assert set(descriptor.to_dict()) == set(DESCRIPTOR_FIELDS)
    assert len(descriptor.to_dict()["accepted_reference"]) == 11
    payload = json.dumps(_descriptor(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert descriptor.identity == "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert isinstance(descriptor.values, MappingProxyType)
    assert isinstance(descriptor.values["accepted_reference"], MappingProxyType)


@pytest.mark.parametrize("change", [
    {"unknown_field": 1}, {"start_line": True}, {"run_id": 3.0}, {"span_cut": 1}, {"final_line_without_lf": None},
    {"excerpt_digest": "sha256:XYZ"}, {"backend": "mysql"}, {"privacy_scope_id": "ptscope1:short"},
    {"schema": "cloe-public-text-descriptor-v0"}, {"kind": "func\x07"}, {"display_name": "://".join(('https', 'ab:cd@example.invalid'))},
    {"graph_id": "graph-b"}, {"generation": 2}, {"span_end_byte": 8}, {"excerpt_bytes": 2},
    {"span_cut": True}, {"utf8_tail_dropped_bytes": 1}, {"utf8_tail_dropped_bytes": 4}, {"crlf_count": 2},
    {"start_line": 3}, {"accepted_reference": _reference(trusted_caller=1)},
    {"accepted_reference": _reference(snapshot_manifest_id=None)},
])
def test_descriptor_refuses_unknown_inexact_private_and_inconsistent_values(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PublicTextDescriptor.from_mapping(_descriptor(**change))


def test_descriptor_refuses_each_missing_field() -> None:
    for name in DESCRIPTOR_FIELDS:
        raw = _descriptor()
        del raw[name]
        with pytest.raises(ValueError):
            PublicTextDescriptor.from_mapping(raw)


def test_accepted_reference_requires_all_eleven_fields_including_optional_ids() -> None:
    assert validate_accepted_reference(_reference()) == _reference()
    for name in ("snapshot_manifest_id", "extraction_receipt_id"):
        raw = _reference()
        del raw[name]
        with pytest.raises(ValueError):
            validate_accepted_reference(raw)
    with pytest.raises(ValueError):
        validate_accepted_reference(_reference(run_id="3"))
    with pytest.raises(ValueError):
        validate_accepted_reference({**_reference(), "extra": "x"})


def test_private_marker_scope_exposes_only_a_random_scope_id() -> None:
    first = PrivateMarkerScope.create((CANARY, "/private/root/alpha"))
    second = PrivateMarkerScope.create((CANARY, "/private/root/alpha"))
    assert first.scope_id.startswith("ptscope1:") and len(first.scope_id) == 73
    assert first.scope_id != second.scope_id
    assert CANARY not in repr(first) and "private/root" not in repr(first)
    assert first.markers == tuple(sorted((CANARY, "/private/root/alpha")))
    assert require_scope(first) is first
    unique = json.dumps(sorted({CANARY, "/private/root/alpha"}), ensure_ascii=False).encode("utf-8")
    private_digest = "sha256:" + hashlib.sha256(unique).hexdigest()
    assert private_digest not in repr(first) and private_digest not in first.scope_id
    assert first.private_digest_matches(private_digest)


@pytest.mark.parametrize("markers", [
    [CANARY], (), tuple(f"m{i}" for i in range(129)), ("",), ("   ",), ("a\x00b",), ("a\nb",), ("\ud800",),
    ("x" * 4097,), ("é" * 2049,), (1,), None,
])
def test_private_marker_scope_refuses_invalid_scope_without_fallback(markers: Any) -> None:
    with pytest.raises(PublicTextRefusal) as error:
        PrivateMarkerScope.create(markers)
    assert error.value.code == PRIVATE_MARKER_SCOPE_INVALID
    assert str(error.value) == PRIVATE_MARKER_SCOPE_INVALID


def test_scope_cannot_be_forged_or_replaced_with_a_public_id() -> None:
    scope = PrivateMarkerScope.create((CANARY,))
    with pytest.raises(PublicTextRefusal):
        PrivateMarkerScope(scope.scope_id, (CANARY,), "sha256:" + "0" * 64)
    with pytest.raises(PublicTextRefusal):
        require_scope(scope.scope_id)
    tampered = replace(scope, _markers=("other",))
    with pytest.raises(PublicTextRefusal):
        require_scope(tampered)


def test_reasons_are_closed_including_maintained_suffixes() -> None:
    assert maintained_reason("public_text_projection_excluded", ExclusionReason.INVALID_UTF8) == (
        "public_text_projection_excluded:invalid_utf8"
    )
    assert is_pair_reason(SPAN_INVALID)
    assert not is_pair_reason("public_text_projection_excluded:made_up")
    assert not is_pair_reason("public_text_other:invalid_utf8")
    with pytest.raises(ValueError):
        maintained_reason("public_text_unknown", "invalid_utf8")
    with pytest.raises(ValueError):
        PairExclusion("k", "bind1:x", "free text reason")
    with pytest.raises(ValueError):
        PublicTextRefusal("not-a-code")
    assert PairExclusion("k", "b", SPAN_INVALID).to_dict() == {
        "canonical_key": "k", "source_binding_id": "b", "reason": SPAN_INVALID,
    }


def test_section_14_codes_are_closed_and_distinct() -> None:
    assert is_pair_reason(EXCERPT_CREDENTIAL_SHAPE_EXCLUDED) and EXCERPT_CREDENTIAL_SHAPE_EXCLUDED in PAIR_REASONS
    assert EXCERPT_CREDENTIAL_SHAPE_EXCLUDED != EXCERPT_PRIVACY_REFUSED and is_pair_reason(EXCERPT_PRIVACY_REFUSED)
    assert DESCRIPTOR_CONSTRUCTION_REFUSED in PREPARATION_REFUSALS and not is_pair_reason(DESCRIPTOR_CONSTRUCTION_REFUSED)
    assert PublicTextRefusal(DESCRIPTOR_CONSTRUCTION_REFUSED).code == DESCRIPTOR_CONSTRUCTION_REFUSED
    assert PairExclusion("k", "b", EXCERPT_CREDENTIAL_SHAPE_EXCLUDED).reason == EXCERPT_CREDENTIAL_SHAPE_EXCLUDED


@pytest.mark.parametrize("change,valid", [
    ({"evidence_key": "ev1:token:sync"}, True), ({"canonical_key": "python.function:pkg.auth:credentials:x"}, True),
    ({"display_name": " ".join(('-----BEGIN', 'PRIVATE', 'KEY-----'))}, False),
    ({"evidence_key": "://".join(('postgres', 'u:PUBLIC_TEST_VALUE@db.invalid'))}, False),
])
def test_descriptor_strings_follow_the_structured_metadata_predicate(change: dict[str, Any], valid: bool) -> None:
    if valid:
        assert PublicTextDescriptor.from_mapping(_descriptor(**change))[next(iter(change))] == next(iter(change.values()))
    else:
        with pytest.raises(ValueError):
            PublicTextDescriptor.from_mapping(_descriptor(**change))


class _V1:
    def to_dict(self) -> dict[str, str]:
        return {"state": "admitted"}


def test_query_decision_state_invariants() -> None:
    admitted = PublicTextQueryDecision(_V1(), "admitted", None, None, None)
    assert admitted.to_dict()["v1"] == {"state": "admitted"}
    for args in (("refused", None, None, None), ("admitted", "x", None, None), ("unavailable", "x", "code", None),
                 ("pending", None, None, None)):
        with pytest.raises(ValueError):
            PublicTextQueryDecision(_V1(), *args)
