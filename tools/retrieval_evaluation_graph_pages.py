"""Completeness accounting for bounded evaluator graph reads."""
from __future__ import annotations

from dataclasses import dataclass, field

from common_lore_index.retrieval.query_contracts import OmissionRecord
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult


@dataclass
class GraphPageEvidence:
    _omissions: list[OmissionRecord] = field(default_factory=list)

    def omit(self, reason: str) -> None:
        omission = OmissionRecord(
            "scope", None, reason, "bounded graph evaluation does not attest complete selected scope",
        ).validate()
        if omission not in self._omissions:
            self._omissions.append(omission)

    def observe(self, result: FencedObservationResult) -> None:
        for omission in result.omissions:
            if omission not in self._omissions:
                self._omissions.append(omission)
        if (result.has_more or not result.scope_complete) and not result.omissions:
            self.omit("observation_page_limit")

    @property
    def omissions(self) -> tuple[OmissionRecord, ...]:
        return tuple(self._omissions)

    @property
    def scope_complete(self) -> bool:
        return not self._omissions
