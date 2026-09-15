"""Controlled executable-authority fixtures for coordinator unit tests.

Semantic unit tests must not consume the host's Python or PostgreSQL
packaging. These helpers build an explicitly moded tree under a test-owned
temporary directory so the security properties the coordinator validates are
stated by the test rather than inherited from the machine.
"""

from __future__ import annotations

import os
import shutil
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch


PSQL_NAME = "psql.exe" if os.name == "nt" else "psql"
# No ``.exe`` suffix on any platform: the contract's approved-interpreter
# pattern matches ``python`` plus a version, and a suffixed name never does.
PYTHON_NAME = "python3"

# ``contract._executable_sha256`` refuses a zero-length file, so every fixture
# executable carries bytes that can actually be digested.
_FIXTURE_CONTENT = "#!/usr/bin/env false\n"


def private_bin_directory(root: Path, name: str = "bin") -> Path:
    """Create a search-path directory that is not group- or other-writable."""

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o755)
    return directory


def approved_psql(root: Path, *, name: str = PSQL_NAME) -> Path:
    """Create an approved, executable, non-group/other-writable psql file."""

    return _approved_executable(root, name)


def approved_python(root: Path, *, name: str = PYTHON_NAME) -> Path:
    """Create an approved, executable, non-group/other-writable interpreter."""

    return _approved_executable(root, name)


def search_path_for(executable: Path) -> tuple[Path, ...]:
    """Return the exact controlled search path for a fixture executable."""

    return (executable.parent,)


@dataclass(frozen=True)
class ControlledServiceAuthority:
    """The fixture paths a service-package spec is built from."""

    python_path: Path
    psql_path: Path


@contextmanager
def controlled_service_authority(root: Path) -> Iterator[ControlledServiceAuthority]:
    """Pin service-package executable authority to test-owned fixtures.

    ``contract`` reads exactly one attribute from each of ``sys`` and
    ``shutil``, so the module references are replaced rather than the shared
    stdlib modules mutated.
    """

    from repomap_kg.service_package import contract

    python_path = _real(approved_python(root))
    psql_path = _real(approved_psql(root))

    def which(name: str) -> str | None:
        return str(psql_path) if name == PSQL_NAME else None

    with (
        patch.object(contract, "sys", SimpleNamespace(executable=str(python_path))),
        patch.object(contract, "shutil", SimpleNamespace(which=which)),
    ):
        yield ControlledServiceAuthority(python_path=python_path, psql_path=psql_path)


def controlled_psql_copy(root: Path) -> Path:
    """Copy the host's PostgreSQL client to a test-owned, safely moded path.

    Integration tests need a client that really runs, but must not inherit the
    packaging mode of the host's copy. Copying the resolved target under the
    approved ``psql`` name preserves wrapper argv[0] dispatch.
    """

    source = shutil.which(PSQL_NAME)
    if source is None:
        raise unittest.SkipTest("missing PostgreSQL client for refresh authority")
    target = private_bin_directory(root, "psql-authority") / PSQL_NAME
    shutil.copyfile(Path(source).resolve(strict=True), target)
    target.chmod(0o444 if os.name == "nt" else 0o755)
    return target


def _approved_executable(root: Path, name: str) -> Path:
    path = private_bin_directory(root) / name
    path.write_text(_FIXTURE_CONTENT, encoding="utf-8")
    path.chmod(0o444 if os.name == "nt" else 0o755)
    return path


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


__all__ = [
    "PSQL_NAME",
    "PYTHON_NAME",
    "ControlledServiceAuthority",
    "approved_psql",
    "approved_python",
    "controlled_psql_copy",
    "controlled_service_authority",
    "private_bin_directory",
    "search_path_for",
]
