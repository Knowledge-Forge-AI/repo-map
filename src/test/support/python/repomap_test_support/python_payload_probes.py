"""Test-support subprocess adapter for isolating python_payload stdlib import probes (ADR 0093).

During measured integration runs, ``ChildCoverageSession`` exports ``COVERAGE_PROCESS_START``
(and pinned Coverage ``7.15.4`` supports inherited ``COVERAGE_PROCESS_CONFIG`` alongside
``COVERAGE_PROCESS_START`` in its ``a1_coverage.pth`` startup hook from ``coverage/pth_file.py``
and ``coverage/control.py``) and prepends its bootstrap ``sitecustomize.py`` directory to
``PYTHONPATH``. When ``common_lore_index.runtime.python_payload`` probes candidate SDK dynamic extensions
via ``[sys.executable, "-I", "-B", "-c", "import <mod>"]`` with
``env={**os.environ, "LD_BIND_NOW": "1"}``, CPython's ``-I`` flag ignores ``PYTHONPATH`` (skipping
the runner's ``sitecustomize.py`` manifest registration) while ``site.py`` still processes
``site-packages/*.pth`` and triggers ``coverage.process_startup(slug="pth")``, writing an
unregistered ``launch_shape=cpython:-c`` coverage shard.

This test-support adapter wraps ``subprocess.run`` to scrub inherited coverage startup state
via ``prepare_child_coverage_environment(..., family="unmeasured")`` strictly for that exact
5-argument stdlib import probe shape and only for the caller's explicitly selected CPython
stdlib module names. All other subprocess calls (such as ``ldd`` and ``dpkg-query``) pass
through with their original arguments and environment untouched, and any unapproved
``-I -B -c`` probe is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

_TOOLS_DIR = str(Path(__file__).resolve().parents[5] / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from runner_coverage_execution import prepare_child_coverage_environment

Runner = Callable[..., subprocess.CompletedProcess[str]]
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STDLIB_MODULE_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names) | {"_tkinter"}


def validate_allowed_stdlib_modules(allowed_modules: Iterable[str]) -> frozenset[str]:
    """Validate that ``allowed_modules`` is a non-empty set of CPython stdlib module names."""
    normalized: set[str] = set()
    for raw in allowed_modules:
        if not isinstance(raw, str) or not _MODULE_NAME_RE.fullmatch(raw):
            raise ValueError(f"invalid stdlib probe module name: {raw!r}")
        if raw.startswith("repomap") or raw not in _STDLIB_MODULE_NAMES:
            raise ValueError(f"refusing non-stdlib module in probe allowlist: {raw!r}")
        normalized.add(raw)
    if not normalized:
        raise ValueError("allowed_modules for stdlib import probe runner must not be empty")
    return frozenset(normalized)


def is_stdlib_import_probe_command(
    command: Sequence[str],
    *,
    executable: str,
    allowed_modules: frozenset[str],
) -> bool:
    """Return True if ``command`` is an approved ``[executable, "-I", "-B", "-c", "import <mod>"]``.

    Raises ``ValueError`` if ``command`` matches the ``[executable, "-I", "-B", "-c", ...]``
    probe shape (or invokes ``executable`` with ``-c``) for an unapproved module or snippet.
    """
    if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
        return False
    tokens = [str(part) for part in command]
    if not tokens or tokens[0] != executable:
        return False
    if len(tokens) == 5 and tuple(tokens[1:4]) == ("-I", "-B", "-c"):
        snippet = tokens[4]
        if snippet.startswith("import "):
            mod_name = snippet[len("import ") :]
            if mod_name in allowed_modules:
                return True
        raise ValueError(f"refusing unapproved python -I -B -c probe command: {tokens!r}")
    if "-c" in tokens[1:]:
        raise ValueError(f"refusing unapproved python -c command in payload probe runner: {tokens!r}")
    return False


def make_stdlib_import_probe_runner(
    allowed_modules: Iterable[str],
    *,
    run: Runner = subprocess.run,
    executable: str = sys.executable,
) -> Runner:
    """Wrap ``run`` so approved ``python -I -B -c "import <stdlib>"`` probes run unmeasured."""
    allowed = validate_allowed_stdlib_modules(allowed_modules)
    if not isinstance(executable, str) or not executable:
        raise ValueError("executable must be a non-empty string")

    def _run_probe_aware(command: Sequence[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if not is_stdlib_import_probe_command(command, executable=executable, allowed_modules=allowed):
            return run(command, *args, **kwargs)
        raw_env = kwargs.get("env")
        source_env: dict[str, str] = dict(os.environ) if raw_env is None else dict(raw_env)
        clean_env = prepare_child_coverage_environment(source_env, family="unmeasured")
        clean_env.pop("COVERAGE_FILE", None)
        updated_kwargs = {**kwargs, "env": clean_env}
        return run(command, *args, **updated_kwargs)

    return _run_probe_aware
