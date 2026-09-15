"""Public compatibility facade for observer trace evidence models."""

from repomap_test_support.observer_trace_validation import (
    ObserverOperationTrace,
    ObserverTraceEvent,
    ObserverTraceSnapshot,
)
from repomap_test_support.observer_trace_models import (
    TerminalCounts,
    reconcile_terminal_counts,
)
from repomap_test_support import observer_trace_vocabulary as _vocabulary

ObserverCaller = _vocabulary.ObserverCaller
ObserverTraceEvidenceError = _vocabulary.ObserverTraceEvidenceError
ObserverTraceKind = _vocabulary.ObserverTraceKind
_LINKED_OPERATION_KINDS = _vocabulary._LINKED_OPERATION_KINDS
_PORT_TOKEN_PATTERN = _vocabulary._PORT_TOKEN_PATTERN
_SAFE_BOUNDARIES = _vocabulary._SAFE_BOUNDARIES
_SAFE_DETAILS = _vocabulary._SAFE_DETAILS
_SAFE_OPERATION_CLASSES = _vocabulary._SAFE_OPERATION_CLASSES
_SAFE_SESSION_STATES = _vocabulary._SAFE_SESSION_STATES
_TOKEN_PATTERN = _vocabulary._TOKEN_PATTERN

__all__ = [
    "ObserverCaller",
    "ObserverOperationTrace",
    "ObserverTraceEvent",
    "ObserverTraceEvidenceError",
    "ObserverTraceKind",
    "ObserverTraceSnapshot",
    "TerminalCounts",
    "reconcile_terminal_counts",
]
