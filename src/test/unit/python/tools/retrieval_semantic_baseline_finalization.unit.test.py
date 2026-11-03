"""Pure finalization boundaries for retained W5 legacy and V2 results."""

from __future__ import annotations

from pathlib import Path
from typing import Any


from repomap_test_support.w5_experiment_results import (
    ResultV2Run,
    finalize_attempt_evidence,
    safe_failure_code,
)
from retrieval_semantic_experiment_contracts import ExperimentRefusal


class _Costs:
    def to_dict(self) -> dict[str, object]:
        return {"failures": 0}


class _Journal:
    def __init__(self, name: str) -> None:
        self.directory = Path(name)
        self.finished: tuple[str, dict[str, object]] | None = None

    def finish(self, status: str, report: dict[str, object]) -> None:
        self.finished = (status, report)


class _RejectingResultV2Run(ResultV2Run):
    def finish(
        self,
        journal: Any,
        *,
        status: str,
        failure_code: str | None = None,
    ) -> None:
        raise ExperimentRefusal("result_completed_cells")


def test_safe_failure_code_keeps_refusal_code_and_hides_exception_names() -> None:
    assert safe_failure_code(
        ExperimentRefusal("controller_admission_required"),
        fallback="attempt_failed",
    ) == "controller_admission_required"
    assert safe_failure_code(
        ExperimentRefusal("CamelCaseFailure"),
        fallback="attempt_failed",
    ) == "attempt_failed"
    assert safe_failure_code(RuntimeError("private detail"), fallback="attempt_failed") == (
        "attempt_failed"
    )


def test_finalizer_preserves_existing_attribution_and_emits_legacy() -> None:
    journal = _Journal("w5-semantic-g1")
    report: dict[str, object] = {
        "status": "failed",
        "generation": 1,
        "failure_type": "ExperimentRefusal",
        "failure_code": "attempt_failed",
    }
    emitted: list[tuple[Any, ...]] = []
    attribution_error = RuntimeError("attribution")
    attribution, v2_errors = finalize_attempt_evidence(
        [(journal, _Costs(), "failed", report)],
        result_v2=ResultV2Run(enabled=False),
        cleanup_status="verified",
        cleanup_error=None,
        attribution_error=attribution_error,
        emit_legacy=lambda paths: emitted.append(paths),
    )
    assert attribution is attribution_error
    assert v2_errors == ()
    assert journal.finished is not None
    assert emitted == [(journal.directory,)]


def test_finalizer_converts_cleanup_only_failure_to_safe_v2_status() -> None:
    journal = _Journal("w5-semantic-g1")
    report: dict[str, object] = {"status": "completed", "generation": 1}
    attribution, v2_errors = finalize_attempt_evidence(
        [(journal, _Costs(), "completed", report)],
        result_v2=ResultV2Run(enabled=False),
        cleanup_status="failed",
        cleanup_error=ExperimentRefusal("cleanup_failed"),
        attribution_error=None,
        emit_legacy=lambda _paths: None,
    )
    assert attribution is None
    assert v2_errors == ()
    assert journal.finished is not None
    assert journal.finished[0] == "failed"
    assert report["failure_code"] == "cleanup_failed"


def test_v2_failure_is_secondary_to_legacy_finalization() -> None:
    journal = _Journal("w5-semantic-g1")
    report: dict[str, object] = {"status": "completed", "generation": 1}
    emitted: list[tuple[Any, ...]] = []
    attribution, v2_errors = finalize_attempt_evidence(
        [(journal, _Costs(), "completed", report)],
        result_v2=_RejectingResultV2Run(enabled=True),
        cleanup_status="verified",
        cleanup_error=None,
        attribution_error=None,
        emit_legacy=lambda paths: emitted.append(paths),
    )
    assert attribution is None
    assert len(v2_errors) == 1
    assert isinstance(v2_errors[0], ExperimentRefusal)
    assert journal.finished is not None
    assert emitted == [(journal.directory,)]
