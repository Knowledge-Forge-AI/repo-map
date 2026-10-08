"""Mutable durable control double; supervisor authority still uses a real process."""
from __future__ import annotations

from typing import Any

from repomap_kg.coordinator._publication_phase import _fencing_identity


class FencingControl:
    def __init__(self, attempt: object, *, restart: bool = False) -> None:
        identity = _fencing_identity(attempt)
        self.instance = "replacement" if restart else identity["instance"]
        self.epoch = int(str(identity["epoch"])) + int(restart)
        self.active = True
        self.attempt = {
            "job_id": identity["job_id"], "attempt": identity["attempt"],
            "graph_id": identity["graph_id"], "coordinator_instance_id": identity["instance"],
            "fencing_epoch": identity["epoch"], "graph_lease_fencing_epoch": identity["graph_lease_epoch"],
            "job_state": "reconciliation_required" if restart else "running",
            "job_publication_state": "commit_unknown", "finished_at": "newly-stamped",
            "supervisor_registration_digest": None,
            "supervisor_registration_consumed": False,
            **{key: identity[key] for key in (
                "source_generation", "config_generation", "extractor_generation", "canonicalizer_generation",
            )},
        }
        self.lease = {**self.attempt, "lease_active": not restart}
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False
        self.rolled_back = False
        self.rowcount = 1
        self.selected: dict[str, Any] | None = None

    def connect(self) -> Any:
        return self

    def __enter__(self) -> FencingControl:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def cursor(self, **kwargs: Any) -> FencingControl:
        return self

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executions.append((query, params))
        if "SELECT txid_current()" in query:
            self.selected = {"txid_current": 92}
        elif "FROM coordinator_instances" in query:
            self.selected = {"authority": 1} if self.active and params == (self.instance, self.epoch) else None
        elif "FROM job_attempts AS a" in query:
            self.selected = self.attempt
        elif "FROM graph_leases" in query:
            self.selected = self.lease
        elif "UPDATE job_attempts" in query:
            if "supervisor_registration_digest = %s" in query:
                self.attempt["supervisor_registration_digest"] = params[0]
            elif "supervisor_registration_digest = NULL" in query:
                self.attempt["supervisor_registration_digest"] = None
            if "supervisor_registration_consumed = TRUE" in query:
                self.attempt["supervisor_registration_consumed"] = True
            if "publication_state = 'not_started'" in query:
                self.attempt["publication_state"] = "not_started"

    def fetchone(self) -> dict[str, Any] | None:
        return self.selected

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True
