"""Typed result-v2 objects and collection; validation stays in the contract module."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from retrieval_evaluation_accounting import EvaluatorByteBreakdownV1
from retrieval_semantic_experiment_artifacts import MEMBER_NAMES
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentPlan
from retrieval_semantic_experiment_scope import CorrespondenceCostSample
from retrieval_semantic_baseline_results import (
    RESULT_SCHEMA, _identity, _refuse, _sha, _validate_result,
)


@dataclass(frozen=True)
class BaselineResultV2:
    """Evaluator-only result; raw envelopes and journals remain separate evidence."""

    attempt_id: str
    generation: int
    status: str
    plan: Mapping[str, object]
    cells: tuple[Mapping[str, object], ...]
    correspondence: tuple[Mapping[str, object], ...]
    byte_work: tuple[Mapping[str, object], ...]
    raw_journal: Mapping[str, object]
    failure_code: str | None = None

    def to_mapping(self) -> dict[str, object]:
        mapping = {
            "schema": RESULT_SCHEMA,
            "attempt_id": self.attempt_id,
            "generation": self.generation,
            "status": self.status,
            "failure_code": self.failure_code,
            "plan": dict(self.plan),
            "cells": [dict(item) for item in self.cells],
            "correspondence": [dict(item) for item in self.correspondence],
            "byte_work": [dict(item) for item in self.byte_work],
            "raw_journal": dict(self.raw_journal),
        }
        _validate_result(mapping)
        return mapping

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BaselineResultV2":
        _validate_result(value)
        return cls(
            attempt_id=cast(str, value["attempt_id"]),
            generation=cast(int, value["generation"]),
            status=cast(str, value["status"]),
            plan=cast(Mapping[str, object], value["plan"]),
            cells=tuple(cast(list[Mapping[str, object]], value["cells"])),
            correspondence=tuple(cast(list[Mapping[str, object]], value["correspondence"])),
            byte_work=tuple(cast(list[Mapping[str, object]], value["byte_work"])),
            raw_journal=cast(Mapping[str, object], value["raw_journal"]),
            failure_code=cast(str | None, value["failure_code"]),
        )


class ResultV2Collector:
    """Collect actual typed records without changing legacy journal calls."""

    def __init__(self, plan: ExperimentPlan) -> None:
        self._plan = plan.validate()
        self._cells: list[dict[str, object]] = []
        self._correspondence: list[dict[str, object]] = []
        self._byte_work: list[dict[str, object]] = []
        self._seen_cells: set[tuple[str, str, int]] = set()
        self._seen_correspondence: set[tuple[str, str, int]] = set()
        self._seen_byte_work: set[tuple[str, str, int]] = set()

    def _bound(self, value: Mapping[str, object]) -> dict[str, object]:
        identity = _identity(value)
        arm_id = cast(str, identity["arm_id"])
        task_id = cast(str, identity["task_id"])
        repetition = cast(int, identity["repetition"])
        if (
            arm_id not in self._plan.arms
            or task_id not in self._plan.task_ids
            or repetition > self._plan.repetitions
        ):
            raise _refuse("result_identity_unbound")
        return identity

    @staticmethod
    def _key(identity: Mapping[str, object]) -> tuple[str, str, int]:
        return (
            cast(str, identity["arm_id"]), cast(str, identity["task_id"]),
            cast(int, identity["repetition"]),
        )

    def add_cell(self, identity: Mapping[str, object], cell: ExperimentCell) -> None:
        ident = self._bound(identity)
        if type(cell) is not ExperimentCell:
            raise _refuse("result_cell_type")
        if self._key(ident) in self._seen_cells:
            raise _refuse("result_duplicate_cell")
        self._seen_cells.add(self._key(ident))
        self._cells.append({"identity": ident, "cell": cell.to_dict()})

    def add_correspondence(
        self,
        identity: Mapping[str, object],
        sidecar: object,
        *,
        observed_backend: str,
        target_backend: str,
        status: str,
        gap_reason: str | None,
        cost: CorrespondenceCostSample,
    ) -> None:
        ident = self._bound(identity)
        if type(cost) is not CorrespondenceCostSample:
            raise _refuse("result_correspondence_cost_type")
        if self._key(ident) in self._seen_correspondence:
            raise _refuse("result_duplicate_correspondence")
        self._seen_correspondence.add(self._key(ident))
        converter = getattr(sidecar, "to_dict", None)
        if not callable(converter):
            raise _refuse("result_sidecar_to_dict_required")
        target_pin = (
            getattr(sidecar, "sqlite_pin", None)
            if target_backend == "sqlite" else getattr(sidecar, "postgres_pin", None)
        )
        verified_pin = target_pin if status == "verified" else None
        try:
            sidecar_map = converter(
                observed_backend=observed_backend,
                target_backend=target_backend,
                status=status,
                gap_reason=gap_reason,
                verified_pin=verified_pin,
                cost=cost,
            )
        except Exception as error:
            raise _refuse("result_sidecar_unavailable") from error
        if not isinstance(sidecar_map, Mapping):
            raise _refuse("result_sidecar_mapping_required")
        self._correspondence.append(
            {"identity": ident, "sidecar": dict(sidecar_map), "cost": cost.to_dict()}
        )

    def add_byte_work(
        self, identity: Mapping[str, object], accounting: EvaluatorByteBreakdownV1
    ) -> None:
        ident = self._bound(identity)
        if type(accounting) is not EvaluatorByteBreakdownV1:
            raise _refuse("result_byte_work_type")
        if self._key(ident) in self._seen_byte_work:
            raise _refuse("result_duplicate_byte_work")
        self._seen_byte_work.add(self._key(ident))
        self._byte_work.append({"identity": ident, "accounting": accounting.to_dict()})

    def finish(
        self, *, status: str, raw_journal_members: Mapping[str, bytes],
        failure_code: str | None = None,
    ) -> BaselineResultV2:
        if (
            not isinstance(raw_journal_members, Mapping)
            or frozenset(raw_journal_members) != set(MEMBER_NAMES)
            or any(type(raw_journal_members[name]) is not bytes for name in MEMBER_NAMES)
        ):
            raise _refuse("result_raw_journal_input")
        raw = {
            name: {
                "length": len(raw_journal_members[name]),
                "sha256": _sha(raw_journal_members[name]),
            }
            for name in MEMBER_NAMES
        }
        result = BaselineResultV2(
            self._plan.attempt_id, self._plan.generation, status,
            self._plan.to_mapping(), tuple(self._cells), tuple(self._correspondence),
            tuple(self._byte_work), raw, failure_code,
        )
        result.to_mapping()
        return result


__all__ = ["BaselineResultV2", "ResultV2Collector"]
