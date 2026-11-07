"""Validation-boundary tests for publication correspondence and build policy binding."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import common_lore_index.retrieval.publication_binding as binding_module
from common_lore_index.artifacts._store_common import ArtifactIntegrityError
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceErrorCode,
    CorrespondenceRefusal,
    ProjectionInputs,
)
from repomap_test_support.w5_publication_validation_fixtures import (
    build_validation_projection,
    publication_tree,
)


def _replace_reference_field(
    reference: AcceptedPublicationReference, field: str, value: object
) -> AcceptedPublicationReference:
    """Keep deliberately malformed raw values at the dataclass boundary."""
    return replace(reference, **cast(Any, {field: value}))


def _replace_inputs_field(
    inputs: ProjectionInputs, field: str, value: object
) -> ProjectionInputs:
    """Keep deliberately malformed runtime values at the dataclass boundary."""
    return replace(inputs, **cast(Any, {field: value}))


def test_accepted_reference_validate_rejects_raw_field_boundaries(tmp_path: Path) -> None:
    """Direct accepted-marker validation rejects every non-structural field boundary."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    reference = inputs.accepted_reference
    with pytest.raises(CorrespondenceRefusal) as untrusted:
        replace(reference, trusted_caller=False).validate()
    assert untrusted.value.code == CorrespondenceErrorCode.UNTRUSTED_CALLER_REFERENCE

    invalid_values = (
        ("graph_id", ""),
        ("graph_id", 1),
        ("repository_id", ""),
        ("publication_bundle_id", ""),
        ("job_id", ""),
        ("backend", "memory"),
        ("run_id", True),
        ("run_id", ""),
        ("run_id", 1.5),
        ("attempt", True),
        ("attempt", 0),
        ("attempt", "1"),
        ("accepted_generation", False),
        ("accepted_generation", 0),
        ("accepted_generation", "1"),
        ("snapshot_manifest_id", ""),
        ("extraction_receipt_id", 1),
    )
    for field, value in invalid_values:
        with pytest.raises(ValueError, match=field):
            _replace_reference_field(reference, field, value).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_id", 1),
        ("backend", 1),
        ("publication_bundle_id", 1),
        ("job_id", 1),
        ("snapshot_manifest_id", 1),
        ("extraction_receipt_id", 1),
    ),
)
def test_accepted_reference_from_mapping_rejects_wrong_raw_types(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """The closed mapping parser rejects wrong primitive types before construction."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    raw = inputs.accepted_reference.to_dict()
    raw[field] = value
    with pytest.raises(ValueError):
        inputs.accepted_reference.from_mapping(raw)


def test_accepted_reference_from_mapping_rejects_extra_and_missing_values(
    tmp_path: Path,
) -> None:
    """Unexpected keys and omitted required fields remain explicit parse failures."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    raw = inputs.accepted_reference.to_dict()
    with pytest.raises(ValueError, match="unexpected fields"):
        inputs.accepted_reference.from_mapping({**raw, "private": "no"})
    for field in ("graph_id", "repository_id", "backend", "publication_bundle_id", "job_id"):
        missing = dict(raw)
        missing.pop(field)
        with pytest.raises(ValueError, match=field):
            inputs.accepted_reference.from_mapping(missing)


def test_correspondence_store_references_have_bounded_failure_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing references, invalid budgets, verify failures, and absent spool are sanitized."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    for field in ("manifest_reference", "bundle_reference", "receipt_reference"):
        with pytest.raises(CorrespondenceRefusal) as failure:
            binding_module.check_correspondence(_replace_inputs_field(inputs, field, None))
        assert failure.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED

    # Keep bool/None malformed budget values at the runtime boundary for this test.
    for budget in (False, 0, -1, None):
        with pytest.raises(CorrespondenceRefusal) as failure:
            binding_module.check_correspondence(
                replace(inputs, max_bundle_bytes=cast(Any, budget))
            )
        assert failure.value.code == CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED

    def verify_false(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(inputs.store, "verify", verify_false)
    with pytest.raises(CorrespondenceRefusal) as false_failure:
        binding_module.check_correspondence(inputs)
    assert false_failure.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED

    def verify_error(*_args: object, **_kwargs: object) -> bool:
        raise ArtifactIntegrityError("controlled verification refusal")

    monkeypatch.setattr(inputs.store, "verify", verify_error)
    with pytest.raises(CorrespondenceRefusal) as error_failure:
        binding_module.check_correspondence(inputs)
    assert error_failure.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED

    monkeypatch.undo()
    with pytest.raises(CorrespondenceRefusal) as spool_failure:
        binding_module.check_correspondence(replace(inputs, spool_dir=None))
    assert spool_failure.value.code == CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED


def test_stored_manifest_and_extraction_receipt_are_rechecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retained manifest bytes and extraction receipt identity cannot be caller-rewritten."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    assert inputs.manifest_reference is not None
    original_read = inputs.store.read
    alternate = PortableSnapshotManifest.create_from(
        inputs.manifest,
        quality_rule_identity="quality1:alternate",
    )

    def read_override(
        reference: ArtifactReference,
        max_bytes: int | None = None,
    ) -> bytes:
        if (
            inputs.manifest_reference is not None
            and getattr(reference, "content_digest", None)
            == inputs.manifest_reference.content_digest
        ):
            return alternate.canonical_bytes()
        return original_read(reference, max_bytes)

    monkeypatch.setattr(inputs.store, "read", read_override)
    with pytest.raises(CorrespondenceRefusal) as manifest_failure:
        binding_module.check_correspondence(inputs)
    assert manifest_failure.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED

    monkeypatch.undo()
    assert inputs.extraction_receipt is not None
    bad_receipt = replace(
        inputs.extraction_receipt,
        snapshot_manifest_id="snapmanifest1:" + "8" * 64,
    )
    with pytest.raises(CorrespondenceRefusal) as receipt_failure:
        binding_module.check_correspondence(
            replace(inputs, extraction_receipt=bad_receipt)
        )
    assert receipt_failure.value.code == CorrespondenceErrorCode.RECEIPT_ID_MISMATCH


def test_canonical_reparse_and_validator_identity_are_not_trusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical IDs are recomputed and validator output is checked before projection."""
    inputs, _policy = build_validation_projection(spool_dir=tmp_path / "spool")
    portable = inputs.receipt.portable
    assert portable is not None
    extraction_receipt_id = portable.extraction_receipt_id

    manifest_id = "snapmanifest1:" + "8" * 64
    bad_manifest = replace(inputs.manifest, manifest_id=manifest_id)
    bad_manifest_receipt = replace(
        inputs.extraction_receipt,
        snapshot_manifest_id=manifest_id,
    ) if inputs.extraction_receipt is not None else None
    bad_manifest_inputs = replace(
        inputs,
        accepted_reference=replace(
            inputs.accepted_reference,
            snapshot_manifest_id=manifest_id,
        ),
        receipt=replace(
            inputs.receipt,
            portable=replace(portable, snapshot_manifest_id=manifest_id),
        ),
        manifest=bad_manifest,
        bundle=replace(inputs.bundle, snapshot_manifest_id=manifest_id),
        extraction_receipt=bad_manifest_receipt,
    )
    with pytest.raises(CorrespondenceRefusal) as manifest_failure:
        binding_module.check_correspondence(bad_manifest_inputs)
    assert manifest_failure.value.code == CorrespondenceErrorCode.CANONICAL_IDENTITY_MISMATCH

    bundle_id = "bundle1:" + "8" * 64
    bad_bundle = replace(inputs.bundle, bundle_id=bundle_id)
    bad_bundle_receipt = replace(
        inputs.extraction_receipt,
        bundle_id=bundle_id,
    ) if inputs.extraction_receipt is not None else None
    bad_bundle_inputs = replace(
        inputs,
        accepted_reference=replace(
            inputs.accepted_reference,
            publication_bundle_id=bundle_id,
        ),
        receipt=replace(
            inputs.receipt,
            portable=replace(portable, publication_bundle_id=bundle_id),
        ),
        bundle=bad_bundle,
        extraction_receipt=bad_bundle_receipt,
    )
    with pytest.raises(CorrespondenceRefusal) as bundle_failure:
        binding_module.check_correspondence(bad_bundle_inputs)
    assert bundle_failure.value.code == CorrespondenceErrorCode.CANONICAL_IDENTITY_MISMATCH

    class WrongValidator:
        def validate_bundle_stream(self, **_kwargs: object) -> object:
            return SimpleNamespace(
                bundle_id="bundle1:" + "9" * 64,
                receipt_id=extraction_receipt_id,
                snapshot_manifest_id=inputs.manifest.manifest_id,
                close=lambda: None,
            )

    monkeypatch.setattr(binding_module, "PublisherBundleValidator", WrongValidator)
    with pytest.raises(CorrespondenceRefusal) as validator_failure:
        binding_module.check_correspondence(inputs)
    assert validator_failure.value.code == CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED


def test_projection_build_refuses_policy_graph_mismatch_and_cleans_spool(
    tmp_path: Path,
) -> None:
    """The directly reachable graph-policy mismatch is refused after correspondence and cleaned."""
    inputs, policy = build_validation_projection(spool_dir=tmp_path / "spool")
    assert inputs.spool_dir is not None
    before = publication_tree(inputs.spool_dir)
    with pytest.raises(ValueError, match="policy.graph_id"):
        build_captured_text_projection(
            inputs,
            replace(policy, graph_id="other-graph"),
        )
    assert publication_tree(inputs.spool_dir) == before
