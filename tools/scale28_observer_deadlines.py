"""Private bounded connection and deadline policy for the live observer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
import shlex
from typing import Mapping


class ObserverTimeoutMechanism(str, Enum):
    """Closed private classification for observer timeout mechanisms."""

    SERVER_STATEMENT_TIMEOUT = "server_statement_timeout"
    CLIENT_CANCEL_FALLBACK = "client_cancel_fallback"
    UNEXPECTED_QUERY_CANCELED = "unexpected_query_canceled"


class ObserverOperationClass(str, Enum):
    """Closed authority classes for observer connection work."""

    CONNECTION_STARTUP = "connection_startup"
    SQL_BOUNDED = "sql_bounded"
    SERIALIZATION_ONLY = "serialization_only"
    SETTLEMENT = "settlement"


class ObserverCancellationLimitation(str, Enum):
    """Closed private classification for client-cancellation limitations."""

    CANCELLATION_TIMEOUT = "cancellation_timeout"
    CANCELLATION_FAILURE = "cancellation_failure"


class ObserverCancellationRequestOutcome(str, Enum):
    """Closed private outcome of one exact-connection cancellation request."""

    NOT_REQUESTED = "not_requested"
    REQUEST_SUCCEEDED = "request_succeeded"
    REQUEST_TIMED_OUT = "request_timed_out"
    REQUEST_FAILED = "request_failed"


@dataclass(frozen=True, slots=True)
class ObserverCancellationState:
    """Immutable operation, cancellation, settlement, and close authority."""

    operation_timeout_created: bool = False
    cancellation_requested: bool = False
    request_in_flight: bool = False
    mechanism: ObserverTimeoutMechanism | None = None
    request_outcome: ObserverCancellationRequestOutcome = (
        ObserverCancellationRequestOutcome.NOT_REQUESTED
    )
    operation_settled: bool = True
    settlement_limitation: bool = False
    request_settlement_limitation: bool = False

    @property
    def close_eligible(self) -> bool:
        """Return whether operation and cancellation request both settled."""

        return self.operation_settled and not self.request_in_flight

    def begin_operation(self) -> ObserverCancellationState:
        """Start one operation with no inherited cancellation facts."""

        if self.request_in_flight:
            raise ValueError("observer cancellation request is still active")
        return ObserverCancellationState(operation_settled=False)

    def request(
        self,
        mechanism: ObserverTimeoutMechanism,
    ) -> ObserverCancellationState:
        """Create operation-timeout and cancellation-request authority once."""

        if self.operation_settled:
            raise ValueError("observer cancellation has no active operation")
        if self.cancellation_requested:
            return self
        return replace(
            self,
            operation_timeout_created=True,
            cancellation_requested=True,
            request_in_flight=True,
            mechanism=mechanism,
        )

    def record_request_outcome(
        self,
        outcome: ObserverCancellationRequestOutcome,
    ) -> ObserverCancellationState:
        """Record one idempotent terminal cancellation-request outcome."""

        if (
            not self.cancellation_requested
            or outcome is ObserverCancellationRequestOutcome.NOT_REQUESTED
        ):
            raise ValueError("observer cancellation outcome is invalid")
        if self.request_outcome is outcome:
            return self
        if (
            self.request_outcome
            is not ObserverCancellationRequestOutcome.NOT_REQUESTED
        ):
            raise ValueError("observer cancellation outcome conflicts")
        if not self.request_in_flight:
            raise ValueError("observer cancellation request is not active")
        return replace(
            self,
            request_in_flight=False,
            request_outcome=outcome,
        )

    def settle_operation(self) -> ObserverCancellationState:
        """Record settlement only from the operation-owning path."""

        if self.operation_settled:
            return self
        return replace(self, operation_settled=True)

    def record_settlement_limitation(self) -> ObserverCancellationState:
        """Record that close eligibility was not proved within its budget."""

        if self.operation_settled:
            raise ValueError("observer settlement limitation is invalid")
        if self.settlement_limitation:
            return self
        return replace(self, settlement_limitation=True)

    def record_request_settlement_limitation(
        self,
    ) -> ObserverCancellationState:
        """Record that an active request did not settle within close authority."""

        if not self.request_in_flight:
            raise ValueError("observer request settlement limitation is invalid")
        if self.request_settlement_limitation:
            return self
        return replace(self, request_settlement_limitation=True)


@dataclass(frozen=True, slots=True)
class ObserverDeadlinePolicy:
    """One immutable internal observer deadline hierarchy."""

    connection_timeout_seconds: int = 2
    server_statement_timeout_ms: int = 400
    client_cancel_after_seconds: float = 0.45
    cancel_request_timeout_seconds: float = 0.25
    caller_operation_timeout_seconds: float = 0.5
    cancel_request_max_seconds: float = 0.3
    cancel_request_publication_margin_seconds: float = 0.05
    request_terminal_timeout_seconds: float = 0.3
    operation_settlement_timeout_seconds: float = 0.9
    close_timeout_seconds: float = 1.0
    terminal_readback_timeout_seconds: float = 0.5
    cleanup_timeout_seconds: float = 5.0
    final_release_timeout_seconds: float = 0.6
    final_release_max_seconds: float = 0.65
    minimum_sql_caller_seconds: float | None = None
    final_sample_floor_seconds: float = 0.05

    def __post_init__(self) -> None:
        if self.minimum_sql_caller_seconds is None:
            server_seconds = self.server_statement_timeout_ms / 1_000
            object.__setattr__(
                self,
                "minimum_sql_caller_seconds",
                server_seconds
                + min(
                    0.02,
                    (self.client_cancel_after_seconds - server_seconds) / 2,
                ),
            )
        numeric = (
            self.connection_timeout_seconds,
            self.server_statement_timeout_ms,
            self.client_cancel_after_seconds,
            self.cancel_request_timeout_seconds,
            self.caller_operation_timeout_seconds,
            self.cancel_request_max_seconds,
            self.cancel_request_publication_margin_seconds,
            self.request_terminal_timeout_seconds,
            self.operation_settlement_timeout_seconds,
            self.close_timeout_seconds,
            self.terminal_readback_timeout_seconds,
            self.cleanup_timeout_seconds,
            self.final_release_timeout_seconds,
            self.final_release_max_seconds,
            self.minimum_sql_caller_seconds,
            self.final_sample_floor_seconds,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in numeric
        ):
            raise ValueError("observer deadline policy is invalid")
        server_seconds = self.server_statement_timeout_ms / 1_000
        if not (
            server_seconds
            < self.client_cancel_after_seconds
            < self.caller_operation_timeout_seconds
        ):
            raise ValueError("observer deadline hierarchy is invalid")
        if self.cancel_request_timeout_seconds > self.cancel_request_max_seconds:
            raise ValueError("observer cancellation reserve is invalid")
        if (
            self.cancel_request_timeout_seconds
            + self.cancel_request_publication_margin_seconds
            > self.request_terminal_timeout_seconds
        ):
            raise ValueError("observer request terminal deadline is invalid")
        assert self.minimum_sql_caller_seconds is not None
        if not (
            server_seconds < self.minimum_sql_caller_seconds
            <= self.client_cancel_after_seconds
        ):
            raise ValueError("observer SQL admission floor is invalid")
        if not (
            self.final_release_timeout_seconds
            <= self.final_release_max_seconds
            and self.final_sample_floor_seconds
            < self.final_release_timeout_seconds
        ):
            raise ValueError("observer final release deadline is invalid")
        if self.connection_timeout_seconds < 2:
            raise ValueError("observer connection timeout is invalid")

    def operation_deadlines(self, caller_seconds: float) -> tuple[float, float]:
        """Return the client trigger and cancellation reserve for one caller."""

        if (
            isinstance(caller_seconds, bool)
            or not isinstance(caller_seconds, (int, float))
            or not math.isfinite(caller_seconds)
            or caller_seconds <= 0
        ):
            raise ValueError("observer operation timeout is invalid")
        assert self.minimum_sql_caller_seconds is not None
        if caller_seconds < self.minimum_sql_caller_seconds:
            raise ValueError("observer SQL authority is insufficient")
        return (
            min(caller_seconds, self.client_cancel_after_seconds),
            self.cancel_request_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ObserverConnectionSettings:
    """Validated one-endpoint libpq startup settings."""

    connect_timeout_seconds: int
    statement_timeout_ms: int

    @classmethod
    def from_policy(
        cls,
        policy: ObserverDeadlinePolicy,
    ) -> ObserverConnectionSettings:
        return cls(
            policy.connection_timeout_seconds,
            policy.server_statement_timeout_ms,
        )

    def __post_init__(self) -> None:
        if (
            isinstance(self.connect_timeout_seconds, bool)
            or not isinstance(self.connect_timeout_seconds, int)
            or self.connect_timeout_seconds < 2
            or isinstance(self.statement_timeout_ms, bool)
            or not isinstance(self.statement_timeout_ms, int)
            or self.statement_timeout_ms < 1
        ):
            raise ValueError("observer connection settings are invalid")

    def apply(self, parameters: Mapping[str, object]) -> dict[str, object]:
        """Return detached parameters with one exact bounded startup policy."""

        if not isinstance(parameters, Mapping):
            raise ValueError("observer connection parameters are invalid")
        result = dict(parameters)
        self._validate_endpoint(result)
        existing_timeout = result.get("connect_timeout")
        if existing_timeout is not None and str(existing_timeout) != str(
            self.connect_timeout_seconds
        ):
            raise ValueError("observer connect_timeout conflicts with policy")
        result["connect_timeout"] = self.connect_timeout_seconds
        options = result.get("options", "")
        if not isinstance(options, str):
            raise ValueError("observer connection options are invalid")
        try:
            tokens = shlex.split(options)
        except ValueError as error:
            raise ValueError("observer connection options are invalid") from error
        if any("statement_timeout" in token.lower() for token in tokens):
            raise ValueError("observer statement_timeout conflicts with policy")
        timeout_option = f"-c statement_timeout={self.statement_timeout_ms}ms"
        result["options"] = " ".join(part for part in (options, timeout_option) if part)
        return result

    @staticmethod
    def _validate_endpoint(parameters: Mapping[str, object]) -> None:
        for field in ("host", "hostaddr", "port"):
            value = parameters.get(field)
            if isinstance(value, (list, tuple)):
                if len(value) != 1:
                    raise ValueError("observer connection requires exactly one host")
                value = value[0]
            if isinstance(value, str) and "," in value:
                raise ValueError("observer connection requires exactly one host")


DEFAULT_OBSERVER_DEADLINE_POLICY = ObserverDeadlinePolicy()


__all__ = [
    "DEFAULT_OBSERVER_DEADLINE_POLICY",
    "ObserverCancellationLimitation",
    "ObserverConnectionSettings",
    "ObserverDeadlinePolicy",
    "ObserverOperationClass",
    "ObserverTimeoutMechanism",
]
