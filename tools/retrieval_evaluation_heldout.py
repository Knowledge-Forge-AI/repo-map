"""Held-out split admission prerequisite gate for CLOE retrieval evaluation (Unit 3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any

from retrieval_evaluation_criteria_v2 import (
    CRITERIA_PROPOSAL_SCHEMA_V2,
    FutureCriteriaProposalV2,
    derive_future_criteria_proposal_v2,
)
from retrieval_evaluation_historical_evidence import verify_completed_attempt
from retrieval_evaluation_schema import AttemptDeclaration, FreezeManifest, TaskCatalog
from retrieval_evaluation_summary_v2 import BASELINE_REPORT_SCHEMA_V2, W3_DEFAULT_ARMS

HELD_OUT_PREREQUISITE_SCHEMA_V1 = "cloe-retrieval-held-out-prerequisite-v1"
HELD_OUT_PREREQUISITE_SCHEMA_V2 = "cloe-retrieval-held-out-prerequisite-v2"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CALIBRATION_ARTIFACTS = frozenset(
    {
        "declaration.json",
        "report.json",
        "observations.jsonl",
        "source-manifest.json",
        "sources.zip",
        "terminal.json",
    }
)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _validate_digest(label: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase sha256: digest")
    return value


def _validate_relative_path(label: str, value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} contains an unsafe relative path")
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"{label} contains an unsafe relative path")
    return value


def _validate_artifact_digests(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _CALIBRATION_ARTIFACTS:
        raise ValueError("calibration_artifact_digests must contain exactly the six retained files")
    result: dict[str, str] = {}
    for name, digest in value.items():
        _validate_relative_path("calibration artifact", name)
        result[name] = _validate_digest(f"calibration_artifact_digests[{name!r}]", digest)
    return result


def _validate_retained_population(
    declaration_raw: Mapping[str, Any], report: Mapping[str, Any], events: list[Any],
    proposal: FutureCriteriaProposalV2, catalog: TaskCatalog, freeze: FreezeManifest,
) -> None:
    declaration = AttemptDeclaration.from_mapping(declaration_raw)
    task_ids = tuple(task.task_id for task in catalog.calibration_tasks())
    if not (len(task_ids) == 24 and declaration.ordered_task_ids == task_ids
            and declaration.repetitions_per_task == 3 and len(declaration.arms) == len(W3_DEFAULT_ARMS)
            and set(declaration.arms) == set(W3_DEFAULT_ARMS)):
        raise ValueError("retained calibration declaration population is not the W3 set")
    arms = report.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != set(W3_DEFAULT_ARMS):
        raise ValueError("retained calibration report arms do not match W3")
    for arm_id in W3_DEFAULT_ARMS:
        arm = arms[arm_id]
        slots = arm.get("slots") if isinstance(arm, Mapping) else None
        if (not isinstance(arm, Mapping) or arm.get("whole_split_denominator") != 24
                or not isinstance(slots, (list, tuple)) or len(slots) != 24):
            raise ValueError("retained calibration report has an incomplete arm population")
        seen_slots: set[tuple[Any, Any]] = set()
        for slot in slots:
            if not isinstance(slot, Mapping):
                raise ValueError("retained calibration report contains a malformed slot")
            key = (slot.get("arm_id"), slot.get("task_id"))
            if key in seen_slots:
                raise ValueError("retained calibration report contains duplicate slots")
            seen_slots.add(key)
        if seen_slots != {(arm_id, task_id) for task_id in task_ids}:
            raise ValueError("retained calibration report slots do not match the catalog")
    def observation_keys(records: object, *, require_event: bool) -> set[tuple[str, str, int]]:
        if not isinstance(records, (list, tuple)):
            raise ValueError("retained calibration observations must be a sequence")
        keys: set[tuple[str, str, int]] = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("retained calibration observations contain a malformed record")
            if require_event and record.get("event") != "query_observed":
                continue
            identity = (record.get("arm_id"), record.get("task_id"), record.get("repetition"))
            if (not isinstance(identity[0], str) or not isinstance(identity[1], str)
                    or isinstance(identity[2], bool) or not isinstance(identity[2], int)):
                raise ValueError("retained calibration observations contain an invalid identity")
            key = (identity[0], identity[1], identity[2])
            if key in keys:
                raise ValueError("retained calibration observations contain duplicates")
            keys.add(key)
        return keys
    expected_observations = {(arm_id, task_id, repetition)
                             for arm_id in W3_DEFAULT_ARMS for task_id in task_ids
                             for repetition in range(1, 4)}
    if (observation_keys(report.get("repetition_observations"), require_event=False) != expected_observations
            or observation_keys(events, require_event=True) != expected_observations):
        raise ValueError("retained report observations do not match the W3 population")
    if report.get("phase_id") != declaration.phase_id:
        raise ValueError("retained report phase_id differs from declaration")
    derived = derive_future_criteria_proposal_v2(report, freeze_sha256=freeze.freeze_digest(),
                                                 catalog_sha256=catalog.catalog_digest(),
                                                 policy_digest=freeze.policy_digest)
    if derived.to_dict() != proposal.to_dict():
        raise ValueError("criteria proposal does not derive from the retained report")


@dataclass(frozen=True)
class HeldOutAdmissionPrerequisite:
    """Parent acceptance receipt required before any held-out split execution."""

    schema_version: str
    status: str
    parent_authorization_token: str
    accepted_criteria_sha256: str
    calibration_attempt_id: str
    freeze_sha256: str
    catalog_sha256: str
    policy_digest: str
    candidate_closure_digests: Mapping[str, str]
    calibration_artifact_digests: Mapping[str, str]

    def validate(self) -> HeldOutAdmissionPrerequisite:
        if self.schema_version != HELD_OUT_PREREQUISITE_SCHEMA_V2:
            raise ValueError(
                f"unsupported HeldOutAdmissionPrerequisite schema_version: {self.schema_version!r}"
            )
        if self.status != "parent_accepted":
            raise ValueError(
                f"held-out prerequisite status must be 'parent_accepted', got {self.status!r}"
            )
        if (
            not isinstance(self.parent_authorization_token, str)
            or not self.parent_authorization_token.strip()
            or any(ord(character) < 32 for character in self.parent_authorization_token)
        ):
            raise ValueError(
                "parent_authorization_token must be an opaque non-empty receipt string"
            )
        if (
            not isinstance(self.calibration_attempt_id, str)
            or not self.calibration_attempt_id.strip()
        ):
            raise ValueError("calibration_attempt_id must be non-empty")
        for label, digest in (
            ("accepted_criteria_sha256", self.accepted_criteria_sha256),
            ("freeze_sha256", self.freeze_sha256),
            ("catalog_sha256", self.catalog_sha256),
            ("policy_digest", self.policy_digest),
        ):
            _validate_digest(label, digest)
        if not self.candidate_closure_digests:
            raise ValueError("candidate_closure_digests must be non-empty")
        for rel, dig in self.candidate_closure_digests.items():
            _validate_relative_path("candidate_closure_digests", rel)
            _validate_digest(f"candidate_closure_digests[{rel!r}]", dig)
        _validate_artifact_digests(self.calibration_artifact_digests)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "parent_authorization_token": self.parent_authorization_token,
            "accepted_criteria_sha256": self.accepted_criteria_sha256,
            "calibration_attempt_id": self.calibration_attempt_id,
            "freeze_sha256": self.freeze_sha256,
            "catalog_sha256": self.catalog_sha256,
            "policy_digest": self.policy_digest,
            "candidate_closure_digests": dict(sorted(self.candidate_closure_digests.items())),
            "calibration_artifact_digests": dict(
                sorted(self.calibration_artifact_digests.items())
            ),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> HeldOutAdmissionPrerequisite:
        if not isinstance(data, Mapping):
            raise ValueError("HeldOutAdmissionPrerequisite requires a mapping")
        expected_keys = {
            "schema_version",
            "status",
            "parent_authorization_token",
            "accepted_criteria_sha256",
            "calibration_attempt_id",
            "freeze_sha256",
            "catalog_sha256",
            "policy_digest",
            "candidate_closure_digests",
            "calibration_artifact_digests",
        }
        if set(data) != expected_keys:
            raise ValueError("HeldOutAdmissionPrerequisite fields are not exact")
        for key in (
            "schema_version",
            "status",
            "parent_authorization_token",
            "accepted_criteria_sha256",
            "calibration_attempt_id",
            "freeze_sha256",
            "catalog_sha256",
            "policy_digest",
        ):
            val = data.get(key)
            if not isinstance(val, str):
                raise ValueError(f"HeldOutAdmissionPrerequisite.{key} must be a string")
        raw_digests = data.get("candidate_closure_digests")
        if not isinstance(raw_digests, Mapping):
            raise ValueError(
                "HeldOutAdmissionPrerequisite.candidate_closure_digests must be a mapping"
            )
        clean_digests: dict[str, str] = {}
        for k, v in raw_digests.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("candidate_closure_digests keys and values must be strings")
            clean_digests[k] = v
        raw_artifacts = data.get("calibration_artifact_digests")
        if not isinstance(raw_artifacts, Mapping):
            raise ValueError("calibration_artifact_digests must be a mapping")
        artifact_digests: dict[str, str] = {}
        for k, v in raw_artifacts.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("calibration_artifact_digests keys and values must be strings")
            artifact_digests[k] = v
        return cls(
            schema_version=data["schema_version"],
            status=data["status"],
            parent_authorization_token=data["parent_authorization_token"],
            accepted_criteria_sha256=data["accepted_criteria_sha256"],
            calibration_attempt_id=data["calibration_attempt_id"],
            freeze_sha256=data["freeze_sha256"],
            catalog_sha256=data["catalog_sha256"],
            policy_digest=data["policy_digest"],
            candidate_closure_digests=clean_digests,
            calibration_artifact_digests=artifact_digests,
        ).validate()


def validate_held_out_admission(
    prerequisite: HeldOutAdmissionPrerequisite | None,
    criteria_v2: Mapping[str, Any] | None,
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    live_candidate_digests: Mapping[str, str],
    calibration_directory: Path | None = None,
    allow_held_out_in_current_milestone: bool = False,
) -> None:
    """Enforce a parent receipt and retained calibration evidence before held-out work."""
    catalog.validate()
    freeze.validate()
    if not allow_held_out_in_current_milestone:
        raise ValueError(
            "held_out_execution_forbidden_in_milestone: W3 calibration milestone "
            "forbids held-out execution until parent accepts W3 calibration criteria"
        )
    if prerequisite is None:
        raise ValueError("held-out admission requires a HeldOutAdmissionPrerequisite")
    prerequisite.validate()
    if criteria_v2 is None or not isinstance(criteria_v2, Mapping):
        raise ValueError("held-out admission requires a v2 criteria proposal artifact")
    proposal = FutureCriteriaProposalV2.from_mapping(criteria_v2)
    if proposal.schema_version != CRITERIA_PROPOSAL_SCHEMA_V2:
        raise ValueError(
            f"held-out admission requires {CRITERIA_PROPOSAL_SCHEMA_V2!r}"
        )
    if proposal.status != "proposed_for_parent_review":
        raise ValueError(
            "held-out admission requires an immutable proposed criteria artifact"
        )
    if proposal.baseline_execution_purpose != "retained_calibration":
        raise ValueError(
            "held-out admission rejects historical or non-retained calibration criteria"
        )
    canonical_proposal = proposal.to_dict()
    if dict(criteria_v2) != canonical_proposal:
        raise ValueError("criteria proposal must be the exact canonical artifact")
    actual_criteria_sha256 = _canonical_sha256(canonical_proposal)
    if prerequisite.accepted_criteria_sha256 != actual_criteria_sha256:
        raise ValueError(
            "prerequisite accepted_criteria_sha256 mismatch against criteria artifact"
        )
    if proposal.freeze_sha256 != prerequisite.freeze_sha256:
        raise ValueError("criteria proposal freeze_sha256 mismatch against receipt")
    if proposal.catalog_sha256 != prerequisite.catalog_sha256:
        raise ValueError("criteria proposal catalog_sha256 mismatch against receipt")
    if proposal.policy_digest != prerequisite.policy_digest:
        raise ValueError("criteria proposal policy_digest mismatch against receipt")
    if prerequisite.calibration_attempt_id != criteria_v2.get("baseline_attempt_id"):
        raise ValueError(
            "prerequisite calibration_attempt_id mismatch against criteria baseline_attempt_id"
        )
    if prerequisite.freeze_sha256 != freeze.freeze_digest():
        raise ValueError("prerequisite freeze_sha256 mismatch against FreezeManifest")
    if prerequisite.catalog_sha256 != catalog.catalog_digest():
        raise ValueError("prerequisite catalog_sha256 mismatch against TaskCatalog")
    if prerequisite.policy_digest != freeze.policy_digest:
        raise ValueError("prerequisite policy_digest mismatch against FreezeManifest")
    if dict(prerequisite.candidate_closure_digests) != dict(live_candidate_digests):
        raise ValueError(
            "prerequisite candidate_closure_digests mismatch against live candidate source"
        )
    if calibration_directory is None:
        raise ValueError("held-out admission requires retained calibration evidence")
    if (
        calibration_directory.is_symlink()
        or not calibration_directory.is_dir()
        or calibration_directory.name != prerequisite.calibration_attempt_id
    ):
        raise ValueError("retained calibration evidence directory is not the declared attempt")
    evidence = verify_completed_attempt(
        calibration_directory,
        expected_terminal_sha256=prerequisite.calibration_artifact_digests["terminal.json"],
    )
    actual_artifacts = evidence.get("sha256")
    if actual_artifacts != dict(prerequisite.calibration_artifact_digests):
        raise ValueError("retained calibration artifact digests mismatch against receipt")
    declaration = evidence["declaration"]
    report = evidence["report"]
    if declaration.get("attempt_id") != prerequisite.calibration_attempt_id:
        raise ValueError("retained declaration attempt_id mismatch against receipt")
    if declaration.get("split") != "calibration":
        raise ValueError("held-out admission requires a calibration declaration")
    runner_profile = declaration.get("runner_profile")
    if (
        not isinstance(runner_profile, Mapping)
        or runner_profile.get("execution_purpose") != "retained_calibration"
    ):
        raise ValueError("held-out admission requires a retained calibration declaration")
    if declaration.get("freeze_sha256") != prerequisite.freeze_sha256:
        raise ValueError("retained declaration freeze_sha256 mismatch against receipt")
    if declaration.get("catalog_sha256") != prerequisite.catalog_sha256:
        raise ValueError("retained declaration catalog_sha256 mismatch against receipt")
    if dict(declaration.get("candidate_closure_digests", {})) != dict(
        prerequisite.candidate_closure_digests
    ):
        raise ValueError("retained declaration closure mismatch against receipt")
    if report.get("schema_version") != BASELINE_REPORT_SCHEMA_V2:
        raise ValueError("held-out admission requires a v2 retained calibration report")
    if report.get("execution_purpose") != "retained_calibration":
        raise ValueError("held-out admission requires a retained calibration report")
    if report.get("split") != "calibration" or report.get("held_out_executed") is not False:
        raise ValueError("retained calibration report is not a calibration-only report")
    if (
        report.get("freeze_sha256") != prerequisite.freeze_sha256
        or report.get("catalog_sha256") != prerequisite.catalog_sha256
        or report.get("policy_digest") != prerequisite.policy_digest
    ):
        raise ValueError("retained calibration report does not match the accepted freeze")
    _validate_retained_population(
        declaration,
        report,
        evidence["events"],
        proposal,
        catalog,
        freeze,
    )


__all__ = [
    "HELD_OUT_PREREQUISITE_SCHEMA_V1",
    "HELD_OUT_PREREQUISITE_SCHEMA_V2",
    "HeldOutAdmissionPrerequisite",
    "validate_held_out_admission",
]
