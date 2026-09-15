from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg


ConnectionFactory = Callable[[], psycopg.Connection[Any]]


class ControlSchemaError(RuntimeError):
    """The dedicated control database does not match the supported schema."""


class ControlStoreError(RuntimeError):
    """A bounded control-store operation failed."""


class SingletonActiveError(RuntimeError):
    """Another coordinator still owns the live singleton lease."""


@dataclass(frozen=True)
class SubmissionResult:
    job_id: str
    state: str
    replayed: bool


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    graph_id: str
    attempt: int
    instance_id: str
    fencing_epoch: int
    priority_class: str = "automatic"
    source_generation: str = "sg1:synthetic"
    config_generation: str = "cg1:synthetic"
    extractor_generation: str = "eg1:synthetic"
    canonicalizer_generation: str = "kg1:synthetic"
    graph_lease_fencing_epoch: int = 0


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    graph_id: str
    state: str
    attempt: int
    publication_state: str
    phase: str
    completed: int
    total: int | None
    error_category: str | None


@dataclass(frozen=True)
class JobListItem:
    job_id: str
    graph_id: str
    state: str
    submitted_at: str


@dataclass(frozen=True)
class JobListPage:
    jobs: tuple[JobListItem, ...]
    next_cursor: str | None
