"""Test-owned prelaunch configuration and observed abrupt lifecycle evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import sys
import time
from typing import Any, ClassVar
from uuid import uuid4

from runner_integration_obligations import find_declaration


@dataclass
class AbruptLaunch:
    context: Any
    declaration: Any
    launch_id: str
    process: Any = None
    pid: int | None = None
    started_ns: int | None = None
    checkpoint: str | None = None

    def launched(self, process: Any) -> Any:
        if self.process is not None or type(process.pid) is not int or process.pid <= 0:
            raise RuntimeError("abrupt launch identity is missing or duplicated")
        self.process = process
        self.pid = process.pid
        self.started_ns = time.monotonic_ns()
        return process

    def observed_checkpoint(self, value: str) -> None:
        if self.process is None or value != self.declaration.checkpoint:
            raise RuntimeError("abrupt child checkpoint mismatch")
        self.checkpoint = value

    def settle(self, returncode: int | None, *, cleanup: bool) -> dict[str, Any]:
        self.context.verify_source()
        if (self.process is None or self.checkpoint is None
                or type(returncode) is not int
                or returncode != self.declaration.expected_returncode or cleanup is not True):
            raise RuntimeError("abrupt behavior or cleanup is unproved")
        record = {
            "nodeid": self.declaration.nodeid, "role": self.declaration.role,
            "invocation_id": self.context.invocation_id,
            "source_sha256": self.context.source_sha256, "launch_id": self.launch_id,
            "pid": self.pid, "parent_pid": os.getpid(), "started_ns": self.started_ns,
            "checkpoint": self.checkpoint, "returncode": returncode,
            "settled_ns": time.monotonic_ns(), "cleanup": cleanup,
            "measurement": "unavailable",
        }
        if self.declaration.nodeid in self.context.records:
            raise RuntimeError("abrupt role executed twice")
        self.context.records[self.declaration.nodeid] = record
        return record


@dataclass
class UsageAbruptLaunch:
    """Observer-only evidence for a declared usage helper termination.

    The native owner supplies only a PID and immutable settlement facts. No
    process object, factory, wait, poll, reap or signal capability crosses
    this test-owned boundary.
    """

    context: Any
    declaration: Any
    launch_id: str
    pid: int | None = None
    started_ns: int | None = None
    checkpoint: str | None = None
    settlement: Any = None

    def launched(self, pid: int) -> None:
        if self.pid is not None or type(pid) is not int or pid <= 0:
            raise RuntimeError("usage abrupt launch identity is missing or duplicated")
        self.pid = pid
        self.started_ns = time.monotonic_ns()

    def observed_checkpoint(self, value: str, pid: int | None = None) -> None:
        if self.pid is None or (
                pid is not None and (type(pid) is not int or pid != self.pid)):
            raise RuntimeError("usage abrupt checkpoint PID mismatch")
        if value != self.declaration.checkpoint:
            raise RuntimeError("usage abrupt child checkpoint mismatch")
        self.checkpoint = value

    def settled(self, facts: Any) -> None:
        """Accept only real native facts, never a test expectation."""
        self._validate_settlement(facts)
        if self.settlement is not None:
            raise RuntimeError("usage abrupt native settlement is unproved")
        self.settlement = facts

    def _validate_settlement(self, facts: Any) -> None:
        from common_lore_index.coordinator._usage_observation import UsageSettlement
        if type(facts) is not UsageSettlement:
            raise RuntimeError("usage abrupt settlement must be immutable native facts")
        statuses = ("waited", "process_group_cleaned", "readers_closed", "streams_closed", "proven")
        if (self.pid is None or type(facts.pid) is not int or facts.pid <= 0
                or facts.pid != self.pid or type(facts.returncode) is not int
                or facts.returncode != self.declaration.expected_returncode
                or any(type(getattr(facts, field)) is not bool
                       or getattr(facts, field) is not True for field in statuses)):
            raise RuntimeError("usage abrupt native settlement is unproved")

    def record(self) -> dict[str, Any]:
        self.context.verify_source()
        if self.pid is None or self.started_ns is None or self.checkpoint is None:
            raise RuntimeError("usage abrupt evidence is incomplete")
        if self.settlement is None:
            raise RuntimeError("usage abrupt settlement is missing")
        self._validate_settlement(self.settlement)
        returncode = self.settlement.returncode
        if self.declaration.nodeid in self.context.records:
            raise RuntimeError("abrupt role executed twice")
        record = {
            "nodeid": self.declaration.nodeid, "role": self.declaration.role,
            "invocation_id": self.context.invocation_id,
            "source_sha256": self.context.source_sha256, "launch_id": self.launch_id,
            "pid": self.pid, "parent_pid": os.getpid(), "started_ns": self.started_ns,
            "checkpoint": self.checkpoint, "returncode": returncode,
            "settled_ns": time.monotonic_ns(), "cleanup": True,
            "measurement": "unavailable",
        }
        self.context.records[self.declaration.nodeid] = record
        return record


class AbruptRunnerContext:
    """Object authority selected by the sealed A plugin, never an ambient flag."""

    _CURRENT: ClassVar[AbruptRunnerContext | None] = None

    def __init__(self, *, nodeids, invocation_id, source_sha256, verify_source,
                 declarations=None):
        from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
        self.nodeids = tuple(nodeids)
        self.invocation_id = invocation_id
        self.source_sha256 = source_sha256
        self.verify_source = verify_source
        self.declarations = tuple(declarations or MAINTAINED_ABRUPT_DECLARATIONS)
        self.records: dict[str, dict[str, Any]] = {}
        self.launches: dict[str, AbruptLaunch | UsageAbruptLaunch] = {}
        self.nodeid: str | None = None
        self.session: Any = None

    def select_test(self, nodeid: str) -> None:
        if nodeid not in self.nodeids:
            raise RuntimeError("undeclared A test execution")
        self.nodeid = nodeid

    def begin(self, role: str) -> AbruptLaunch:
        declaration = find_declaration(self.nodeid, self.declarations)
        if declaration is None or declaration.role != role or self.nodeid in self.launches:
            raise RuntimeError("undeclared or repeated abrupt launch")
        self.verify_source()
        launch = AbruptLaunch(self, declaration, uuid4().hex)
        self.launches[declaration.nodeid] = launch
        return launch

    def begin_usage(self, role: str, case: str) -> UsageAbruptLaunch:
        declaration = find_declaration(self.nodeid, self.declarations)
        if (declaration is None or declaration.role != role
                or self.nodeid not in self.nodeids
                or declaration.launch_case != case or self.nodeid in self.launches
                or declaration.owner_sha256 != hashlib.sha256(
                    f"{self.nodeid} (call)".encode()).hexdigest()):
            raise RuntimeError("undeclared or repeated usage abrupt launch")
        self.verify_source()
        launch = UsageAbruptLaunch(self, declaration, uuid4().hex)
        self.launches[declaration.nodeid] = launch
        return launch

    def child_environment(self) -> dict[str, str]:
        """Choose no measurement for this not-yet-launched declared role only."""
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("COVERAGE_")}
        if self.session is not None:
            owned = {str(self.session.session_dir), str(self.session.bootstrap_dir)}
            environment["PYTHONPATH"] = os.pathsep.join(
                part for part in environment.get("PYTHONPATH", "").split(os.pathsep)
                if part and str(Path(part).resolve()) not in owned)
        return environment

    @contextmanager
    def spawn_environment(self):
        previous = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.child_environment_from(previous))
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def child_environment_from(self, previous):
        # Compute while original values are present; only this synchronous spawn
        # scope changes inheritance. No issued child registration is revoked.
        environment = {k: v for k, v in previous.items() if not k.startswith("COVERAGE_")}
        if self.session is not None:
            owned = {str(self.session.session_dir), str(self.session.bootstrap_dir)}
            environment["PYTHONPATH"] = os.pathsep.join(
                p for p in environment.get("PYTHONPATH", "").split(os.pathsep)
                if p and str(Path(p).resolve()) not in owned)
        return environment

    def _usage_environment(self, original: dict[str, str]) -> dict[str, str]:
        """Build a coverage/bootstrap-free environment for the exact A child."""
        environment = {key: value for key, value in original.items()
                       if not key.startswith("COVERAGE_")}
        owned: set[str] = set()
        if self.session is not None:
            owned.update((str(self.session.session_dir), str(self.session.bootstrap_dir)))
        if "PYTHONPATH" in environment:
            environment["PYTHONPATH"] = os.pathsep.join(
                item for item in environment["PYTHONPATH"].split(os.pathsep)
                if item and str(Path(item).resolve()) not in owned
            )
        return environment

    def _usage_declaration(self) -> Any:
        declaration = find_declaration(self.nodeid, self.declarations)
        return (declaration if declaration is not None and self.nodeid in self.nodeids
                and declaration.launch_case else None)

    @contextmanager
    def bind_session(self, session):
        import common_lore_index.coordinator._portable_worker_launch as owner
        previous_context = type(self)._CURRENT
        measured_adapter = owner.run_worker_spec
        original = getattr(measured_adapter, "_repomap_original", measured_adapter)
        self.session = session
        type(self)._CURRENT = self

        def observe(spec, identity, limits, **kwargs):
            # All ordinary children still take the measured adapter.
            declaration = self._usage_declaration()
            usage_case = None
            if len(spec.argv) >= 5 and tuple(spec.argv[1:3]) == (
                "-m", "repomap_test_support.usage_worker"):
                if spec.argv[3] == "--case" and len(spec.argv) > 4:
                    usage_case = spec.argv[4]
            if declaration is not None and usage_case == declaration.launch_case:
                if spec.argv[0] != sys.executable:
                    raise RuntimeError("usage abrupt interpreter identity mismatch")
                if kwargs.get("_launch_process") is not None or kwargs.get("_launch_ticket") is not None:
                    raise RuntimeError("usage abrupt launch cannot inject factory or ticket")
                if "_usage_observer" in kwargs:
                    raise RuntimeError("usage abrupt observer authority cannot be overridden")
                if kwargs.get("collect_usage") is not True:
                    raise RuntimeError("usage abrupt observer requires native usage collection")
                from runner_usage_command import (
                    USAGE_COMMAND, usage_python_paths, validate_usage_arguments,
                    validate_usage_probe,
                )
                from runner_usage_abrupt import observe_usage_checkpoint
                if tuple(spec.argv[1:3]) != USAGE_COMMAND:
                    raise RuntimeError("usage abrupt command identity mismatch")
                capability = getattr(self.session, "_portable_capability", None)
                parsed_case, probe = validate_usage_arguments(
                    tuple(spec.argv[3:]), measured_only=False,
                )
                if parsed_case != usage_case:
                    raise RuntimeError("usage abrupt case identity mismatch")
                tail = tuple(spec.argv[3:])
                try:
                    job_id = tail[tail.index("--job-id") + 1]
                    attempt = int(tail[tail.index("--attempt") + 1])
                except (ValueError, IndexError) as error:
                    raise RuntimeError("usage abrupt capability identity is malformed") from error
                if (job_id, attempt) != (identity.get("job_id"), identity.get("attempt")):
                    raise RuntimeError("usage abrupt capability identity mismatch")
                if capability is not None:
                    roots = (self.session.session_dir, self.session.child_manifest_dir,
                             self.session.data_dir)
                else:
                    roots = (None, None, None)
                if probe is not None:
                    validate_usage_probe(
                        probe, case=parsed_case, session_dir=roots[0],
                        child_manifest_dir=roots[1], data_dir=roots[2],
                    )
                expected_paths = usage_python_paths(Path(__file__).resolve().parents[1])
                actual_paths = tuple(
                    Path(item).resolve() for item in
                    str(spec.environment.get("PYTHONPATH", "")).split(os.pathsep) if item
                )
                if actual_paths != expected_paths:
                    raise RuntimeError("usage abrupt source paths mismatch")
                usage_launch = self.begin_usage(declaration.role, usage_case)
                clean = replace(spec, environment=self._usage_environment(dict(spec.environment)))
                original_kwargs = dict(kwargs)
                original_kwargs["_usage_observer"] = usage_launch
                # Keep the native default launcher and resource reaper; A is
                # intentionally outside coverage registration and M receipts.
                try:
                    result = original(clean, identity, limits, **original_kwargs)
                except BaseException as error:
                    try:
                        observe_usage_checkpoint(usage_launch, clean, None)
                        usage_launch.record()
                    except Exception as checkpoint_error:
                        error.add_note(
                            f"usage abrupt checkpoint evidence failure: "
                            f"{type(checkpoint_error).__name__}"
                        )
                    raise
                observe_usage_checkpoint(usage_launch, clean, result)
                usage_launch.record()
                return result
            if (find_declaration(self.nodeid, self.declarations) is None
                    or self.nodeid not in self.nodeids
                    or tuple(spec.argv[1:5]) != (
                        "-m", "repomap_test_support.portable_worker_conformance",
                        "--case", "crash:after-materialization")):
                return measured_adapter(spec, identity, limits, **kwargs)
            if session is not None:
                cap = session._portable_capability
                cap.validate_for_launch()
                if spec.argv[0] != sys.executable:
                    raise RuntimeError("abrupt conformance interpreter mismatch")
                from runner_coverage_conformance import validate_conformance_arguments
                validate_conformance_arguments(tuple(spec.argv[3:]))
                paths = cap.paths_for_command(tuple(spec.argv[1:3]))
                if tuple(Path(p).resolve() for p in spec.environment["PYTHONPATH"].split(os.pathsep)) != paths:
                    raise RuntimeError("abrupt conformance source paths mismatch")
            if any(k.startswith("COVERAGE_") for k in spec.environment):
                raise RuntimeError("ambient coverage in abrupt spec")
            from common_lore_index.coordinator.process_supervision import launch_managed_process
            launch = self.begin("conformance-abrupt")
            launcher = kwargs.pop("_launch_process", None) or launch_managed_process

            def registered_launch(*args, **options):
                return launch.launched(launcher(*args, **options))

            result = original(spec, identity, limits, _launch_process=registered_launch, **kwargs)
            # The child emits this bounded checkpoint on its own stderr at the
            # intended fault. Captured pipes belong to this exact launch.
            expected = f"REPOMAP_ABRUPT_CHECKPOINT during_semantic {launch.pid}"
            if expected not in result.stderr.splitlines():
                raise RuntimeError("conformance pre-fault checkpoint was not observed")
            launch.observed_checkpoint("during_semantic")
            launch.settle(launch.process.returncode, cleanup=(
                result.waited and result.process_group_cleaned
                and result.cleanup_error is None and result.protocol_error is None))
            return result

        owner.run_worker_spec = observe
        try:
            yield self
        finally:
            owner.run_worker_spec = measured_adapter
            type(self)._CURRENT = previous_context
            self.session = None

    def record_usage(self) -> dict[str, Any]:
        declaration = self._usage_declaration()
        if declaration is None:
            raise RuntimeError("no usage abrupt declaration selected")
        launch = self.launches.get(declaration.nodeid)
        if not isinstance(launch, UsageAbruptLaunch):
            raise RuntimeError("usage abrupt launch was not observed")
        return launch.record()


def active_abrupt_context() -> AbruptRunnerContext:
    context = AbruptRunnerContext._CURRENT
    if context is None or context.nodeid is None:
        raise RuntimeError("abrupt launch requires sealed runner context")
    return context
