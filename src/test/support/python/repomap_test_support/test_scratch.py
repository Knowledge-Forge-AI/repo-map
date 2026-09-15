"""Repository-owned test scratch authority.

One deterministic layout for every temporary, cache, and build-state path a
RepoMap test run creates, so no test writes to an unowned location and no
selected path leaks the developer's home directory.

Ownership order matters. ``tools/run_tests.py`` establishes the layout before
Go validation, pytest collection, or any Docker command starts; the common
pytest conftest reuses whatever the runner already allocated and only allocates
its own root when pytest is invoked directly.

This module must stay dependency-free and must not import product code: it runs
before the product is importable.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

__all__ = (
    "DEFAULT_PHASE",
    "DEFAULT_PROJECT",
    "ENV_PHASE",
    "ENV_PROJECT",
    "ENV_RUN_ROOT",
    "ENV_SCRATCH_ROOT",
    "MANIFEST_SCHEMA",
    "MAX_SOCKET_PATH_BYTES",
    "TestScratchError",
    "TestScratchLayout",
    "allocate_run_root",
    "establish_run",
    "finalize_run",
    "read_run_manifest",
    "select_scratch_root",
    "short_test_directory",
    "socket_component_byte_capacity",
    "validate_inherited_run_root",
)

from repomap_test_support.test_scratch_contract import (
    ENV_SCRATCH_ROOT as ENV_SCRATCH_ROOT,
    ENV_RUN_ROOT as ENV_RUN_ROOT,
    ENV_PROJECT as ENV_PROJECT,
    ENV_PHASE as ENV_PHASE,
    DEFAULT_PROJECT as DEFAULT_PROJECT,
    DEFAULT_PHASE as DEFAULT_PHASE,
    DARWIN_SHARED_ROOT as DARWIN_SHARED_ROOT,
    PORTABLE_ROOT_NAME as PORTABLE_ROOT_NAME,
    MAX_SOCKET_PATH_BYTES as MAX_SOCKET_PATH_BYTES,
    MANIFEST_SCHEMA as MANIFEST_SCHEMA,
    _TERMINAL_STATES as _TERMINAL_STATES,
    TestScratchError as TestScratchError,
)

from repomap_test_support.test_scratch_layout import (
    TestScratchLayout as TestScratchLayout,
    _monitoring_index as _monitoring_index,
    short_test_directory as short_test_directory,
    socket_component_byte_capacity as socket_component_byte_capacity,
)


def _is_safe_directory(path: Path) -> bool:
    """True when path is a real directory this user owns and can use."""
    try:
        stat = path.lstat()
    except OSError:
        return False
    if path.is_symlink() or not os.path.isdir(path):
        return False
    if stat.st_uid != os.getuid():
        return False
    return os.access(path, os.R_OK | os.W_OK | os.X_OK)


def select_scratch_root(environ=None) -> Path:
    """Select the scratch authority.

    Precedence: an explicit ``REPOMAP_TEST_SCRATCH_ROOT``; then the Darwin
    shared root, but only when it already exists and is safe; then a portable
    fallback beneath the platform temporary directory for ordinary developer
    and CI use. The shared root is never created here — it is operator-managed.
    """
    env = os.environ if environ is None else environ
    explicit = env.get(ENV_SCRATCH_ROOT)
    if explicit:
        root = Path(explicit)
        if not root.is_absolute():
            raise TestScratchError(f"{ENV_SCRATCH_ROOT} must be absolute")
        root.mkdir(parents=True, exist_ok=True)
        if not _is_safe_directory(root):
            raise TestScratchError(
                f"{ENV_SCRATCH_ROOT} is not a safe, writable directory"
            )
        return root

    if sys.platform == "darwin" and _is_safe_directory(DARWIN_SHARED_ROOT):
        return DARWIN_SHARED_ROOT

    fallback = Path(tempfile.gettempdir()) / PORTABLE_ROOT_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    if not _is_safe_directory(fallback):
        raise TestScratchError("no safe portable scratch root is available")
    return fallback


def allocate_run_root(scratch_root: Path) -> Path:
    """Allocate one short run root by exclusive directory creation.

    Uniqueness comes from exclusive creation, never from time alone.
    """
    parent = Path(scratch_root) / "r"
    parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(64):
        candidate = parent / ("t" + os.urandom(5).hex())
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return candidate
    raise TestScratchError("could not allocate a unique test run root")


def _owned_by_current_user(path: Path) -> bool:
    try:
        return path.lstat().st_uid == os.getuid()
    except OSError:
        return False


def read_run_manifest(run_root: Path) -> dict:
    """Read one run's manifest, refusing anything that is not a plain file.

    A symlinked manifest is refused rather than followed: the link could point
    at another owner's record, and writing through it would damage theirs.
    """
    manifest = Path(run_root) / "manifest.json"
    if manifest.is_symlink():
        raise TestScratchError("run manifest must not be a symlink")
    if not manifest.is_file():
        raise TestScratchError("run manifest is missing")
    if not _owned_by_current_user(manifest):
        raise TestScratchError("run manifest is not owned by this user")
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TestScratchError("run manifest is not readable JSON") from error
    if not isinstance(manifest_data, dict):
        raise TestScratchError("run manifest is not a JSON object")
    return manifest_data


def _require_manifest_identity(manifest: dict, run_root: Path, *, project: str,
                               phase: str | None = None) -> None:
    """Require every field that makes a manifest *this* project's *this* run.

    The scratch root is shared with other projects and other agents, so a
    directory being safe and beneath the root says nothing about who owns it.
    Only the manifest does.
    """
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise TestScratchError(f"run manifest schema is not {MANIFEST_SCHEMA}")
    if manifest.get("run_kind") != "test":
        raise TestScratchError("run manifest is not a test run")
    if manifest.get("project") != project:
        raise TestScratchError("run manifest belongs to another project")
    if phase is not None and manifest.get("phase") != phase:
        raise TestScratchError("run manifest belongs to another phase")
    if manifest.get("run_id") != run_root.name:
        raise TestScratchError("run manifest run_id is not its directory name")
    physical = manifest.get("physical_run_root")
    if not physical or Path(physical).resolve() != run_root.resolve():
        raise TestScratchError("run manifest physical_run_root does not match")


def _validated_inherited_run(
    run_root: Path,
    scratch_root: Path,
    *,
    project: str,
    phase: str | None = None,
) -> tuple[Path, dict]:
    root = Path(run_root)
    if not root.is_absolute():
        raise TestScratchError(f"{ENV_RUN_ROOT} must be absolute")
    if root.is_symlink():
        raise TestScratchError(f"{ENV_RUN_ROOT} must not be a symlink")
    if not _is_safe_directory(root):
        raise TestScratchError(
            f"{ENV_RUN_ROOT} is not a real directory owned by this user"
        )
    scratch = Path(scratch_root).resolve()
    resolved = root.resolve()
    if resolved != scratch and scratch not in resolved.parents:
        raise TestScratchError(
            f"{ENV_RUN_ROOT} must resolve beneath {ENV_SCRATCH_ROOT}"
        )

    manifest = read_run_manifest(resolved)
    _require_manifest_identity(manifest, resolved, project=project, phase=phase)
    if manifest.get("state") != "running":
        raise TestScratchError(
            "inherited run is not running; its owner already finished it"
        )
    return resolved, manifest


def validate_inherited_run_root(run_root: Path, scratch_root: Path, *,
                                project: str,
                                phase: str | None = None) -> Path:
    """Accept an inherited run root only when it is this project's own run.

    The expected project — and the phase, when the caller supplies one — are
    explicit parameters rather than values read back out of the manifest after
    the fact, so the check cannot agree with whatever it happens to find.
    """
    resolved, _ = _validated_inherited_run(
        run_root, scratch_root, project=project, phase=phase
    )
    return resolved






def _borrow_inherited_run(
    inherited: str,
    scratch_root: Path,
    *,
    project: str,
    phase: str | None,
) -> TestScratchLayout:
    run_root, manifest = _validated_inherited_run(
        Path(inherited), scratch_root, project=project, phase=phase
    )
    inherited_phase = manifest.get("phase")
    if not isinstance(inherited_phase, str) or not inherited_phase:
        raise TestScratchError("run manifest phase is invalid")
    return TestScratchLayout(
        run_root, scratch_root, allocated=False,
        project=project, phase=inherited_phase,
    ).create()


def establish_run(environ=None, *, project: str | None = None,
                  phase: str | None = None) -> TestScratchLayout:
    """Return the layout for this test run, reusing an inherited run root.

    Called by both ``tools/run_tests.py`` and the common pytest conftest. When
    a valid ``REPOMAP_TEST_RUN_ROOT`` is already exported, it is reused, so a
    direct pytest invocation under the runner never creates a second root.
    """
    env = os.environ if environ is None else environ
    scratch_root = select_scratch_root(env)
    expected_project = project or env.get(ENV_PROJECT) or DEFAULT_PROJECT
    # Only an explicitly supplied or exported phase is enforced on inheritance;
    # the default is a placeholder, not a claim about who owns the run.
    expected_phase = phase or env.get(ENV_PHASE)

    inherited = env.get(ENV_RUN_ROOT)
    if inherited:
        return _borrow_inherited_run(
            inherited, scratch_root,
            project=expected_project, phase=expected_phase,
        )

    run_phase = expected_phase or DEFAULT_PHASE
    run_root = allocate_run_root(scratch_root)
    layout = TestScratchLayout(
        run_root, scratch_root, allocated=True,
        project=expected_project, phase=run_phase,
    ).create()
    from repomap_test_support.resource_lifecycle_claim import (
        ClaimPurpose,
        lifecycle_claim,
    )

    with lifecycle_claim(
        scratch_root,
        expected_project,
        run_root.name,
        ClaimPurpose.MONITORING_REGISTRATION,
    ):
        index = None
        try:
            index = _monitoring_index(
                scratch_root, expected_project, run_phase, run_root
            )
            _write_manifest(layout, expected_project, run_phase, index)
        except BaseException as error:
            if index is not None and index.is_symlink():
                try:
                    if index.resolve() == run_root.resolve():
                        index.unlink()
                except OSError as cleanup_error:
                    error.add_note(
                        f"monitoring registration rollback also failed: {cleanup_error}"
                    )
            raise
    return layout


def _write_manifest(layout: TestScratchLayout, project: str, phase: str,
                    index: Path) -> None:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project": project,
        "phase": phase,
        "run_kind": "test",
        "run_id": layout.run_root.name,
        "pid": os.getpid(),
        "physical_run_root": str(layout.run_root),
        "monitoring_index_path": str(index),
        "state": "running",
        "retention_policy": "operator_review",
    }
    layout.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def finalize_run(layout: TestScratchLayout, result: str, *,
                 exit_status: int, live_runtime_residue: bool = False) -> None:
    """Mark the run terminal.

    Idempotent for an identical result; fails closed on a conflicting one, so a
    run cannot be quietly reclassified after the fact.

    The manifest is re-read and revalidated immediately before the write. Time
    passes between allocation and finalization, and this is the last moment at
    which the file on disk can still be shown to be the run this layout owns.
    Only that one exact manifest is ever written; the shared run directory is
    never enumerated to find others to close.
    """
    if result not in _TERMINAL_STATES:
        raise TestScratchError(f"unknown terminal result: {result}")
    if not layout.allocated:
        # Inherited run: the allocating process owns the terminal state.
        return

    manifest = read_run_manifest(layout.run_root)
    _require_manifest_identity(manifest, layout.run_root, project=layout.project)

    existing = manifest.get("state")
    if existing in _TERMINAL_STATES:
        if existing == result and manifest.get("exit_status") == exit_status:
            return
        raise TestScratchError(
            f"conflicting terminal state: {existing} then {result}"
        )
    if existing != "running":
        raise TestScratchError(f"run is not running; state is {existing!r}")

    manifest.update(
        {
            "state": result,
            "exit_status": exit_status,
            "live_runtime_residue": live_runtime_residue,
            "retention_policy": "operator_review",
        }
    )
    layout.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
