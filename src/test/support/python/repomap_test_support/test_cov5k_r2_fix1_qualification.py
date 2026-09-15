"""Closed qualification schema and verifier for TEST-COV5K-R2-FIX1."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Mapping

from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry,
    REQUIRED_MANIFEST_GROUPS,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix1_qualification_records import (
    DraftManifest,
    FrozenManifest,
    IntegrityError,
    LifecycleState,
    ObservationSession,
    ObservedTuple,
    PROTOCOL_DIGEST,
    RUNTIME_IDENTITY_DIGEST,
    ResultArtifact,
    SealedRehearsal,
    THRESHOLDS,
    TOLERANCES,
    ValidatedManifest,
    _EXPECTED_FIELDS,
    _duplicate,
    build_result,
    canonical_digest,
    closed_source_manifest_digest as _closed_source_manifest_digest,
    parameter_digest,
    predecessor_accepts_p0,
    resolve_owner,
)
from repomap_test_support.test_cov5k_r2_fix1_qualification_groups import (
    _verify_group_a, _verify_group_d,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    POLICY_DIGEST,
)


def create_draft(
    registration_id: str = "TEST-COV5K-R3-preregistration-001",
) -> DraftManifest:
    """Create the one complete draft; no observations are accepted yet."""
    if not registration_id:
        raise IntegrityError("registration identity is required")
    return DraftManifest(
        registration_id=registration_id,
        entries=build_closed_catalog(),
        thresholds=THRESHOLDS,
        tolerances=TOLERANCES,
    )


def validate_draft(draft: DraftManifest) -> ValidatedManifest:
    """Validate exact closed membership and every independent identity."""
    if draft.state is not LifecycleState.DRAFT:
        raise IntegrityError("manifest is not in draft state")
    expected = build_closed_catalog()
    actual_groups = tuple(sorted({entry.semantic_group for entry in draft.entries}))
    if actual_groups != tuple(sorted(REQUIRED_MANIFEST_GROUPS)):
        raise IntegrityError("missing group manifest")
    if _duplicate(entry.authority_id for entry in draft.entries):
        raise IntegrityError("duplicate authority ID")
    if _duplicate(entry.case_id for entry in draft.entries):
        raise IntegrityError("duplicate semantic case")
    if any(
        entry.semantic_group == "K"
        and (
            "final_release" in entry.evidence_executor_id
            or "rss" in entry.evidence_executor_id
        )
        for entry in draft.entries
    ):
        raise IntegrityError("Group K mapped to unrelated executor")
    if draft.entries != expected:
        expected_by_case = {entry.case_id: entry for entry in expected}
        actual_by_case = {entry.case_id: entry for entry in draft.entries}
        if set(expected_by_case) - set(actual_by_case):
            raise IntegrityError("missing registered case")
        if set(actual_by_case) - set(expected_by_case):
            raise IntegrityError("unexpected registered case")
        raise IntegrityError("closed registered case changed")
    for entry in draft.entries:
        if entry.product_owner_id == entry.evidence_executor_id:
            raise IntegrityError("product owner and executor are conflated")
        if entry.parameter_schema != tuple(key for key, _ in entry.parameter_values):
            raise IntegrityError("case parameter schema is not enacted")
        if len(set(entry.parameter_schema)) != len(entry.parameter_schema):
            raise IntegrityError("duplicate case parameter")
    if draft.thresholds != THRESHOLDS:
        raise IntegrityError("threshold changed before freeze")
    if draft.tolerances != TOLERANCES:
        raise IntegrityError("tolerance changed before freeze")
    return ValidatedManifest(
        registration_id=draft.registration_id,
        entries=draft.entries,
        thresholds=draft.thresholds,
        tolerances=draft.tolerances,
    )


def freeze_manifest(validated: ValidatedManifest) -> FrozenManifest:
    """Freeze exact bytes before the observation lifecycle can open."""
    if validated.state is not LifecycleState.VALIDATED:
        raise IntegrityError("manifest is not in validated state")
    source_manifest_digest = _closed_source_manifest_digest(validated.entries)
    payload = {
        "registration_id": validated.registration_id,
        "entries": validated.entries,
        "thresholds": validated.thresholds,
        "tolerances": validated.tolerances,
        "source_manifest_digest": source_manifest_digest,
        "policy_digest": POLICY_DIGEST,
        "protocol_digest": PROTOCOL_DIGEST,
        "runtime_identity_digest": RUNTIME_IDENTITY_DIGEST,
    }
    return FrozenManifest(
        registration_id=validated.registration_id,
        entries=validated.entries,
        thresholds=validated.thresholds,
        tolerances=validated.tolerances,
        source_manifest_digest=source_manifest_digest,
        policy_digest=POLICY_DIGEST,
        protocol_digest=PROTOCOL_DIGEST,
        runtime_identity_digest=RUNTIME_IDENTITY_DIGEST,
        preregistration_digest=canonical_digest(payload),
    )


def verify_frozen(manifest: FrozenManifest) -> FrozenManifest:
    """Reject reconstruction or mutation of any frozen authority input."""
    validated = validate_draft(
        DraftManifest(
            manifest.registration_id,
            manifest.entries,
            manifest.thresholds,
            manifest.tolerances,
        )
    )
    if manifest != freeze_manifest(validated):
        raise IntegrityError("post-freeze manifest drift")
    return manifest


def open_observations(manifest: FrozenManifest) -> ObservationSession:
    """Open observations only against a currently verified freeze."""
    verify_frozen(manifest)
    return ObservationSession(
        manifest.registration_id,
        manifest.preregistration_digest,
    )


def _entry_map(manifest: FrozenManifest) -> dict[str, CatalogEntry]:
    return {entry.case_id: entry for entry in manifest.entries}


def _verify_group_semantics(
    entry: CatalogEntry,
    observed: Mapping[str, object],
) -> None:
    if observed["primary_result_category"] in {"expected", "removed"}:
        raise IntegrityError("expected or removed value used as observation")
    if entry.semantic_group in {"A", "PARENT_SETTLEMENT"}:
        _verify_group_a(entry, observed)
    if entry.semantic_group == "D":
        _verify_group_d(entry, observed)
    if entry.semantic_group == "G":
        if observed.get("aggregate") is True:
            raise IntegrityError("aggregate Group G result")
        if observed["execution_parameter_digest"] != parameter_digest(entry):
            raise IntegrityError("Group G enacted parameter evidence changed")
    if entry.semantic_group == "H":
        if observed["host_process_count"] != 0:
            raise IntegrityError("Group H host process count is not zero")
        if observed.get("aggregate") is True:
            raise IntegrityError("aggregate Group H process zero")
        if observed["nested_psql_intent_count"] != 0:
            raise IntegrityError("Group H nested psql intent is not zero")
        if observed["cleanup_disposition"] != "axis_resource_settled":
            raise IntegrityError("Group H cleanup evidence changed")
    if entry.semantic_group == "K":
        if any(v in entry.evidence_executor_id for v in ("final_release", "rss")):
            raise IntegrityError("Group K mapped to unrelated executor")
        if observed["shell"] is not False:
            raise IntegrityError("Group K shell must be false")
        if not isinstance(observed["argv"], tuple) or not observed["argv"]:
            raise IntegrityError("Group K fixed argv missing")
        if (
            not isinstance(observed["effective_argv"], tuple)
            or not observed["effective_argv"]
        ):
            raise IntegrityError("Group K effective argv missing")
        if not observed["disposable_resource_owned"]:
            raise IntegrityError("Group K disposable ownership missing")
        parameters = dict(entry.parameter_values)
        shape = parameters.get("rehearsal_argv_shape")
        if not isinstance(shape, tuple):
            raise IntegrityError("Group K rehearsal argv shape is not a tuple")
        rehearsal_argv = shape
        if observed["argv"] != rehearsal_argv:
            raise IntegrityError("Group K observed argv changed")
        if observed["effective_argv"] != rehearsal_argv:
            raise IntegrityError("Group K effective argv changed")
        execution_digest = observed["argv_execution_digest"]
        if (
            not isinstance(execution_digest, str)
            or len(execution_digest) != 64
            or any(v not in "0123456789abcdef" for v in execution_digest)
        ):
            raise IntegrityError("Group K execution digest changed")
        observed_executable = Path(str(observed["host_executable"])).name
        expected_executable = rehearsal_argv[0]
        if (
            expected_executable != "{python}"
            and observed_executable != expected_executable
        ):
            raise IntegrityError("Group K observed executable changed")
        if observed["timeout_seconds"] != 10:
            raise IntegrityError("Group K timeout changed")
        if observed["host_process_count"] != 1:
            raise IntegrityError("Group K host process evidence changed")
        disposition = observed["execution_disposition"]
        if disposition not in {
            "bounded_operation_completed",
            "bounded_operation_rejected",
        }:
            raise IntegrityError("Group K execution disposition changed")
        if not isinstance(observed["returncode"], int):
            raise IntegrityError("Group K bounded return code changed")
        expected_receipt_digest = canonical_digest(
            {
                "effective_argv": observed["effective_argv"],
                "returncode": observed["returncode"],
                "execution_disposition": disposition,
                "shell": observed["shell"],
                "timeout_seconds": observed["timeout_seconds"],
            }
        )
        if execution_digest != expected_receipt_digest:
            raise IntegrityError("Group K execution receipt changed")
        if (
            disposition == "bounded_operation_completed" and observed["returncode"] != 0
        ) or (
            disposition == "bounded_operation_rejected" and observed["returncode"] == 0
        ):
            raise IntegrityError("Group K bounded result changed")
        if observed["cleanup_disposition"] != "disposable_resource_settled":
            raise IntegrityError("Group K cleanup evidence changed")


def verify_result(
    manifest: FrozenManifest,
    artifact: ResultArtifact,
) -> ResultArtifact:
    """Reject relabelled, aggregate, drifted, or non-observational evidence."""
    verify_frozen(manifest)
    if artifact.schema != "repomap.test-cov5k-r2-fix1.result.v1":
        raise IntegrityError("result schema changed")
    entry = _entry_map(manifest).get(artifact.case_id)
    if entry is None:
        raise IntegrityError("unexpected result")
    if artifact.authority_id != entry.authority_id:
        raise IntegrityError("authority does not match frozen case")
    if artifact.condition_id != entry.condition_id:
        raise IntegrityError("condition does not match frozen case")
    if artifact.semantic_group != entry.semantic_group:
        raise IntegrityError("semantic group does not match frozen case")
    if artifact.product_owner_id != entry.product_owner_id:
        raise IntegrityError("product owner does not match frozen case")
    if artifact.evidence_executor_id != entry.evidence_executor_id:
        raise IntegrityError("executor does not match frozen case")
    if (
        artifact.parameter_values != entry.parameter_values
        or artifact.enacted_parameters != entry.parameter_values
        or artifact.parameter_digest != parameter_digest(entry)
    ):
        raise IntegrityError("parameter tuple changed")
    if (
        artifact.runtime_identity_digest != manifest.runtime_identity_digest
        or artifact.source_manifest_digest != manifest.source_manifest_digest
        or artifact.policy_digest != manifest.policy_digest
        or artifact.protocol_digest != manifest.protocol_digest
        or artifact.preregistration_digest != manifest.preregistration_digest
    ):
        raise IntegrityError("source policy protocol or runtime drift")
    if _duplicate(field for field, _ in artifact.observed_fields):
        raise IntegrityError("duplicate observed field")
    observed = dict(artifact.observed_fields)
    if _EXPECTED_FIELDS.intersection(observed):
        raise IntegrityError("expected value inserted as observation")
    if entry.semantic_group == "G" and observed.get("aggregate") is True:
        raise IntegrityError("aggregate Group G result")
    if entry.semantic_group == "H" and observed.get("aggregate") is True:
        raise IntegrityError("aggregate Group H process zero")
    if tuple(observed) != entry.observation_schema:
        raise IntegrityError("observation schema changed")
    if (
        artifact.started_monotonic_ns < 0
        or artifact.completed_monotonic_ns < artifact.started_monotonic_ns
    ):
        raise IntegrityError("invalid monotonic relation")
    if (
        artifact.purpose != "qualification_model_rehearsal"
        or artifact.qualification_status != "unqualified"
        or not artifact.model_rehearsal_only
    ):
        raise IntegrityError("rehearsal was presented as qualification")
    _verify_group_semantics(entry, observed)
    unsigned = ResultArtifact(**{**asdict(artifact), "result_digest": ""})
    if artifact.result_digest != canonical_digest(unsigned):
        raise IntegrityError("result digest mismatch")
    return artifact


def verify_rehearsal(
    manifest: FrozenManifest,
    selected_case_ids: Iterable[str],
    artifacts: Iterable[ResultArtifact],
) -> SealedRehearsal:
    """Seal exactly one bounded, explicitly unqualified rehearsal selection."""
    verify_frozen(manifest)
    selected = tuple(selected_case_ids)
    results = tuple(verify_result(manifest, item) for item in artifacts)
    if _duplicate(selected):
        raise IntegrityError("duplicate selected case")
    result_cases = tuple(item.case_id for item in results)
    if _duplicate(item.result_digest for item in results):
        raise IntegrityError("duplicate result reused across cases")
    missing = set(selected) - set(result_cases)
    unexpected = set(result_cases) - set(selected)
    if missing:
        raise IntegrityError("missing result")
    if unexpected:
        raise IntegrityError("unexpected result")
    if len(result_cases) != len(selected):
        raise IntegrityError("one result reused across cases")
    return SealedRehearsal(
        registration_id=manifest.registration_id,
        preregistration_digest=manifest.preregistration_digest,
        result_digests=tuple(item.result_digest for item in results),
    )


__all__ = [
    "DraftManifest",
    "FrozenManifest",
    "IntegrityError",
    "LifecycleState",
    "ObservationSession",
    "ObservedTuple",
    "PROTOCOL_DIGEST",
    "RUNTIME_IDENTITY_DIGEST",
    "ResultArtifact",
    "SealedRehearsal",
    "THRESHOLDS",
    "TOLERANCES",
    "ValidatedManifest",
    "build_result",
    "canonical_digest",
    "create_draft",
    "freeze_manifest",
    "open_observations",
    "parameter_digest",
    "predecessor_accepts_p0",
    "resolve_owner",
    "validate_draft",
    "verify_frozen",
    "verify_rehearsal",
    "verify_result",
]
