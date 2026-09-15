"""Test-owned process-creation boundary evidence for TEST-COV5K-R2."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from multiprocessing.process import BaseProcess
import os
from pathlib import Path
import subprocess
from threading import RLock, local
import time
from typing import Callable, Protocol, TypeVar, runtime_checkable
from unittest.mock import patch

from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    OwnerEntryEvidence,
    ExecutorEvidence,
    bind_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_contracts import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program


_T = TypeVar("_T")


@runtime_checkable
class _IndexedCommand(Protocol):
    """Legacy sequence iteration is also accepted by subprocess observers."""

    def __getitem__(self, index: int, /) -> object: ...


@dataclass(frozen=True, slots=True)
class ProcessCreation:
    """One process creation observed before the child can exit."""

    boundary: str
    host_executable: str
    command_shape: tuple[str, ...]
    nested_psql_intent: bool
    excluded_harness_lifecycle: bool


@dataclass(frozen=True, slots=True)
class ProcessBoundaryEvidence:
    """Complete immutable process intent evidence for one operation."""

    operation_started_ns: int
    operation_ended_ns: int
    creations: tuple[ProcessCreation, ...]

    @property
    def host_process_count(self) -> int:
        return sum(not event.excluded_harness_lifecycle for event in self.creations)

    @property
    def nested_psql_intent_count(self) -> int:
        return sum(
            event.nested_psql_intent and not event.excluded_harness_lifecycle
            for event in self.creations
        )


def _command_shape(command: object) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        return ("<shell-text>",)
    if not isinstance(command, (Iterable, _IndexedCommand)):
        return ("<opaque-command>",)
    try:
        values = tuple(str(value) for value in iter(command))
    except TypeError:
        return ("<opaque-command>",)
    if not values:
        return ("<empty-command>",)
    return (Path(values[0]).name, *("<arg>" for _ in values[1:]))


def _host_executable(command: object) -> str:
    if isinstance(command, (str, bytes)):
        return "shell"
    if not isinstance(command, (Iterable, _IndexedCommand)):
        return "unknown"
    try:
        first = next(iter(command))
    except (StopIteration, TypeError):
        return "unknown"
    return Path(str(first)).name


class ProcessBoundaryRecorder:
    """Record Popen/run/spawn/multiprocessing creation at entry boundaries."""

    def __init__(self) -> None:
        self._events: list[ProcessCreation] = []
        self._lock = RLock()
        self._state = local()
        self._started_ns = 0
        self._ended_ns = 0

    def _record(self, boundary: str, command: object) -> None:
        executable = _host_executable(command)
        excluded = executable in {"resource_tracker", "forkserver"}
        event = ProcessCreation(
            boundary,
            executable,
            _command_shape(command),
            executable == "psql",
            excluded,
        )
        with self._lock:
            self._events.append(event)

    def _outer(self) -> bool:
        return getattr(self._state, "depth", 0) == 0

    def _call(self, boundary: str, command: object, call: Callable[[], _T]) -> _T:
        outer = self._outer()
        self._state.depth = getattr(self._state, "depth", 0) + 1
        try:
            if outer:
                self._record(boundary, command)
            return call()
        finally:
            self._state.depth -= 1

    def record_explicit_child(self, executable: str, *arguments: str) -> None:
        """Record an explicit harness child at the same creation boundary."""

        self._record("explicit_harness_child", (executable, *arguments))

    def run(self, operation: Callable[[], _T]) -> tuple[_T, ProcessBoundaryEvidence]:
        """Execute operation while observing every supported creation API."""

        original_popen: Callable[..., subprocess.Popen[bytes] | subprocess.Popen[str]] = (
            subprocess.Popen
        )
        original_run: Callable[
            ..., subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]
        ] = subprocess.run
        original_spawn = getattr(os, "posix_spawn", None)
        original_spawnp = getattr(os, "posix_spawnp", None)
        original_process_start = BaseProcess.start

        def popen(*args: object, **kwargs: object):
            command = args[0] if args else kwargs.get("args", ())
            return self._call(
                "subprocess.Popen",
                command,
                lambda: original_popen(*args, **kwargs),
            )

        def run(*args: object, **kwargs: object):
            command = args[0] if args else kwargs.get("args", ())
            return self._call(
                "subprocess.run",
                command,
                lambda: original_run(*args, **kwargs),
            )

        def process_start(process: BaseProcess) -> None:
            name = getattr(process, "name", "multiprocessing-child")
            return self._call(
                "multiprocessing.Process.start",
                (name,),
                lambda: original_process_start(process),
            )

        self._started_ns = time.monotonic_ns()
        with ExitStack() as stack:
            stack.enter_context(patch.object(subprocess, "Popen", popen))
            stack.enter_context(patch.object(subprocess, "run", run))
            stack.enter_context(patch.object(BaseProcess, "start", process_start))
            if original_spawn is not None:
                def spawn(path: object, argv: object, env: object, **kwargs: object):
                    return self._call(
                        "os.posix_spawn",
                        argv,
                        lambda: original_spawn(path, argv, env, **kwargs),
                    )
                stack.enter_context(patch.object(os, "posix_spawn", spawn))
            if original_spawnp is not None:
                def spawnp(path: object, argv: object, env: object, **kwargs: object):
                    return self._call(
                        "os.posix_spawnp",
                        argv,
                        lambda: original_spawnp(path, argv, env, **kwargs),
                    )
                stack.enter_context(patch.object(os, "posix_spawnp", spawnp))
            result = operation()
        self._ended_ns = time.monotonic_ns()
        return result, ProcessBoundaryEvidence(
            self._started_ns,
            self._ended_ns,
            tuple(self._events),
        )


def record_process_boundary(operation: Callable[[], object]) -> ProcessBoundaryEvidence:
    """Run an operation through the complete creation recorder."""

    _, evidence = ProcessBoundaryRecorder().run(operation)
    return evidence


def execute_zero_process_boundary(
    entry: CatalogEntry,
    operation: Callable[[], object],
) -> ExecutorEvidence:
    """Run a Group H owner and retain all creation and nested intent facts."""

    axis = str(dict(entry.parameter_values)["axis"])
    program = scenario_program(
        owner_identity="ProcessBoundaryRecorder.run",
        seam_identity="fix3.process_boundary.operation",
        input_action=(("axis", axis),),
        expected_product_event_classes=("process_boundary",),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    evidence, owner_evidence, _frames = invoke_bound_owner(
        evidence_factory=OwnerEntryEvidence,
        executor=execute_zero_process_boundary,
        owner=ProcessBoundaryRecorder.run,
        scenario_seam_active=True,
        operation=lambda: record_process_boundary(operation),
    )
    observed = (
        ("primary_result_category", "axis_completed"),
        ("host_process_count", evidence.host_process_count),
        ("nested_psql_intent_count", evidence.nested_psql_intent_count),
        ("process_creations", evidence.creations),
        ("operation_started_ns", evidence.operation_started_ns),
        ("operation_ended_ns", evidence.operation_ended_ns),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=(("axis", str(dict(program.input_action)["axis"])),),
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=(("process_boundary", evidence),),
    )
