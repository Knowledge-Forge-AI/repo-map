"""Closed test-owned conformance command syntax for measured portable launches."""

from __future__ import annotations

import re

from runner_coverage_capability import CapabilityValidationError

CONFORMANCE_COMMAND = ("-m", "repomap_test_support.portable_worker_conformance")
_KINDS = frozenset({
    "authority", "failure", "receipt", "receipt-cancel", "cancel", "crash",
    "heartbeat-failure", "terminal-validation", "progress-failure", "parent-wait",
    "identity-start",
})


def validate_conformance_arguments(arguments: tuple[str, ...]) -> None:
    """Accept the test-owned launch shape; product parsing owns case semantics."""
    args = list(arguments)
    if len(args) < 8 or args.pop(0) != "--case":
        raise CapabilityValidationError("invalid conformance case arguments")
    case = args.pop(0)
    if (not re.fullmatch(r"[a-z_-]+(?::[a-z_-]+)?", case)
            or case.partition(":")[0] not in _KINDS):
        raise CapabilityValidationError("invalid conformance case identity")
    if args and args[0] == "--probe-path":
        if len(args) < 2 or not args[1] or args[1].startswith("--"):
            raise CapabilityValidationError("invalid conformance probe arguments")
        del args[:2]
    if (len(args) != 6 or args[::2] != ["--capability", "--job-id", "--attempt"]
            or not all(args[1::2]) or not args[-1].isdigit()):
        raise CapabilityValidationError("invalid conformance worker arguments")
