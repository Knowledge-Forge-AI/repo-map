"""One allocating-run owner for admission, quotas, teardown, and close evidence."""

from __future__ import annotations

import os
import secrets as secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from repomap_test_support.resource_admission import (
    HostSignals,
    collect_host_signals as collect_host_signals,
    decide_host_admission as decide_host_admission,
)
from repomap_test_support.resource_hygiene_policy import (
    HygieneConfig,
    HygieneProfile,
    QuotaEvent,
    QuotaExceeded,
    QuotaTracker,
)
from repomap_test_support.resource_index import (
    AdvisoryIndex, AdmissionRecordedError as AdmissionRecordedError,
    HostAdmissionRefused as HostAdmissionRefused,
)
from repomap_test_support.resource_interruption import (
    InterruptionOutcome,
    classify_interruption,
    operator_marker_path,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    lifecycle_claim,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity as RunIdentity
from repomap_test_support.resource_ledger_io import (
    write_private_json as write_private_json,
)
from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_run_admission import admit_resource_run
from repomap_test_support.resource_run_cleanup import (
    cleanup_unadmitted_layout, abort_admitted_start as abort_admitted_start,
    process_start_evidence as process_start_evidence,
)
from repomap_test_support.resource_scratch import ScratchMeasurement, ScratchRunOwner
from repomap_test_support.test_scratch import TestScratchLayout


ENV_RESOURCE_LEDGER = "REPOMAP_TEST_RESOURCE_LEDGER"
_ACTIVE_RESOURCE_RUN: "TestResourceRun | None" = None


def active_resource_run() -> "TestResourceRun | None":
    """Return the in-process managed owner used by pytest support producers."""
    return _ACTIVE_RESOURCE_RUN


class ResourceRunError(RuntimeError):
    """The allocating run could not be admitted, measured, or closed exactly."""


class TestResourceRun:
    """Coordinates one owner; inherited borrowers never compete for lifecycle."""

    __test__ = False

    def __init__(
        self,
        layout: TestScratchLayout,
        ledger: ResourceLedger,
        scratch: ScratchRunOwner,
        index: AdvisoryIndex,
        profile: HygieneProfile,
        config: HygieneConfig,
        admission_owner_token: str,
        quota_override: tuple[int, int] | None = None,
    ) -> None:
        self.layout = layout
        self.ledger = ledger
        self.scratch = scratch
        self.index = index
        self.profile = profile
        self.config = config
        self.admission_owner_token = admission_owner_token
        self._closed = False
        self._quota_measurement: ScratchMeasurement | None = None
        self._quota_terminal = False
        self._quota_event_recorded = False
        self._interruption = InterruptionOutcome.NO_INTERRUPTION
        self._quota = QuotaTracker(
            profile,
            self._record_quota_event,
            quota=quota_override,
        )

    @property
    def run_root(self) -> Path:
        return self.layout.run_root

    @property
    def run_id(self) -> str:
        return self.layout.run_root.name

    @classmethod
    def start(
        cls,
        layout: TestScratchLayout,
        *,
        profile: HygieneProfile = HygieneProfile.ORDINARY,
        config: HygieneConfig | None = None,
        host_signals: HostSignals | None = None,
        now_seconds: int | None = None,
        quota_override: tuple[int, int] | None = None,
        operator_attested_exclusive: bool = False,
        operator_attested_pressure_degradation: bool = False,
        campaign_plan_id: str | None = None,
        declared_complete_gates: int = 0,
    ) -> TestResourceRun | None:
        return admit_resource_run(
            cls,
            layout,
            profile=profile,
            config=config,
            host_signals=host_signals,
            now_seconds=now_seconds,
            quota_override=quota_override,
            operator_attested_exclusive=operator_attested_exclusive,
            operator_attested_pressure_degradation=operator_attested_pressure_degradation,
            campaign_plan_id=campaign_plan_id,
            declared_complete_gates=declared_complete_gates,
        )

    @property
    def quota_exceeded(self) -> bool:
        return self._quota_terminal

    @contextmanager
    def bounded_subprocess(self, label: str) -> Iterator[None]:
        self.checkpoint(f"before_{label}")
        try:
            yield
        except (Exception, KeyboardInterrupt, SystemExit) as primary:
            try:
                self.checkpoint(f"after_{label}")
            except Exception:
                primary.add_note("secondary resource checkpoint failed")
            raise
        else:
            self.checkpoint(f"after_{label}")

    def checkpoint(self, label: str, *, check_capacity: bool = True) -> ScratchMeasurement:
        measurement = self.scratch.checkpoint(label)
        measurement = self._apply_quota(label, measurement)
        from test_sandbox import active_sandbox

        if check_capacity and active_sandbox():
            from test_sandbox_capacity import validate_scratch_capacity

            validate_scratch_capacity()
        return measurement

    def retain_evidence(self, path: Path, *, reason: str) -> None:
        if reason == "report_source":
            with lifecycle_claim(
                self.layout.scratch_root,
                self.layout.project,
                self.layout.run_root.name,
                ClaimPurpose.REPORT_SOURCE_REGISTRATION,
            ):
                self.scratch.retain(path, reason=reason)
            return
        self.scratch.retain(path, reason=reason)

    def close(
        self,
        outcome: TerminalOutcome = TerminalOutcome.PASSED,
        *,
        now_seconds: int | None = None,
    ) -> dict[str, int | bool | str]:
        if self._closed:
            raise ResourceRunError("test resource run is already closed")
        marker = operator_marker_path(
            self.layout.scratch_root,
            project=self.layout.project,
            run_id=self.layout.run_root.name,
        )
        if marker.exists() or marker.is_symlink():
            self.observe_state_change()
        try:
            self._closing_checkpoint("before_cleanup")
            self.scratch.cleanup_transient(record_boundaries=False)
            self._closing_checkpoint("after_cleanup")
            self.ledger.assert_current_run_teardown()
            self._closing_checkpoint("close")
        except RuntimeError as error:
            raise ResourceRunError("current_run_cleanup_failed") from error
        if self._interruption is InterruptionOutcome.OPERATOR_INTERRUPTED:
            terminal_outcome = TerminalOutcome.OPERATOR_INTERRUPTED
        elif self._interruption is InterruptionOutcome.EXTERNAL_UNATTRIBUTED_MUTATION:
            terminal_outcome = TerminalOutcome.EXTERNAL_UNATTRIBUTED_MUTATION
        else:
            terminal_outcome = (
                TerminalOutcome.QUOTA_EXCEEDED if self._quota_terminal else outcome
            )
        now = int(time.time()) if now_seconds is None else now_seconds
        lifecycle = self.ledger.stamp_terminal(
            terminal_outcome,
            now,
            report_source_pending=self.ledger.has_report_source(),
        )
        scratch_projection = self.scratch.final_projection()
        self.index.close(
            run_id=self.layout.run_root.name,
            phase=self.layout.phase,
            terminal_outcome=terminal_outcome,
            allocated_bytes=scratch_projection["scratch_retained_bytes"],
            inode_count=scratch_projection["scratch_retained_inodes"],
            retained_evidence_bytes=scratch_projection["scratch_retained_bytes"],
            retention_class=lifecycle.retention_class.value,
            closed_at_seconds=now,
            owner_token=self.admission_owner_token,
        )
        projection = self.ledger.public_projection()
        projection.update(scratch_projection)
        projection["current_run_teardown_complete"] = True
        projection["host_restoration_proved"] = self.ledger.host_restoration_proved()
        projection["terminal_outcome"] = terminal_outcome.value
        projection["retention_class"] = lifecycle.retention_class.value
        projection["current_run_cleanup_outcome"] = "cleanup_complete"
        projection["retained_evidence_outcome"] = "evidence_retained"
        self._closed = True
        global _ACTIVE_RESOURCE_RUN
        if _ACTIVE_RESOURCE_RUN is self:
            _ACTIVE_RESOURCE_RUN = None
        if os.environ.get(ENV_RESOURCE_LEDGER) == str(self.ledger.path):
            os.environ.pop(ENV_RESOURCE_LEDGER, None)
        return projection

    def observe_state_change(self) -> InterruptionOutcome:
        marker = operator_marker_path(
            self.layout.scratch_root,
            project=self.layout.project,
            run_id=self.layout.run_root.name,
        )
        self._interruption = classify_interruption(
            marker,
            project=self.layout.project,
            phase=self.layout.phase,
            run_id=self.layout.run_root.name,
            state_changed=True,
        )
        return self._interruption

    def _closing_checkpoint(self, label: str) -> None:
        try:
            self.checkpoint(label, check_capacity=False)
        except QuotaExceeded:
            self._quota_terminal = True

    def _apply_quota(
        self, label: str, measurement: ScratchMeasurement
    ) -> ScratchMeasurement:
        self._quota_measurement = measurement
        self._quota_event_recorded = False
        try:
            self._quota.checkpoint(
                label,
                allocated_bytes=measurement.allocated_bytes,
                inode_count=measurement.inode_count,
            )
            if self._quota_event_recorded:
                measurement = self.scratch.measure_current()
                self._quota_measurement = measurement
                self._quota.checkpoint(
                    f"{label}_event_evidence",
                    allocated_bytes=measurement.allocated_bytes,
                    inode_count=measurement.inode_count,
                )
        except QuotaExceeded:
            self._quota_terminal = True
            raise
        finally:
            self._quota_measurement = None
        return measurement

    def _record_quota_event(self, event: QuotaEvent) -> None:
        measurement = self._quota_measurement
        if measurement is None:
            raise ResourceRunError("quota event lacks an exact scratch measurement")
        self._quota_event_recorded = True
        self.ledger.add_checkpoint(
            f"{event.category}_{event.label}"[:64],
            {
                "allocated_bytes": measurement.allocated_bytes,
                "apparent_bytes": measurement.apparent_bytes,
                "inode_count": measurement.inode_count,
                "retained_evidence_bytes": measurement.retained_allocated_bytes,
                "largest_owned_subtree_category": measurement.largest_subtree_category,
                "unsafe_link_count": measurement.unsafe_link_count,
            },
        )




__all__ = [
    "ENV_RESOURCE_LEDGER",
    "active_resource_run",
    "ResourceRunError",
    "TestResourceRun",
    "cleanup_unadmitted_layout",
]
