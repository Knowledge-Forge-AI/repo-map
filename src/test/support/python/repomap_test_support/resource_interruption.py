"""Closed operator-interruption versus unattributed-mutation classification."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from repomap_test_support.resource_ledger_io import PrivateJsonError, read_private_json
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_bool,
    exact_object,
    nonnegative_int,
)


MARKER_SCHEMA = "repomap-test-operator-interruption-v1"


class InterruptionOutcome(str, Enum):
    NO_INTERRUPTION = "no_interruption"
    OPERATOR_INTERRUPTED = "operator_interrupted"
    EXTERNAL_UNATTRIBUTED_MUTATION = "external_unattributed_mutation"


def operator_marker_path(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
) -> Path:
    project = bounded_string(project, "project")
    run_id = bounded_string(run_id, "run id")
    if any(token in value for value in (project, run_id) for token in ("/", "\\")):
        raise HygieneValidationError("unsafe operator marker identity")
    return Path(scratch_root) / ".operator-reclamation" / project / f"{run_id}.json"


def classify_interruption(
    marker_path: Path,
    *,
    project: str,
    phase: str,
    run_id: str,
    state_changed: bool,
) -> InterruptionOutcome:
    exact_bool(state_changed, "state_changed")
    if not state_changed:
        return InterruptionOutcome.NO_INTERRUPTION
    try:
        payload = exact_object(
            read_private_json(marker_path),
            {
                "schema",
                "project",
                "phase",
                "run_id",
                "operator_attributed",
                "observed_at_seconds",
            },
            "operator interruption marker",
        )
        if payload["schema"] != MARKER_SCHEMA:
            raise HygieneValidationError("unsupported interruption marker schema")
        marker_identity = (
            bounded_string(payload["project"], "project"),
            bounded_string(payload["phase"], "phase"),
            bounded_string(payload["run_id"], "run id"),
        )
        exact_bool(payload["operator_attributed"], "operator_attributed")
        nonnegative_int(payload["observed_at_seconds"], "observed timestamp")
    except (PrivateJsonError, HygieneValidationError, OSError):
        return InterruptionOutcome.EXTERNAL_UNATTRIBUTED_MUTATION
    if marker_identity != (project, phase, run_id) or not payload["operator_attributed"]:
        return InterruptionOutcome.EXTERNAL_UNATTRIBUTED_MUTATION
    return InterruptionOutcome.OPERATOR_INTERRUPTED


__all__ = [
    "InterruptionOutcome",
    "classify_interruption",
    "operator_marker_path",
]
