"""Native input custody helpers for the private public-text host (study section 19.2).

Definitions only: exact phase-owned directories, a byte-verified copy of the
unchanged flat worker closure, the one fixed learned argv and a scoped child
environment mapping. Nothing here launches a runner, model, container or SQL,
reserves a slot or reads credentials; composing an argv grants no execution.
Callers pass the private scratch root; no private path is stored in Q.
"""

from __future__ import annotations

from typing import cast

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES

LEARNED_SELECTOR = (
    "src/test/int/python/tools/retrieval_public_text_study.int.test.py::test_public_text_semantic_study"
)
FUNCTIONAL_SELECTOR = (
    "src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py::test_public_text_functional_lifecycle"
)
PG_CONTAINER_PORT = "55433"
NATIVE_LABEL = "REPOMAP-CLOE-PUBLIC-TEXT1-PUBLICTEXT-CAL1"
MAX_WORKER_SOURCE_BYTES = 1024 * 1024
SCRATCH_NAMES = ("tmp", "pycache", "resource-runs", "go-cache", "go-tmp", "pip-cache", "xdg-cache", "xdg-config")
REMOVED_ENVIRONMENT = (
    "COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG", "PYTHONOPTIMIZE", "PYTHONSTARTUP", "PYTHONINSPECT",
    "PYTHONPATH", "PYTHONHOME", "REPOMAP_TEST_RUN_ROOT", "REPOMAP_TEST_RUNTIME_IMAGE", "CLOE_HOME",
    "REPOMAP_HOME", "DOCKER_DEFAULT_PLATFORM",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class NativeInputRefusal(ValueError):
    """Closed refusal without raw paths, file content or credentials."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, repr=False)
class NativePaths:
    """Exact phase-owned paths below one private scratch root; never serialized publicly."""

    run_root: Path
    source_view: Path
    report_dir: Path
    stdout_path: Path
    stderr_path: Path
    input_roots: tuple[Path, Path]
    output_roots: tuple[Path, Path]

    def __repr__(self) -> str:
        return "NativePaths(<private>)"


def _owned_directory(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise NativeInputRefusal("native_directory_invalid")
    if any(ancestor.is_symlink() for ancestor in (path, *path.parents)):
        raise NativeInputRefusal("native_directory_symlink")
    try:
        details = os.lstat(path)
    except OSError:
        raise NativeInputRefusal("native_directory_unavailable") from None
    if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700):
        raise NativeInputRefusal("native_directory_custody")


def _new_directory(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    except OSError:
        raise NativeInputRefusal("native_directory_already_used_or_unavailable") from None
    _owned_directory(path)
    return path


def create_native_paths(scratch_root: Path) -> NativePaths:
    """Create fresh exact directories; a reused run or report directory refuses."""
    for path in (scratch_root, scratch_root / "tmp", scratch_root / "evidence"):
        _owned_directory(path)
    run_root = scratch_root / "tmp" / "publictext-cal1-native"
    report_dir = scratch_root / "evidence" / "publictext-cal1-native-report"
    if report_dir.exists() or report_dir.is_symlink():
        raise NativeInputRefusal("native_report_already_used")
    _new_directory(run_root)
    source_view = _new_directory(run_root / "worker-source")
    inputs = tuple(_new_directory(run_root / f"model-input-g{g}") for g in (1, 2))
    outputs = tuple(_new_directory(run_root / f"model-output-g{g}") for g in (1, 2))
    for name in SCRATCH_NAMES:
        _new_directory(run_root / name)
    return NativePaths(run_root, source_view, report_dir, run_root / "canonical.stdout.log",
                       run_root / "canonical.stderr.log", cast(tuple[Path, Path], inputs), cast(tuple[Path, Path], outputs))


def _read_verified(source: Path, digest: str) -> bytes:
    try:
        before = os.lstat(source)
    except OSError:
        raise NativeInputRefusal("native_worker_source_unavailable") from None
    if (stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
            or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not 0 < before.st_size <= MAX_WORKER_SOURCE_BYTES):
        raise NativeInputRefusal("native_worker_source_custody")
    try:
        descriptor = os.open(source, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
    except OSError:
        raise NativeInputRefusal("native_worker_source_unavailable") from None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise NativeInputRefusal("native_worker_source_changed")
        raw = bytearray()
        while len(raw) <= MAX_WORKER_SOURCE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_WORKER_SOURCE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        if len(raw) != before.st_size or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise NativeInputRefusal("native_worker_source_changed")
    finally:
        os.close(descriptor)
    if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
        raise NativeInputRefusal("native_worker_source_digest")
    return bytes(raw)


def _write_exclusive(target: Path, raw: bytes) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise NativeInputRefusal("native_worker_source_write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_worker_view(tools_root: Path, paths: NativePaths, expected: Mapping[str, str]) -> dict[str, str]:
    """Copy exactly the unchanged flat worker closure after hash/mode/owner/no-follow checks."""
    _owned_directory(paths.source_view)
    if not isinstance(expected, Mapping) or set(expected) != set(WORKER_SOURCE_FILES):
        raise NativeInputRefusal("native_worker_closure_population")
    if any(type(value) is not str or _DIGEST.fullmatch(value) is None for value in expected.values()):
        raise NativeInputRefusal("native_worker_source_identity")
    if any(paths.source_view.iterdir()):
        raise NativeInputRefusal("native_worker_view_not_empty")
    if not isinstance(tools_root, Path) or not tools_root.is_absolute() or tools_root.is_symlink():
        raise NativeInputRefusal("native_worker_tools_root")
    sources = {name: _read_verified(tools_root / name, expected[name]) for name in WORKER_SOURCE_FILES}
    for name, raw in sources.items():
        try:
            _write_exclusive(paths.source_view / name, raw)
        except OSError:
            raise NativeInputRefusal("native_worker_source_write") from None
    directory = os.open(paths.source_view, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {name: expected[name] for name in WORKER_SOURCE_FILES}


def canonical_argv(interpreter: Path, paths: NativePaths, diagnostic_runtime: str) -> tuple[str, ...]:
    """The single learned selector with the existing source-proof runtime override; no other flags."""
    if not isinstance(interpreter, Path) or not interpreter.is_absolute() or not interpreter.name.startswith("python"):
        raise NativeInputRefusal("native_interpreter_binding")
    if type(diagnostic_runtime) is not str or _DIGEST.fullmatch(diagnostic_runtime) is None:
        raise NativeInputRefusal("native_runtime_binding")
    return (
        str(interpreter), "-I", "-B", "tools/run_tests.py", "--suite", "int", "--no-coverage", "--jobs", "1",
        "--pg-test-profile", "pgvector", "--pg-container-port", PG_CONTAINER_PORT,
        "--smoke-image-reference", diagnostic_runtime, "--report-dir", str(paths.report_dir),
        "--", LEARNED_SELECTOR, "-s",
    )


def child_environment(paths: NativePaths, base: Mapping[str, str]) -> dict[str, str]:
    """A new mapping for the child only; the caller's own environment is never mutated."""
    for name in SCRATCH_NAMES:
        _owned_directory(paths.run_root / name)
    environment = {key: value for key, value in base.items() if key not in REMOVED_ENVIRONMENT}
    tmp = str(paths.run_root / "tmp")
    environment.update({
        "TMPDIR": tmp, "TMP": tmp, "TEMP": tmp, "PYTHONPYCACHEPREFIX": str(paths.run_root / "pycache"),
        "PYTHONDONTWRITEBYTECODE": "1", "REPOMAP_TEST_SCRATCH_ROOT": str(paths.run_root / "resource-runs"),
        "REPOMAP_TEST_PROJECT": "repo-map_public", "REPOMAP_TEST_PHASE": NATIVE_LABEL, "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1", "GOCACHE": str(paths.run_root / "go-cache"),
        "GOTMPDIR": str(paths.run_root / "go-tmp"), "PIP_CACHE_DIR": str(paths.run_root / "pip-cache"),
        "XDG_CACHE_HOME": str(paths.run_root / "xdg-cache"), "XDG_CONFIG_HOME": str(paths.run_root / "xdg-config"),
    })
    return environment


__all__ = [
    "FUNCTIONAL_SELECTOR", "LEARNED_SELECTOR", "NATIVE_LABEL", "NativeInputRefusal", "NativePaths",
    "PG_CONTAINER_PORT", "canonical_argv", "child_environment", "copy_worker_view", "create_native_paths",
]
