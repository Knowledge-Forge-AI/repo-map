from __future__ import annotations

import importlib.metadata
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg import pq
import psycopg_c
import pytest

from ci.bootstrap_pre_review import verify_python_distribution


def test_sandbox_c_psycopg_distribution_attestation_succeeds_in_fresh_child_python() -> None:
    python_bin = Path(sys.executable)
    owner_root = Path(sys.prefix).resolve()

    assert importlib.metadata.version("psycopg") == "3.3.6"
    assert importlib.metadata.version("psycopg-c") == "3.3.6"
    assert pq.__impl__ == "c"
    assert psycopg.__file__ is not None
    assert psycopg_c.__file__ is not None
    assert Path(psycopg.__file__).resolve().is_relative_to(owner_root)
    assert Path(psycopg_c.__file__).resolve().is_relative_to(owner_root)

    verify_python_distribution(python_bin, "psycopg", "psycopg", "3.3.6", owner_root)
    verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.6", owner_root)


def test_sandbox_c_psycopg_distribution_attestation_refuses_wrong_version() -> None:
    python_bin = Path(sys.executable)
    owner_root = Path(sys.prefix).resolve()

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg-c",
    ):
        verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.5", owner_root)

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg",
    ):
        verify_python_distribution(python_bin, "psycopg", "psycopg", "3.3.5", owner_root)


def test_sandbox_c_psycopg_distribution_attestation_refuses_wrong_owner_root(
    tmp_path: Path,
) -> None:
    python_bin = Path(sys.executable)
    wrong_root = tmp_path / "wrong-owner-root"
    wrong_root.mkdir()

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg-c",
    ):
        verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.6", wrong_root)

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg",
    ):
        verify_python_distribution(python_bin, "psycopg", "psycopg", "3.3.6", wrong_root)


def test_sandbox_c_psycopg_distribution_attestation_refuses_missing_module_or_distribution() -> None:
    python_bin = Path(sys.executable)
    owner_root = Path(sys.prefix).resolve()

    with pytest.raises(subprocess.CalledProcessError):
        verify_python_distribution(
            python_bin,
            "repomap_nonexistent_module_ci65",
            "psycopg-c",
            "3.3.6",
            owner_root,
        )

    with pytest.raises(subprocess.CalledProcessError):
        verify_python_distribution(
            python_bin,
            "psycopg_c",
            "repomap-nonexistent-dist-ci65",
            "3.3.6",
            owner_root,
        )
