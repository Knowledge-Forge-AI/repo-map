"""Deterministic timeout classification using the real observer session."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg
import pytest

from scale28_backend_observer_session import (
    BackendMonitorError, BackendObserverSession, ObserverFailureBoundary, ObserverSessionState,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY, ObserverDeadlinePolicy


class _StatementTimeoutCanceled(psycopg.errors.QueryCanceled):
    @property
    def diag(self):
        return SimpleNamespace(message_primary="canceling statement due to statement timeout")


@pytest.mark.parametrize('cause,mechanism', [
    (AssertionError('fixture connection type mismatch'), None),
    (psycopg.errors.QueryCanceled('fixture cancellation'), 'unexpected_query_canceled'),
    (_StatementTimeoutCanceled(), 'server_statement_timeout'),
])
def test_immediate_operation_failure_preserves_cause_and_timeout_classification(cause, mechanism):
    connection = Mock(closed=False, broken=False)
    session = BackendObserverSession(
        observer_factory=Mock, connection_factory=lambda _settings=None: connection,
        failure_causality=None, child_released=lambda: True,
        deadline_policy=DEFAULT_OBSERVER_DEADLINE_POLICY,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    timer = Mock()

    def operation(observer, owned_connection):
        assert owned_connection is connection
        raise cause

    try:
        with patch('scale28_backend_observer_session.Timer', return_value=timer):
            with pytest.raises(BackendMonitorError) as caught:
                session.run(ObserverFailureBoundary.ACTIVE_SUMMARY, operation,
                            allowed_states=(ObserverSessionState.ACTIVE,), timeout_seconds=0.5)
        assert caught.value.__cause__ is cause
        actual = caught.value.observer_timeout_mechanism
        assert (actual.value if actual is not None else None) == mechanism
        connection.cancel_safe.assert_not_called()
        timer.cancel.assert_called_once()
    finally:
        session.close()
    connection.close.assert_called_once()
    assert session.snapshot().operation_in_flight is False



def test_decision_support_reserve_preserves_default_deadline_policy():
    default = DEFAULT_OBSERVER_DEADLINE_POLICY
    assert default.server_statement_timeout_ms == 400
    assert default.client_cancel_after_seconds == 0.45
    assert default.caller_operation_timeout_seconds == 0.5
    policy = ObserverDeadlinePolicy(
        connection_timeout_seconds=2, server_statement_timeout_ms=100,
        client_cancel_after_seconds=0.2, cancel_request_timeout_seconds=0.2,
        caller_operation_timeout_seconds=0.5,
    )
    assert policy.server_statement_timeout_ms < policy.client_cancel_after_seconds * 1000
    assert policy.client_cancel_after_seconds + policy.cancel_request_timeout_seconds < policy.caller_operation_timeout_seconds
    assert DEFAULT_OBSERVER_DEADLINE_POLICY is default

