"""Typed event and variant values for the FIX11 trace authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

class TraceContractError(ValueError):
    """One closed FIX11 trace-contract violation."""


class ClockDomain(StrEnum):
    PARENT_MONOTONIC = "parent_monotonic"
    WORKER_LOCAL_DURATION = "worker_local_duration"


class TraceVariant(StrEnum):
    SUCCESSFUL_ATTEMPT = "successful_attempt"
    SOURCE_RESOURCE_FAILURE = "source_resource_failure"
    PREPARATION_TIMEOUT = "preparation_timeout"
    OBSERVATION_TRANSPORT_FAILURE = "observation_transport_failure"
    ACKNOWLEDGEMENT_FAILURE = "acknowledgement_failure"
    RECEIPT_FAILURE = "receipt_failure"
    PROCESS_SETTLEMENT_FAILURE = "process_settlement_failure"
    CLEANUP_LIMITATION = "cleanup_limitation"
    TWO_ATTEMPT_SUCCESS = "two_attempt_success"
    TWO_ATTEMPT_TERMINAL_FAILURE = "two_attempt_terminal_failure"


class TerminalCategory(StrEnum):
    SUCCESS = "success"
    RESOURCE_READER_UNAVAILABLE = "resource_reader_unavailable"
    PREPARATION_TIMEOUT = "preparation_timeout"
    OBSERVATION_FAILURE = "observation_failure"
    ACKNOWLEDGEMENT_FAILURE = "acknowledgement_failure"
    RECEIPT_FAILURE = "receipt_failure"
    PROCESS_SETTLEMENT_FAILURE = "process_settlement_failure"
    CLEANUP_LIMITATION = "cleanup_limitation"


class CleanupState(StrEnum):
    COMPLETED = "completed"
    LIMITED = "limited"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event: str
    attempt: int
    sequence: int
    clock_domain: ClockDomain


@dataclass(frozen=True, slots=True)
class VariantContract:
    required_by_attempt: Mapping[int, frozenset[str]]
    prohibited_events: frozenset[str]
    ordering_edges: tuple[tuple[str, str], ...]
    allowed_categories_by_attempt: Mapping[int, frozenset[TerminalCategory]]
    cleanup_by_attempt: Mapping[int, CleanupState]
    attempt_two_permitted: bool


