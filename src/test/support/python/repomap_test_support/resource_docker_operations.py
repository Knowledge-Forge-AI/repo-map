"""Durable append-only authority for every canonical Docker build/pull operation.

Counters are derived from this population, never asserted. An operation that
executed remains counted after its output image is deleted, after the run
fails, and after any later report error, because records are only ever
appended and are fsynced before the Docker call they authorize.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from repomap_test_support.resource_docker_operation_records import (
    DERIVED_OPERATION_FIELDS,
    DockerAuthorityClass,
    DockerOperationEvent,
    DockerOperationKind,
    DockerOperationResult,
    MaterializationObservation,
    _BUILD_KINDS,
)


JOURNAL_SCHEMA = "repomap-docker-operation-journal-v1"
JOURNAL_FILENAME = "docker-operation-journal.jsonl"


class DockerOperationJournalError(RuntimeError):
    """The operation population could not be recorded or read exactly."""


# Preserve the original public qualified identities after moving definitions
# behind this module's compatibility facade.
DockerAuthorityClass.__module__ = __name__
DockerOperationEvent.__module__ = __name__
DockerOperationKind.__module__ = __name__
DockerOperationResult.__module__ = __name__
MaterializationObservation.__module__ = __name__


class DockerOperationJournal:
    """Append-only, fsynced, run-scoped Docker operation population."""

    def __init__(self, path: Path, *, run_id: str) -> None:
        path = Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise DockerOperationJournalError(
                "Docker operation journal path is not an exact private file"
            )
        self.path = path
        self.run_id = str(run_id)
        self._ordinal = 0

    @classmethod
    def for_ledger(cls, ledger: Any) -> "DockerOperationJournal":
        return cls(
            Path(ledger.path).resolve().parent / JOURNAL_FILENAME,
            run_id=ledger.identity.run_id,
        )

    def begin(
        self,
        *,
        kind: DockerOperationKind,
        authority: DockerAuthorityClass,
        owner: str,
        mechanism: str,
        request: str,
    ) -> str:
        """Durably record intent BEFORE the daemon is asked to mutate."""
        event_id = self._next_event_id()
        self._append(
            {
                "event_id": event_id,
                "kind": DockerOperationKind(kind).value,
                "authority": DockerAuthorityClass(authority).value,
                "owner": str(owner),
                "mechanism": str(mechanism),
                "request": str(request),
                "result": DockerOperationResult.STARTED.value,
                "started": True,
                "completed": False,
            }
        )
        return event_id

    def complete(
        self,
        event_id: str,
        *,
        result: DockerOperationResult,
        image_ids: Sequence[str] = (),
        failure_category: str | None = None,
        cleanup_disposition: str | None = None,
    ) -> None:
        result = DockerOperationResult(result)
        if result is DockerOperationResult.STARTED:
            raise DockerOperationJournalError("completion result must be terminal")
        self._append(
            {
                "event_id": str(event_id),
                "result": result.value,
                "completed": True,
                "image_ids": sorted(str(item) for item in image_ids),
                "failure_category": failure_category,
                "cleanup_disposition": cleanup_disposition,
            }
        )

    def refuse(
        self,
        *,
        kind: DockerOperationKind,
        owner: str,
        mechanism: str,
        request: str,
        failure_category: str,
    ) -> str:
        """Record a forbidden operation that is rejected before daemon mutation."""
        event_id = self._next_event_id()
        self._append(
            {
                "event_id": event_id,
                "kind": DockerOperationKind(kind).value,
                "authority": DockerAuthorityClass.UNMANAGED_FORBIDDEN.value,
                "owner": str(owner),
                "mechanism": str(mechanism),
                "request": str(request),
                "result": DockerOperationResult.REFUSED.value,
                "started": False,
                "completed": True,
                "failure_category": str(failure_category),
            }
        )
        return event_id

    def record_materialization(
        self,
        *,
        event_id: str,
        final_image_id: str,
        intermediate_created_ids: Sequence[str],
        intermediate_removed_ids: Sequence[str],
    ) -> None:
        self._append(
            {
                "record": "materialization",
                "event_id": str(event_id),
                "final_image_id": str(final_image_id),
                "intermediate_created_ids": sorted(
                    str(x) for x in intermediate_created_ids
                ),
                "intermediate_removed_ids": sorted(
                    str(x) for x in intermediate_removed_ids
                ),
            }
        )

    def events(self) -> tuple[DockerOperationEvent, ...]:
        states: dict[str, dict[str, Any]] = {}
        order: dict[str, int] = {}
        for record in self._read():
            if record.get("record") == "materialization":
                continue
            event_id = str(record["event_id"])
            if event_id not in states:
                states[event_id] = {}
                order[event_id] = int(record["ordinal"])
            states[event_id].update(record)
        events = []
        for event_id, state in states.items():
            events.append(
                DockerOperationEvent(
                    ordinal=order[event_id],
                    event_id=event_id,
                    kind=DockerOperationKind(state["kind"]),
                    authority=DockerAuthorityClass(state["authority"]),
                    owner=str(state["owner"]),
                    mechanism=str(state["mechanism"]),
                    request=str(state["request"]),
                    result=DockerOperationResult(state["result"]),
                    started=bool(state.get("started")),
                    completed=bool(state.get("completed")),
                    image_ids=tuple(state.get("image_ids") or ()),
                    failure_category=state.get("failure_category"),
                    cleanup_disposition=state.get("cleanup_disposition"),
                )
            )
        return tuple(sorted(events, key=lambda item: item.ordinal))

    def materializations(self) -> tuple[MaterializationObservation, ...]:
        observations = []
        for record in self._read():
            if record.get("record") != "materialization":
                continue
            observations.append(
                MaterializationObservation(
                    event_id=str(record["event_id"]),
                    final_image_id=str(record["final_image_id"]),
                    intermediate_created_ids=tuple(
                        record.get("intermediate_created_ids") or ()
                    ),
                    intermediate_removed_ids=tuple(
                        record.get("intermediate_removed_ids") or ()
                    ),
                )
            )
        return tuple(observations)

    def derive_counters(self) -> dict[str, int]:
        """Every field is a count over the observed closed population."""
        events = self.events()
        counters = {
            "product_or_build_profile_build_count": self._count(
                events,
                kinds=_BUILD_KINDS,
                authority=DockerAuthorityClass.PRODUCT_OR_BUILD_PROFILE,
                executed_only=True,
            ),
            "managed_test_runtime_image_build_count": self._count(
                events,
                kinds={DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD},
                authority=DockerAuthorityClass.MANAGED_TEST_RUNTIME,
                executed_only=True,
            ),
            "managed_system_candidate_image_build_count": self._count(
                events,
                kinds={DockerOperationKind.DOCKER_BUILD},
                authority=DockerAuthorityClass.MANAGED_SYSTEM_CANDIDATE,
                executed_only=True,
            ),
            "managed_external_base_pull_count": self._count(
                events,
                kinds={DockerOperationKind.DOCKER_PULL},
                authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
                executed_only=True,
            ),
            "unmanaged_build_count": self._count(
                events,
                kinds=_BUILD_KINDS,
                authority=DockerAuthorityClass.UNMANAGED_FORBIDDEN,
                executed_only=False,
            ),
            "unmanaged_pull_count": self._count(
                events,
                kinds={DockerOperationKind.DOCKER_PULL},
                authority=DockerAuthorityClass.UNMANAGED_FORBIDDEN,
                executed_only=False,
            ),
        }
        observations = self.materializations()
        created = sum(len(item.intermediate_created_ids) for item in observations)
        removed = sum(len(item.intermediate_removed_ids) for item in observations)
        residue = sum(len(item.intermediate_terminal_ids) for item in observations)
        counters["managed_runtime_build_intermediate_created_count"] = created
        counters["managed_runtime_build_intermediate_removed_count"] = removed
        counters["managed_runtime_build_intermediate_residue_count"] = residue
        return counters

    def derivation_evidence(self) -> dict[str, Any]:
        """Explain each derived field so no zero can be self-fulfilling."""
        events = self.events()
        observations = self.materializations()
        return {
            "schema": JOURNAL_SCHEMA,
            "run_id": self.run_id,
            "journal_path": str(self.path),
            "event_count": len(events),
            "materialization_count": len(observations),
            "events": [
                {
                    "ordinal": item.ordinal,
                    "event_id": item.event_id,
                    "kind": item.kind.value,
                    "authority": item.authority.value,
                    "owner": item.owner,
                    "mechanism": item.mechanism,
                    "request": item.request,
                    "result": item.result.value,
                    "executed": item.executed,
                    "image_ids": list(item.image_ids),
                    "failure_category": item.failure_category,
                    "cleanup_disposition": item.cleanup_disposition,
                }
                for item in events
            ],
            "materializations": [
                {
                    "event_id": item.event_id,
                    "final_image_id": item.final_image_id,
                    "intermediate_created_ids": list(item.intermediate_created_ids),
                    "intermediate_removed_ids": list(item.intermediate_removed_ids),
                    "intermediate_terminal_ids": list(item.intermediate_terminal_ids),
                }
                for item in observations
            ],
            "derived": self.derive_counters(),
        }

    @staticmethod
    def _count(
        events: Iterable[DockerOperationEvent],
        *,
        kinds: Iterable[DockerOperationKind],
        authority: DockerAuthorityClass,
        executed_only: bool,
    ) -> int:
        kinds = frozenset(kinds)
        return sum(
            1
            for item in events
            if item.kind in kinds
            and item.authority is authority
            and (item.executed or not executed_only)
        )

    def _next_event_id(self) -> str:
        return f"{self.run_id}:{self._ordinal + 1:06d}"

    def _append(self, payload: Mapping[str, Any]) -> None:
        self._ordinal += 1
        record = {
            "schema": JOURNAL_SCHEMA,
            "run_id": self.run_id,
            "ordinal": self._ordinal,
            **dict(payload),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        if self.path.is_symlink():
            raise DockerOperationJournalError("Docker operation journal is unsafe")
        records = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("schema") != JOURNAL_SCHEMA:
                    raise DockerOperationJournalError(
                        "Docker operation journal schema differs"
                    )
                if record.get("run_id") != self.run_id:
                    raise DockerOperationJournalError(
                        "Docker operation journal run identity differs"
                    )
                records.append(record)
        return tuple(sorted(records, key=lambda item: int(item["ordinal"])))


__all__ = [
    "DERIVED_OPERATION_FIELDS",
    "DockerAuthorityClass",
    "DockerOperationEvent",
    "DockerOperationJournal",
    "DockerOperationJournalError",
    "DockerOperationKind",
    "DockerOperationResult",
    "JOURNAL_FILENAME",
    "JOURNAL_SCHEMA",
    "MaterializationObservation",
]
