"""Private terminal reconciliation coordination for actual refresh supervision."""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, Protocol, cast

from actual_refresh_event_pump import ActualRefreshEventPump
from actual_refresh_failure_causality import FailureCausalityAuthority
from actual_refresh_terminal import storage_reconciled, terminal_category
from scale11_threshold_evaluator import IncrementalThresholdMonitor
from scale14_active_boundary import ActiveBoundaryError, ActiveBoundaryState
from scale15_terminal_contracts import (
    CleanupState,
    ControlFailure,
    ControlFailureCode,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalControlResult,
    TerminalReadback,
)
from scale16_launch_binding import LaunchBindingError, LaunchBindingState
from scale25_terminal_settlement import (
    TerminalResourceStatus,
    TerminalSettlementAuthority,
)


class _TerminalReconciliationOwner(Protocol):
    """Smallest supervisor surface needed by terminal coordination."""

    _terminal_result: TerminalControlResult | None
    _terminal_settlement: TerminalSettlementAuthority
    _event_pump: ActualRefreshEventPump | None
    _poll_interval_seconds: float
    _phase_sequence: list[str]
    _operation_sequence: list[str]
    _prelaunch_expectation: object | None
    _launch_binding: LaunchBindingState
    _boundaries: ActiveBoundaryState
    _primary_failure: ControlFailureCode | None
    _secondary_failures: list[ControlFailureCode]
    _signal_count: int
    _signal_reason: str | None
    _primary_stop_boundary: str | None
    _last_active_boundary: str | None
    _monitor: IncrementalThresholdMonitor
    _clock_ns: Callable[[], int]
    _cleanup_verifier: Callable[[TerminalReadback], CleanupState]

    def _probe_control_authorities(
        self,
        *,
        probe_resources: bool = True,
    ) -> None: ...

    def _record_control_failure(
        self,
        error: BaseException,
        fallback: ControlFailureCode = ControlFailureCode.RESOURCE_READER_UNAVAILABLE,
    ) -> None: ...

    def _record_failure(
        self,
        code: ControlFailureCode,
        *,
        primary: bool = True,
    ) -> None: ...

    def _record_secondary(self, code: ControlFailureCode) -> None: ...

    def _record_terminal_event_status(self) -> None: ...

    def _settle_event_authority(self) -> None: ...

    def _observe(
        self,
        now_ns: int,
        started_ns: int,
        *,
        terminal: bool,
    ) -> None: ...

    def _resource_error_status(
        self,
        error: BaseException,
        *,
        settlement: bool = False,
    ) -> TerminalResourceStatus: ...

    def _settle_resource_authority(self) -> BaseException | None: ...

    def _reconcile_backends(
        self,
        child_quiescent: bool,
    ) -> tuple[Mapping[str, int], bool]: ...

    def _read_terminal_state(self) -> TerminalReadback | None: ...

    def _causality(self) -> FailureCausalityAuthority: ...


class _ActualRefreshTerminalCoordinator:
    """Sequence terminal authorities without owning supervisor state."""

    def __init__(self, owner: _TerminalReconciliationOwner) -> None:
        self._owner = owner

    def reconcile(
        self,
        exit_code: int | None,
        started_ns: int,
    ) -> TerminalControlResult:
        owner = self._owner
        if owner._terminal_result is not None:
            return owner._terminal_result
        child_quiescent = exit_code is not None
        owner._terminal_settlement.settle_child(exit_code)
        event_eof_observed = False
        if owner._event_pump is not None:
            try:
                if not child_quiescent or not owner._event_pump.wait_done(
                    timeout_seconds=owner._poll_interval_seconds
                ):
                    owner._event_pump.close()
                event_failure = owner._event_pump.take_failure()
                event_eof_observed = isinstance(event_failure, EOFError)
                if event_failure is not None and not event_eof_observed:
                    owner._record_control_failure(
                        event_failure
                        if isinstance(
                            event_failure,
                            (
                                ActiveBoundaryError,
                                ControlFailure,
                                LaunchBindingError,
                            ),
                        )
                        else ControlFailure(
                            ControlFailureCode.EVENT_TRANSPORT_FAILED,
                            cause=event_failure,
                        )
                    )
            except BaseException as error:
                owner._record_control_failure(error)
        if owner._primary_failure is None:
            try:
                owner._probe_control_authorities(probe_resources=False)
            except BaseException as error:
                owner._record_control_failure(error)
        if (
            event_eof_observed
            and owner._primary_failure is None
            and not owner._phase_sequence
        ):
            owner._record_failure(ControlFailureCode.EVENT_TRANSPORT_EOF)
        if (
            child_quiescent
            and exit_code == 0
            and owner._prelaunch_expectation is not None
            and owner._launch_binding.bound_attempt is None
        ):
            owner._record_failure(ControlFailureCode.LAUNCH_AUTHORITY_MISSING)
        if child_quiescent and owner._primary_failure is None:
            if not owner._phase_sequence:
                owner._record_failure(ControlFailureCode.LIFECYCLE_INCOMPLETE)
            else:
                try:
                    owner._boundaries.close()
                except ActiveBoundaryError as error:
                    owner._record_control_failure(error)
        elif child_quiescent:
            if not owner._phase_sequence:
                owner._record_secondary(ControlFailureCode.LIFECYCLE_INCOMPLETE)
            else:
                try:
                    owner._boundaries.close()
                except ActiveBoundaryError:
                    owner._record_secondary(
                        ControlFailureCode.LIFECYCLE_INCOMPLETE
                    )
        if child_quiescent and owner._primary_failure is not None:
            owner._record_terminal_event_status()
        owner._settle_event_authority()
        owner._terminal_settlement.settle_events(True)

        terminal_resource_status = TerminalResourceStatus.SAMPLE_UNAVAILABLE
        if child_quiescent:
            try:
                owner._observe(owner._clock_ns(), started_ns, terminal=True)
                terminal_resource_status = TerminalResourceStatus.AVAILABLE
            except BaseException as error:
                terminal_resource_status = owner._resource_error_status(error)
                owner._record_failure(
                    ControlFailureCode.TERMINAL_RESOURCE_UNAVAILABLE,
                    primary=owner._primary_failure is None,
                )

        resource_error = owner._settle_resource_authority()
        if resource_error is not None:
            terminal_resource_status = owner._resource_error_status(
                resource_error,
                settlement=True,
            )
        owner._terminal_settlement.settle_resources(terminal_resource_status)
        backend_summary, backend_quiescent = owner._reconcile_backends(
            child_quiescent
        )
        owner._terminal_settlement.settle_backends(backend_quiescent)
        readback = owner._read_terminal_state()
        owner._terminal_settlement.settle_readback(readback is not None)
        cleanup_state = CleanupState.UNPROVED
        if readback is not None:
            try:
                cleanup_state = CleanupState(owner._cleanup_verifier(readback))
            except BaseException:
                owner._record_failure(
                    ControlFailureCode.CLEANUP_ELIGIBILITY_UNPROVED,
                    primary=owner._primary_failure is None,
                )
            if cleanup_state is CleanupState.UNPROVED:
                owner._record_failure(
                    ControlFailureCode.CLEANUP_ELIGIBILITY_UNPROVED,
                    primary=owner._primary_failure is None,
                )
        owner._terminal_settlement.settle_cleanup(
            cleanup_state is not CleanupState.UNPROVED
        )
        settled = owner._terminal_settlement.freeze()

        publication_state = (
            PublicationState.UNPROVED
            if readback is None
            else readback.publication_state
        )
        stage_state = (
            StageState.UNPROVED if readback is None else readback.stage_state
        )
        if stage_state not in {
            StageState.PRE_BINDING_RECONCILED,
            StageState.PRE_STAGE_RECONCILED,
            StageState.PUBLISHED_RECONCILED,
            StageState.FAILED_RECONCILED,
        }:
            owner._record_failure(
                ControlFailureCode.STAGE_RECONCILIATION_UNPROVED,
                primary=owner._primary_failure is None,
            )
        reconciled = storage_reconciled(
            settled.child_quiescent,
            settled.backend_quiescent,
            publication_state,
            stage_state,
            cleanup_state,
        )
        reconciliation_status = (
            ReconciliationStatus.RECONCILED
            if reconciled
            else ReconciliationStatus.UNRECONCILED
        )
        failure_projection = owner._causality().freeze().public_projection()
        category = terminal_category(
            exit_code,
            publication_state,
            reconciliation_status,
            owner._primary_failure,
            owner._signal_reason,
        )
        owner._terminal_result = TerminalControlResult(
            category,
            owner._primary_failure,
            tuple(owner._secondary_failures),
            reconciliation_status,
            exit_code,
            owner._signal_count,
            child_quiescent,
            backend_quiescent,
            settled.terminal_resource_available,
            publication_state,
            stage_state,
            cleanup_state,
            owner._primary_stop_boundary or owner._last_active_boundary,
            owner._monitor.finalize(),
            tuple(owner._phase_sequence),
            tuple(owner._operation_sequence),
            backend_summary,
            (
                "uninstrumented"
                if owner._prelaunch_expectation is None
                else owner._launch_binding.public_state
            ),
            (
                "matched"
                if owner._launch_binding.bound_attempt is not None
                and readback is not None
                and publication_state
                not in {
                    PublicationState.LAUNCH_AUTHORITY_MISSING,
                    PublicationState.LAUNCH_ATTEMPT_MISMATCH,
                    PublicationState.LAUNCH_STAGE_MISSING,
                    PublicationState.FOREIGN_STAGE_DETECTED,
                    PublicationState.FOREIGN_PUBLICATION_DETECTED,
                }
                else "mismatch"
                if owner._launch_binding.bound_attempt is not None
                else "unbound"
            ),
            str(failure_projection["order_status"]),
            tuple(
                cast(Iterable[str], failure_projection["categories"])
            ),
        )
        return owner._terminal_result


__all__: list[str] = []
