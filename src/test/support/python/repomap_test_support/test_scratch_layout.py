"""Scratch path layout, monitoring links, and byte-budgeted socket directories."""

from __future__ import annotations

import os
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from repomap_test_support.test_scratch_contract import (
    DEFAULT_PROJECT, DEFAULT_PHASE, MAX_SOCKET_PATH_BYTES,
)

@dataclass(frozen=True)
class TestScratchLayout:
    """One immutable set of short physical paths for a single test run."""

    # Not a test class; see TestScratchError.
    __test__ = False

    run_root: Path
    scratch_root: Path
    # True only for the process that allocated this run root. A nested caller
    # that inherited it must not mark it terminal: the allocator owns the
    # lifecycle, and the runner's own tests invoke main() repeatedly inside one
    # outer run.
    allocated: bool = False
    # Carried so finalization can revalidate the manifest it is about to write
    # without guessing the identity back out of that same manifest.
    project: str = DEFAULT_PROJECT
    phase: str = DEFAULT_PHASE

    @property
    def manifest(self) -> Path:
        return self.run_root / "manifest.json"

    @property
    def tmp(self) -> Path:
        return self.run_root / "tmp"

    @property
    def pytest_basetemp(self) -> Path:
        return self.run_root / "pt"

    @property
    def pycache(self) -> Path:
        return self.run_root / "pyc"

    @property
    def go_tmp(self) -> Path:
        return self.run_root / "go" / "t"

    @property
    def go_cache(self) -> Path:
        return self.run_root / "go" / "c"

    @property
    def golangci_cache(self) -> Path:
        return self.run_root / "go" / "l"

    @property
    def pip_cache(self) -> Path:
        return self.run_root / "pip"

    @property
    def buildx_config(self) -> Path:
        return self.run_root / "bx"

    @property
    def logs(self) -> Path:
        return self.run_root / "logs"

    @property
    def socket_directories(self) -> Path:
        """Owned top-level group for byte-budgeted coordinator layouts."""
        return self.run_root / "s"

    def directories(self) -> tuple[Path, ...]:
        return (
            self.tmp,
            self.pytest_basetemp,
            self.pycache,
            self.go_tmp,
            self.go_cache,
            self.golangci_cache,
            self.pip_cache,
            self.buildx_config,
            self.logs,
            self.socket_directories,
        )

    def create(self) -> "TestScratchLayout":
        for directory in self.directories():
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self

    def child_environment(self) -> dict[str, str]:
        """The complete environment every child process must receive."""
        from repomap_test_support import test_scratch as owner

        return {
            "TMPDIR": str(self.tmp),
            "TMP": str(self.tmp),
            "TEMP": str(self.tmp),
            "PYTHONPYCACHEPREFIX": str(self.pycache),
            "GOTMPDIR": str(self.go_tmp),
            "GOCACHE": str(self.go_cache),
            "GOLANGCI_LINT_CACHE": str(self.golangci_cache),
            "PIP_CACHE_DIR": str(self.pip_cache),
            "BUILDX_CONFIG": str(self.buildx_config),
            "PYTHONDONTWRITEBYTECODE": "1",
            owner.ENV_SCRATCH_ROOT: str(self.scratch_root),
            owner.ENV_RUN_ROOT: str(self.run_root),
            owner.ENV_PROJECT: self.project,
            owner.ENV_PHASE: self.phase,
        }

    def apply(self) -> "TestScratchLayout":
        """Install the layout into this process.

        ``tempfile.tempdir`` is reset explicitly: an earlier
        ``tempfile.gettempdir()`` call caches its answer, and without this a
        cached value would silently outrank the new ``TMPDIR``.
        """
        os.environ.update(self.child_environment())
        # Spawned Python children receive no-bytecode at interpreter bootstrap.
        tempfile.tempdir = str(self.tmp)
        return self


def _monitoring_index(scratch_root: Path, project: str, phase: str,
                      run_root: Path) -> Path:
    """Return this run's monitoring symlink, failing closed on any collision.

    An existing path is reused only when it is provably the intended symlink to
    this exact run. Anything else — a regular file, a real directory, a dangling
    link, a link to another run, a link out of the scratch root — is a genuine
    collision. Overwriting or silently reusing one would hide a run behind
    another's name, so it raises instead. The error is never swallowed into
    ``None``: a monitoring index that quietly does nothing is worse than none.
    """
    from repomap_test_support import test_scratch as owner

    scratch = Path(scratch_root).resolve()
    index = Path(scratch_root) / "index" / project / phase
    try:
        index.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise owner.TestScratchError(
            "could not create the monitoring index directory"
        ) from error
    link = index / run_root.name

    if link.is_symlink():
        if not link.exists():
            raise owner.TestScratchError(
                "monitoring index entry is a dangling symlink"
            )
        target = link.resolve()
        if scratch not in target.parents:
            raise owner.TestScratchError(
                "monitoring index entry points outside the scratch root"
            )
        if target != run_root.resolve():
            raise owner.TestScratchError(
                "monitoring index entry already points at another run"
            )
        return link
    if link.exists():
        raise owner.TestScratchError(
            "monitoring index entry exists and is not a symlink"
        )

    depth = len(link.relative_to(scratch_root).parts) - 1
    try:
        link.symlink_to(Path(*([".."] * depth)) / "r" / run_root.name)
    except OSError as error:
        raise owner.TestScratchError(
            "could not create the monitoring index entry"
        ) from error
    return link


def socket_component_byte_capacity(
    parent: Path,
    required_relative_suffix: str,
    *,
    maximum_path_bytes: int = MAX_SOCKET_PATH_BYTES,
) -> int:
    """Return available owned-component bytes or refuse an impossible path."""
    from repomap_test_support import test_scratch as owner

    suffix = Path(required_relative_suffix)
    if (
        not required_relative_suffix
        or suffix.is_absolute()
        or ".." in suffix.parts
    ):
        raise owner.TestScratchError("required socket suffix must be a safe relative path")
    one_byte_shape = Path(parent) / "x" / suffix
    fixed_bytes = len(os.fsencode(str(one_byte_shape))) - 1
    capacity = maximum_path_bytes - fixed_bytes
    if capacity < 1:
        raise owner.TestScratchError(
            "socket path budget is mathematically impossible: encoded bytes "
            "beneath the selected run root exceed the limit"
        )
    return capacity


@contextmanager
def short_test_directory(
    prefix: str,
    longest_relative_socket_path: str,
    layout: TestScratchLayout | None = None,
    *,
    maximum_path_bytes: int = MAX_SOCKET_PATH_BYTES,
):
    """Yield a short directory sized for a caller's longest socket path.

    The caller passes the longest path it will actually create beneath the
    directory, relative to it. The check counts encoded bytes rather than
    characters, because ``sun_path`` is a byte buffer.
    """
    from repomap_test_support import test_scratch as owner

    active = layout or owner.establish_run()
    parent = active.socket_directories
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    lead = next(
        (
            character.lower()
            for character in prefix
            if character.isascii() and character.isalnum()
        ),
        "s",
    )
    capacity = owner.socket_component_byte_capacity(
        parent,
        longest_relative_socket_path,
        maximum_path_bytes=maximum_path_bytes,
    )
    component_length = min(4, capacity)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    for _attempt in range(128):
        if component_length == 1:
            candidates = lead + alphabet.replace(lead, "")
            name = candidates[_attempt % len(candidates)]
        else:
            random_part = "".join(
                secrets.choice(alphabet) for _ in range(component_length - 1)
            )
            name = lead + random_part
        directory = parent / name
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            continue
        break
    else:
        raise owner.TestScratchError("could not allocate a unique short test directory")
    actual_path = directory / longest_relative_socket_path
    encoded = len(os.fsencode(str(actual_path)))
    if encoded > maximum_path_bytes:
        directory.rmdir()
        raise owner.TestScratchError(
            "created socket path is %d encoded bytes, over the %d-byte limit"
            % (encoded, maximum_path_bytes)
        )
    try:
        yield directory
    finally:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
