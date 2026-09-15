"""Test-owned external-process boundary instrumentation.

Two independent detectors, because either alone can be defeated:

``poison_psql_directory``
    writes an executable literally named ``psql`` that records its invocation
    and exits with a unique nonzero code, for placing first on ``PATH``.

``RecordingProcessBoundary``
    wraps host process creation and inspects the **whole** argv for basename
    ``psql``, not just ``argv[0]``.

The second detector exists because a psql invocation can be nested inside
another executable's argument list, for example
``docker exec -i <container> psql ...``. There ``argv[0]`` is the container
runtime, so a ``PATH``-only poison observes a clean run on a path that does in
fact execute psql.

Two axes, never conflated
------------------------
A nested token is an *intent*, not a host process. ``docker exec ... psql`` is
one host ``docker`` process carrying one nested psql intent and zero host psql
processes. Reporting it as a host ``psql`` process would misstate what the
operating system was actually asked to execute, and would make a
container-mediated read indistinguishable from a direct client invocation.

One spawn, one observation
--------------------------
Only the lowest common process-creation boundary is instrumented:
``subprocess.Popen.__init__``. ``subprocess.run``, ``call``, ``check_call``,
and ``check_output`` all construct a ``Popen``, so wrapping them as well would
record a single host process twice. Process APIs that genuinely bypass
``Popen`` — the ``os.exec*`` family — get their own distinct, non-overlapping
owner rather than being folded into this one.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = (
    "POISON_PSQL_EXIT_CODE",
    "PsqlInvokedError",
    "ProcessInvocation",
    "RecordingProcessBoundary",
    "classify_host_executable",
    "poison_psql_directory",
)

POISON_PSQL_EXIT_CODE = 97

_CONTAINER_RUNTIMES = frozenset({"docker", "podman", "nerdctl"})
_POSTGRES_CLIENTS = frozenset(
    {"pg_dump", "pg_restore", "pg_isready", "pg_dumpall", "createdb", "dropdb"}
)
_GO_TOOLS = frozenset({"go", "gofmt", "golangci-lint"})


class PsqlInvokedError(RuntimeError):
    """Raised by a fail-closed boundary when psql would have been executed."""


def classify_host_executable(basename: str) -> str:
    """Classify the executable the operating system was actually asked to run."""
    if basename == "psql":
        return "psql"
    if basename in _CONTAINER_RUNTIMES:
        return "container_runtime"
    if basename in _POSTGRES_CLIENTS:
        return "postgres_client"
    if basename.startswith("python"):
        return "python"
    if basename in _GO_TOOLS:
        return "go_toolchain"
    return "other"


@dataclass(frozen=True)
class ProcessInvocation:
    """One observed host process creation, in public-safe terms.

    ``nested_psql_token_positions`` records every argv index whose basename is
    ``psql``. For a direct client invocation that is position zero; for a
    container-mediated read it is a later position. The two cases are
    distinguished by ``host_executable_basename``, never by collapsing them.
    """

    process_api: str
    host_executable_basename: str
    argv_length: int
    nested_psql_token_positions: tuple[int, ...]

    @property
    def host_process_class(self) -> str:
        return classify_host_executable(self.host_executable_basename)

    @property
    def contains_nested_psql_intent(self) -> bool:
        return bool(self.nested_psql_token_positions)

    @property
    def is_host_psql_process(self) -> bool:
        return self.host_executable_basename == "psql"


def poison_psql_directory(directory: Path) -> Path:
    """Create an executable named ``psql`` that always fails distinctly."""
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "psql-invocations.log"
    command = directory / "psql"
    command.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> {log}\n'
        f"exit {POISON_PSQL_EXIT_CODE}\n",
        encoding="utf-8",
    )
    command.chmod(0o700)
    return command


def _tokens(argv: object) -> list[str]:
    if isinstance(argv, (str, bytes, os.PathLike)):
        return [os.fsdecode(os.fspath(argv))]
    if isinstance(argv, Iterable):
        out: list[str] = []
        for item in argv:
            try:
                out.append(os.fsdecode(os.fspath(item)))
            except TypeError:
                out.append(str(item))
        return out
    return [str(argv)]


@dataclass
class RecordingProcessBoundary:
    """Record host process creation; optionally fail closed on psql.

    Install with ``monkeypatch`` so the wrappers are removed automatically::

        boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
        boundary.install(monkeypatch)
    """

    fail_closed_on_psql: bool = False
    invocations: list[ProcessInvocation] = field(default_factory=list)

    # --- host process counts -------------------------------------------------

    @property
    def host_process_count(self) -> int:
        return len(self.invocations)

    def host_process_count_by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.invocations:
            counts[item.host_process_class] = (
                counts.get(item.host_process_class, 0) + 1
            )
        return counts

    def counts_by_host_executable(self) -> dict[str, int]:
        """Count by the executable actually launched.

        A nested token is never substituted for ``argv[0]``.
        """
        counts: dict[str, int] = {}
        for item in self.invocations:
            key = item.host_executable_basename
            counts[key] = counts.get(key, 0) + 1
        return counts

    # --- psql axes -----------------------------------------------------------

    @property
    def nested_psql_intent_count(self) -> int:
        return sum(1 for item in self.invocations
                   if item.contains_nested_psql_intent)

    @property
    def host_psql_process_count(self) -> int:
        return sum(1 for item in self.invocations if item.is_host_psql_process)

    # --- instrumentation -----------------------------------------------------

    def _observe(self, argv: object, api: str) -> None:
        tokens = _tokens(argv)
        positions = tuple(
            index
            for index, token in enumerate(tokens)
            if os.path.basename(token) == "psql"
        )
        self.invocations.append(
            ProcessInvocation(
                process_api=api,
                host_executable_basename=(
                    os.path.basename(tokens[0]) if tokens else ""
                ),
                argv_length=len(tokens),
                nested_psql_token_positions=positions,
            )
        )
        if positions and self.fail_closed_on_psql:
            raise PsqlInvokedError(
                f"psql invoked via {api} at argv positions {list(positions)}"
            )

    def install(self, monkeypatch) -> "RecordingProcessBoundary":
        """Instrument the single lowest common host-spawn boundary.

        ``subprocess.run`` and friends are deliberately left alone: they build
        a ``Popen``, so wrapping them too would double-count one host process.
        """
        real_popen_init = subprocess.Popen.__init__

        def guarded_popen_init(inner, argv: Sequence[str], *args, **kwargs):
            self._observe(argv, "subprocess.Popen")
            return real_popen_init(inner, argv, *args, **kwargs)

        monkeypatch.setattr(subprocess.Popen, "__init__", guarded_popen_init)
        return self

    def install_exec_owner(self, monkeypatch) -> "RecordingProcessBoundary":
        """Instrument the ``os.exec*`` family as a distinct, separate owner.

        ``tools/actual_refresh_child_bootstrap.py`` replaces its own image with
        ``os.execvpe``, which never reaches ``Popen``. This owner does not
        overlap the ``Popen`` owner, so a process is still recorded once.
        """
        real_execvpe = os.execvpe
        real_execv = os.execv

        def guarded_execvpe(file, argv, env):
            self._observe(argv, "os.execvpe")
            return real_execvpe(file, argv, env)

        def guarded_execv(path, argv):
            self._observe(argv, "os.execv")
            return real_execv(path, argv)

        monkeypatch.setattr(os, "execvpe", guarded_execvpe)
        monkeypatch.setattr(os, "execv", guarded_execv)
        return self
