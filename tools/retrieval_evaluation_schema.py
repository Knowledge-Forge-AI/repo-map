"""Schemas for the 36-task retrieval evaluation catalog, freeze manifest, and attempt declarations (S3)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.query_contracts import EvaluationLocator

TASK_CATALOG_SCHEMA_VERSION = "cloe-retrieval-task-catalog-v1"
FREEZE_MANIFEST_SCHEMA_VERSION = "cloe-retrieval-freeze-v1"
ATTEMPT_DECLARATION_SCHEMA_VERSION = "cloe-retrieval-attempt-declaration-v1"

TASK_FAMILIES: dict[str, tuple[int, int, int]] = {
    "exact_symbol_and_partial_name": (4, 3, 1),
    "punctuation_phrase_and_distractors": (4, 3, 1),
    "behavior_without_exact_symbol": (3, 2, 1),
    "cross_source_shell_nix_investigation": (4, 3, 1),
    "relevant_tests_for_behavior": (3, 2, 1),
    "code_plus_design_or_message_context": (3, 2, 1),
    "independent_document_email_feed_retrieval": (4, 3, 1),
    "duplicate_paths_quotations_long_unicode": (4, 2, 2),
    "absent_ambiguous_changed_deleted_stale": (5, 3, 2),
    "direct_location_zero_graph_calls": (2, 1, 1),
}

VALID_SPLITS = frozenset({"calibration", "held_out"})
VALID_STRATA = frozenset({"body", "metadata", "graph_topology", "direct_handoff"})
VALID_GRADING_RULES = frozenset(
    {"ranked_positive", "absent_answer", "safety_refusal", "direct_handoff"}
)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class GoldTarget:
    """One pre-authored gold locator and integer relevance grade (0..3)."""

    locator: EvaluationLocator
    relevance_grade: int
    rationale: str
    canonical_key: str | None = None

    def validate(self) -> GoldTarget:
        self.locator.validate()
        if (
            isinstance(self.relevance_grade, bool)
            or not isinstance(self.relevance_grade, int)
            or not (0 <= self.relevance_grade <= 3)
        ):
            raise ValueError("relevance_grade must be an integer in 0..3")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("rationale must be a non-empty string")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "locator": self.locator.to_dict(),
            "relevance_grade": self.relevance_grade,
            "rationale": self.rationale,
            "canonical_key": self.canonical_key,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GoldTarget:
        loc_raw = data.get("locator")
        if not isinstance(loc_raw, Mapping):
            raise ValueError("locator must be a mapping")
        return cls(
            locator=EvaluationLocator.from_mapping(loc_raw),
            relevance_grade=data["relevance_grade"],
            rationale=data["rationale"],
            canonical_key=data.get("canonical_key"),
        ).validate()


@dataclass(frozen=True)
class EvaluationTask:
    """One frozen retrieval evaluation task in the 36-task catalog."""

    task_id: str
    family: str
    split: str
    question: str
    permitted_query_plan: Mapping[str, Any]
    graph_id: str
    generation: int
    selected_bindings: tuple[str, ...]
    source_path_prefix: str | None
    requested_mode: str
    intended_match_surface: str
    comparability_stratum: str
    comparator_exposure: Mapping[str, str]
    gold_targets: tuple[GoldTarget, ...]
    expected_capability_state: str
    expected_refusal_code: str | None
    grading_rule: str

    def validate(self) -> EvaluationTask:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if self.family not in TASK_FAMILIES:
            raise ValueError(f"unknown task family: {self.family!r}")
        if self.split not in VALID_SPLITS:
            raise ValueError(f"invalid split: {self.split!r}")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be non-empty")
        if not isinstance(self.permitted_query_plan, Mapping) or not self.permitted_query_plan:
            raise ValueError("permitted_query_plan must be a non-empty mapping")
        if self.generation not in (1, 2):
            raise ValueError("generation must be 1 or 2")
        if self.comparability_stratum not in VALID_STRATA:
            raise ValueError(f"invalid comparability_stratum: {self.comparability_stratum!r}")
        if self.grading_rule not in VALID_GRADING_RULES:
            raise ValueError(f"invalid grading_rule: {self.grading_rule!r}")
        seen_locators: set[tuple[str, str, int | None, int | None]] = set()
        for gold in self.gold_targets:
            gold.validate()
            key = gold.locator.identity_key()
            if key in seen_locators:
                raise ValueError(f"duplicate gold locator in {self.task_id}: {key}")
            seen_locators.add(key)
        if self.grading_rule in {"ranked_positive", "direct_handoff"} and not any(
            g.relevance_grade > 0 for g in self.gold_targets
        ):
            raise ValueError(f"{self.task_id}: positive grading_rule requires grade > 0 target")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "task_id": self.task_id,
            "family": self.family,
            "split": self.split,
            "question": self.question,
            "permitted_query_plan": dict(self.permitted_query_plan),
            "graph_id": self.graph_id,
            "generation": self.generation,
            "selected_bindings": list(self.selected_bindings),
            "source_path_prefix": self.source_path_prefix,
            "requested_mode": self.requested_mode,
            "intended_match_surface": self.intended_match_surface,
            "comparability_stratum": self.comparability_stratum,
            "comparator_exposure": dict(self.comparator_exposure),
            "gold_targets": [g.to_dict() for g in self.gold_targets],
            "expected_capability_state": self.expected_capability_state,
            "expected_refusal_code": self.expected_refusal_code,
            "grading_rule": self.grading_rule,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> EvaluationTask:
        golds_raw = data.get("gold_targets", ())
        if not isinstance(golds_raw, (list, tuple)):
            raise ValueError("gold_targets must be a list or tuple")
        return cls(
            task_id=data["task_id"],
            family=data["family"],
            split=data["split"],
            question=data["question"],
            permitted_query_plan=dict(data["permitted_query_plan"]),
            graph_id=data["graph_id"],
            generation=int(data["generation"]),
            selected_bindings=tuple(data.get("selected_bindings", ())),
            source_path_prefix=data.get("source_path_prefix"),
            requested_mode=data["requested_mode"],
            intended_match_surface=data["intended_match_surface"],
            comparability_stratum=data["comparability_stratum"],
            comparator_exposure=dict(data.get("comparator_exposure", {})),
            gold_targets=tuple(
                g if isinstance(g, GoldTarget) else GoldTarget.from_mapping(g) for g in golds_raw
            ),
            expected_capability_state=data["expected_capability_state"],
            expected_refusal_code=data.get("expected_refusal_code"),
            grading_rule=data["grading_rule"],
        ).validate()


@dataclass(frozen=True)
class TaskCatalog:
    """Frozen 36-task (24 calibration, 12 held-out) retrieval evaluation catalog."""

    schema_version: str
    fixture_id: str
    tasks: tuple[EvaluationTask, ...]

    def validate(self) -> TaskCatalog:
        if self.schema_version != TASK_CATALOG_SCHEMA_VERSION:
            raise ValueError(f"unsupported TaskCatalog schema_version: {self.schema_version!r}")
        if len(self.tasks) != 36:
            raise ValueError(f"TaskCatalog requires exactly 36 tasks, got {len(self.tasks)}")
        seen_ids: set[str] = set()
        for task in self.tasks:
            task.validate()
            if task.task_id in seen_ids:
                raise ValueError(f"duplicate task_id: {task.task_id!r}")
            seen_ids.add(task.task_id)
        cal, held = self.calibration_tasks(), self.held_out_tasks()
        if len(cal) != 24 or len(held) != 12:
            raise ValueError(f"expected 24 calibration and 12 held_out, got {len(cal)}/{len(held)}")
        for family, (expected_total, expected_cal, expected_held) in TASK_FAMILIES.items():
            fam_all = [t for t in self.tasks if t.family == family]
            fam_cal = [t for t in fam_all if t.split == "calibration"]
            fam_held = [t for t in fam_all if t.split == "held_out"]
            if (len(fam_all), len(fam_cal), len(fam_held)) != (
                expected_total,
                expected_cal,
                expected_held,
            ):
                raise ValueError(f"family {family!r} count mismatch")
        return self

    def calibration_tasks(self) -> tuple[EvaluationTask, ...]:
        return tuple(t for t in self.tasks if t.split == "calibration")

    def held_out_tasks(self) -> tuple[EvaluationTask, ...]:
        return tuple(t for t in self.tasks if t.split == "held_out")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    def catalog_digest(self) -> str:
        return _canonical_sha256(self.to_dict())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TaskCatalog:
        tasks_raw = data.get("tasks", ())
        if not isinstance(tasks_raw, (list, tuple)):
            raise ValueError("tasks must be a sequence")
        return cls(
            schema_version=data["schema_version"],
            fixture_id=data["fixture_id"],
            tasks=tuple(EvaluationTask.from_mapping(item) for item in tasks_raw),
        ).validate()


@dataclass(frozen=True)
class FreezeManifest:
    """Pre-query cryptographic freeze over catalog, fixture files, working copies, and policy."""

    schema_version: str
    fixture_id: str
    catalog_sha256: str
    committed_fixture_files: Mapping[str, str]
    generation_1_files: Mapping[str, Mapping[str, Any]]
    generation_2_files: Mapping[str, Mapping[str, Any]]
    representation_version: str
    policy_digest: str

    def validate(self) -> FreezeManifest:
        if self.schema_version != FREEZE_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported FreezeManifest schema_version: {self.schema_version!r}")
        for label, digest in (
            ("catalog_sha256", self.catalog_sha256),
            ("policy_digest", self.policy_digest),
        ):
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise ValueError(f"{label} must be a sha256: digest")
        if not self.generation_1_files or not self.generation_2_files:
            raise ValueError("generation_1_files and generation_2_files must be non-empty")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "catalog_sha256": self.catalog_sha256,
            "committed_fixture_files": dict(sorted(self.committed_fixture_files.items())),
            "generation_1_files": {k: dict(v) for k, v in sorted(self.generation_1_files.items())},
            "generation_2_files": {k: dict(v) for k, v in sorted(self.generation_2_files.items())},
            "representation_version": self.representation_version,
            "policy_digest": self.policy_digest,
        }

    def freeze_digest(self) -> str:
        return _canonical_sha256(self.to_dict())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FreezeManifest:
        return cls(
            schema_version=data["schema_version"],
            fixture_id=data["fixture_id"],
            catalog_sha256=data["catalog_sha256"],
            committed_fixture_files=dict(data["committed_fixture_files"]),
            generation_1_files=dict(data["generation_1_files"]),
            generation_2_files=dict(data["generation_2_files"]),
            representation_version=data["representation_version"],
            policy_digest=data["policy_digest"],
        ).validate()


@dataclass(frozen=True)
class AttemptDeclaration:
    """Pre-registered baseline attempt declaration before executing queries."""

    schema_version: str
    attempt_id: str
    phase_id: str
    split: str
    freeze_sha256: str
    catalog_sha256: str
    ordered_task_ids: tuple[str, ...]
    arms: tuple[str, ...]
    repetitions_per_task: int
    stopping_rule: str
    replacement_policy: str
    candidate_closure_digests: Mapping[str, str]
    runner_profile: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> AttemptDeclaration:
        if self.schema_version != ATTEMPT_DECLARATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported AttemptDeclaration schema: {self.schema_version!r}")
        if self.split != "calibration":
            raise ValueError(
                f"W2 refuses attempt declaration for split {self.split!r}; held_out is reserved for W3"
            )
        if len(self.ordered_task_ids) != 24:
            raise ValueError("calibration attempt requires all 24 calibration task_ids")
        if self.repetitions_per_task < 1:
            raise ValueError("repetitions_per_task must be >= 1")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "phase_id": self.phase_id,
            "split": self.split,
            "freeze_sha256": self.freeze_sha256,
            "catalog_sha256": self.catalog_sha256,
            "ordered_task_ids": list(self.ordered_task_ids),
            "arms": list(self.arms),
            "repetitions_per_task": self.repetitions_per_task,
            "stopping_rule": self.stopping_rule,
            "replacement_policy": self.replacement_policy,
            "candidate_closure_digests": dict(sorted(self.candidate_closure_digests.items())),
            "runner_profile": dict(self.runner_profile),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AttemptDeclaration:
        return cls(
            schema_version=data["schema_version"],
            attempt_id=data["attempt_id"],
            phase_id=data["phase_id"],
            split=data["split"],
            freeze_sha256=data["freeze_sha256"],
            catalog_sha256=data["catalog_sha256"],
            ordered_task_ids=tuple(data["ordered_task_ids"]),
            arms=tuple(data["arms"]),
            repetitions_per_task=int(data["repetitions_per_task"]),
            stopping_rule=data["stopping_rule"],
            replacement_policy=data["replacement_policy"],
            candidate_closure_digests=dict(data["candidate_closure_digests"]),
            runner_profile=dict(data.get("runner_profile", {})),
        ).validate()


def load_task_catalog(path: Path) -> TaskCatalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("catalog JSON must be an object")
    return TaskCatalog.from_mapping(raw)


def load_freeze_manifest(path: Path) -> FreezeManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("freeze JSON must be an object")
    return FreezeManifest.from_mapping(raw)
