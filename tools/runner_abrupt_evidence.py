"""Test-owned prelaunch configuration and observed abrupt lifecycle evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
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
        self.launches: dict[str, AbruptLaunch] = {}
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

    @contextmanager
    def bind_session(self, session):
        import repomap_kg.coordinator._portable_worker_launch as owner
        previous_context = type(self)._CURRENT
        measured_adapter = owner.run_worker_spec
        original = getattr(measured_adapter, "_repomap_original", measured_adapter)
        self.session = session
        type(self)._CURRENT = self

        def observe(spec, identity, limits, **kwargs):
            # All ordinary children still take the measured adapter.
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
            from repomap_kg.coordinator.process_supervision import launch_managed_process
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


def active_abrupt_context() -> AbruptRunnerContext:
    context = AbruptRunnerContext._CURRENT
    if context is None or context.nodeid is None:
        raise RuntimeError("abrupt launch requires sealed runner context")
    return context
