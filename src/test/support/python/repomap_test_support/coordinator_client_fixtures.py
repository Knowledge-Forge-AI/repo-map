"""Typed coordinator client response doubles and factories."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar


class FakeCoordinatorClient:
    def __init__(
        self,
        statuses: tuple[object, ...] | list[object] = (),
        *,
        cancel_state: object = "cancel_requested",
        health: object | None = None,
    ) -> None:
        self.statuses: Iterator[object] = iter(statuses)
        self.cancel_state = cancel_state
        self.health_payload = health or {
            "health_schema_version": 1,
            "status": "ready",
            "service": {"status": "ready"},
            "ownership": {"status": "owned"},
            "queue": {"status": "not_reported"},
            "workers": {"status": "not_reported"},
            "publication": {"status": "not_reported"},
            "polling": {"status": "not_configured"},
            "transport": {"status": "ready"},
            "storage": {"status": "not_reported"},
        }
        self.calls: list[tuple[object, ...]] = []

    def health(self) -> object:
        self.calls.append(("health",))
        return self.health_payload

    def status(self, job_id: str) -> object:
        self.calls.append(("status", job_id))
        return next(self.statuses)

    def wait(self, job_id: str) -> object:
        self.calls.append(("wait", job_id))
        return next(self.statuses)

    def cancel(self, job_id: str) -> object:
        self.calls.append(("cancel", job_id))
        return {"job_id": job_id, "state": self.cancel_state}

    def list_jobs(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> object:
        self.calls.append(
            ("list", {"limit": limit, "graph_id": graph_id, "cursor": cursor})
        )
        return {
            "jobs": [
                {
                    "job_id": "job-1",
                    "graph_id": "repo-map",
                    "state": "succeeded",
                    "submitted_at": "2026-07-13T12:00:00.000000Z",
                }
            ],
            "next_cursor": None,
        }


class CustomPageClient:
    def __init__(self, page: object) -> None:
        self._page = page

    def list_jobs(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> object:
        del limit, graph_id, cursor
        return self._page


class ItemClient(CustomPageClient):
    def __init__(self, item: object) -> None:
        super().__init__({"jobs": [item], "next_cursor": None})


_ClientFixtureT = TypeVar("_ClientFixtureT")


def fixed_client_factory(
    client: _ClientFixtureT,
) -> Callable[[Path, Path], _ClientFixtureT]:
    def factory(_socket: Path, _token: Path) -> _ClientFixtureT:
        return client

    return factory


