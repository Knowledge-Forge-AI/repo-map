"""Measured usage-child observer and strict native settlement bridge."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

from common_lore_index.coordinator._usage_observation import UsageSettlement
from runner_coverage_capability import CapabilityValidationError


@dataclass(frozen=True, slots=True)
class UsageObservation:
    """Detached launch/settlement facts received from native supervision."""

    pid: int
    returncode: int | None
    waited: bool
    process_group_cleaned: bool
    readers_closed: bool
    streams_closed: bool
    proven: bool


class MeasuredUsageObserver:
    """Notification-only observer; it never receives or controls a process."""

    def __init__(
        self, *, session: Any, capability: Any, token: str, environment: Mapping[str, str],
        identity: Mapping[str, object], job_context: Mapping[str, object] | None,
    ) -> None:
        self.session = session
        self.capability = capability
        self.token = token
        self.environment = dict(environment)
        self.identity = identity
        self.job_context = job_context or {}
        self.pid: int | None = None
        self.facts: UsageObservation | None = None

    def launched(self, pid: int) -> None:
        if self.pid is not None or type(pid) is not int or pid <= 0:
            raise CapabilityValidationError("usage child launch identity is missing or duplicated")
        self.pid = pid
        self.capability.launched_pids[self.token] = pid
        observer = getattr(self.session, "process_observer", None)
        if observer is None:
            raise CapabilityValidationError("measured usage requires active process observer")
        launch_argv = self.job_context.get("argv")
        if not isinstance(launch_argv, (tuple, list)):
            launch_argv = self.job_context.get("launch_argv")
        if not isinstance(launch_argv, (tuple, list)):
            raise CapabilityValidationError("measured usage launch argv is unavailable")
        observer.observe_launch(
            host_pid=pid,
            inner_pid=None,
            pid_namespace_relation="shared",
            invocation_id=self.capability.invocation_id,
            argv=tuple(launch_argv),
            env=self.environment,
            ppid=os.getpid(),
            executable_family="portable_worker",
            test_owner=self.environment.get("COVERAGE_CHILD_TEST_OWNER"),
            capability=self.session.bootstrap_capability,
        )

    def settled(self, facts: Any) -> None:
        if self.pid is None or self.facts is not None:
            raise CapabilityValidationError("usage child settlement is missing or duplicated")
        if type(facts) is not UsageSettlement:
            raise CapabilityValidationError("usage child settlement has an unknown type")
        if (facts.pid != self.pid or type(facts.pid) is not int
                or type(facts.returncode) is not int
                or any(type(getattr(facts, name)) is not bool for name in (
                    "waited", "process_group_cleaned", "readers_closed", "streams_closed", "proven"))):
            raise CapabilityValidationError("usage child settlement facts are invalid")
        self.facts = UsageObservation(
            pid=facts.pid,
            returncode=facts.returncode,
            waited=bool(facts.waited),
            process_group_cleaned=bool(facts.process_group_cleaned),
            readers_closed=bool(facts.readers_closed),
            streams_closed=bool(facts.streams_closed),
            proven=bool(facts.proven),
        )


def require_usage_settlement(observer: MeasuredUsageObserver, result: Any) -> None:
    """Fail closed when native ownership did not return complete facts."""
    facts = observer.facts
    if (facts is None or type(facts.returncode) is not int or not facts.proven
            or not facts.waited or not facts.process_group_cleaned):
        raise CapabilityValidationError("measured usage settlement is incomplete")
    if not facts.readers_closed or not facts.streams_closed:
        raise CapabilityValidationError("measured usage streams are not settled")
    if result is None:
        raise CapabilityValidationError("measured usage result is not synchronously reaped")
    result_returncode = getattr(result, "returncode", None)
    result_waited = getattr(result, "waited", None)
    result_group_cleaned = getattr(result, "process_group_cleaned", None)
    if (type(result_returncode) is not int or result_returncode != facts.returncode
            or type(result_waited) is not bool or result_waited is not True
            or type(result_group_cleaned) is not bool or result_group_cleaned is not True):
        raise CapabilityValidationError("measured usage result is not synchronously reaped")


def make_registered_launch(
    *, launcher: Any, capability: Any, token: str, session: Any,
    environment: Mapping[str, str], job_context: Mapping[str, object] | None,
    identity: Mapping[str, object],
    wrapper: Any,
) -> Any:
    """Build the incumbent non-usage launch callback without changing its contract."""
    def registered_launch(*args: Any, **kwargs: Any) -> Any:
        process = launcher(*args, **kwargs)
        capability.launched_pids[token] = process.pid
        observer = session.process_observer
        if observer is None:
            raise RuntimeError("scoped_portable_coverage_adapter requires active session.process_observer")
        launch_argv = args[0] if args else kwargs.get("argv")
        launch_env = kwargs.get("environment") or environment
        inner_pid = kwargs.get("inner_pid")
        pid_relation = "translated" if kwargs.get("is_container_namespace", False) else kwargs.get("pid_namespace_relation", "shared")
        inv_id = job_context.get("invocation_id") if isinstance(job_context, dict) else environment.get("COVERAGE_SESSION_INVOCATION_ID")
        owner_val = getattr(identity, "worker_id", None) or environment.get("COVERAGE_CHILD_TEST_OWNER")
        observer.observe_launch(
            host_pid=process.pid, inner_pid=inner_pid, pid_namespace_relation=pid_relation,
            invocation_id=inv_id, argv=launch_argv, env=launch_env, ppid=os.getpid(),
            executable_family="portable_worker", test_owner=owner_val, capability=session.bootstrap_capability,
        )
        return wrapper(process, token, capability.child_manifest_dir)
    return registered_launch


__all__ = ("MeasuredUsageObserver", "UsageObservation", "require_usage_settlement")
