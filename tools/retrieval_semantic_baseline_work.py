"""Measured correspondence work and transparent artifact-read accounting."""
from __future__ import annotations
from collections.abc import Callable
from time import perf_counter_ns
from typing import Any
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_baseline_capture import IssuedBaselineCapture


class CorrespondenceVerificationFailure(ExperimentRefusal):
    """Fail-closed sidecar refusal retaining measured verification work."""

    def __init__(self, code: str, cost: Any) -> None:
        super().__init__(code)
        self.correspondence_cost = cost


class _CostClock:
    def __init__(self) -> None:
        self.started_ns = perf_counter_ns()
        self.known_artifact_bytes = 0
        self.known_materialized_bytes = 0
        self.carried_ns = 0
    def include_capture(self, capture: IssuedBaselineCapture) -> None:
        self.carried_ns += capture.read_ns
    def sample(self, cost_type: Callable[..., Any], *, failures: int) -> Any:
        return cost_type(
            correspondence_verification_ns=self.carried_ns + max(0, perf_counter_ns() - self.started_ns),
            correspondence_verification_bytes_read=None,
            known_artifact_bytes_read=self.known_artifact_bytes,
            known_materialized_bytes_read=self.known_materialized_bytes,
            correspondence_failures=failures,
        ).validate()


class _MeteredArtifactStore:
    """Count only bytes returned by explicit artifact reads; opaque IO stays unknown."""

    def __init__(self, delegate: Any, clock: _CostClock) -> None:
        self._delegate = delegate
        self._clock = clock

    def read(self, reference: Any, max_bytes: int | None = None) -> bytes:
        raw = self._delegate.read(reference, max_bytes=max_bytes)
        if isinstance(raw, (bytes, bytearray, memoryview)):
            self._clock.known_artifact_bytes += len(raw)
        return raw

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)
