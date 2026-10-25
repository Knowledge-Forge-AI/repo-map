"""Containerized integration tests for CI pg_config diversion custody using real dpkg-divert (ADR 0093).

These tests invoke the container's real ``dpkg-divert`` and ``dpkg --print-architecture`` binaries
against a test-owned temporary ``--admindir`` and ``--instdir`` under ``tmp_path``, verifying that
``/var/lib/dpkg`` is never mutated. They exercise ``psycopg_pg_config_custody._verify_diversion_records``
directly against real ``dpkg-divert`` database state with a strict runner that returns only explicit
minimal ``dpkg-query`` ownership/listing fixtures and raises on any unexpected command. Full bootstrap,
build-child binding, and defensive owner-level chained-truename branches remain in unit test owners.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

import pytest

from ci import psycopg_pg_config_custody as custody

_SYSTEM_DPKG_FILES: tuple[Path, ...] = (
    Path("/var/lib/dpkg/diversions"),
    Path("/var/lib/dpkg/status"),
)
_ORIGINAL_PG_CONFIG_SCRIPT = (
    b"#!/bin/sh\n"
    b'case "$1" in\n'
    b'  --includedir) echo "/usr/include/postgresql" ;;\n'
    b'  --libdir) echo "/usr/lib/postgresql-test" ;;\n'
    b'  --version) echo "PostgreSQL 17.10 (Debian 17.10-1)" ;;\n'
    b"  *) exit 64 ;;\n"
    b"esac\n"
)


def _snapshot_system_dpkg() -> dict[Path, tuple[int, int, int, int, str]]:
    snap: dict[Path, tuple[int, int, int, int, str]] = {}
    for path in _SYSTEM_DPKG_FILES:
        st = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snap[path] = (int(st.st_dev), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns), digest)
    return snap


def _real_native_arch() -> str:
    arch = subprocess.run(
        ["dpkg", "--print-architecture"],
        capture_output=True,
        text=True,
        check=True,
        env=custody.controlled_env(),
    ).stdout.strip()
    assert arch and arch != "all"
    return arch


def _init_temp_dpkg_tree(base: Path) -> tuple[Path, Path]:
    admindir = base / "admindir"
    admindir.mkdir(parents=True, exist_ok=True)
    (admindir / "updates").mkdir(exist_ok=True)
    (admindir / "diversions").write_text("", encoding="utf-8")
    (admindir / "status").write_text("", encoding="utf-8")

    instdir = base / "instdir"
    usr_bin = instdir / "usr/bin"
    usr_bin.mkdir(parents=True, exist_ok=True)
    orig = usr_bin / "pg_config"
    orig.write_bytes(_ORIGINAL_PG_CONFIG_SCRIPT)
    orig.chmod(0o755)
    return admindir, instdir


def _run_real_dpkg_divert(
    admindir: Path, instdir: Path, args: list[str], *, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = ["dpkg-divert", "--admindir", str(admindir), "--instdir", str(instdir), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=custody.controlled_env(env),
    )


def _minimal_installed_managers(
    *,
    manager: str = "postgresql-common",
    status: str = "ii",
    architecture: str = "all",
    version: str = "278",
) -> dict[str, dict[str, str]]:
    if not manager:
        return {}
    return {
        f"{manager}:{architecture}": {
            "name": manager,
            "architecture": architecture,
            "version": version,
            "status": status,
            "source": manager,
            "source_version": version,
        }
    }


def _make_strict_divert_custody_runner(
    admindir: Path,
    instdir: Path,
    arch: str,
    *,
    manager: str = "postgresql-common",
) -> tuple[Callable[..., subprocess.CompletedProcess[str]], list[list[str]]]:
    query_fixtures: dict[tuple[str, ...], tuple[int, str]] = {
        ("dpkg-query", "-S", "/usr/bin/pg_config"): (
            0,
            (
                f"diversion by {manager} from: /usr/bin/pg_config\n"
                f"diversion by {manager} to: /usr/bin/pg_config.libpq-dev\n"
                f"libpq-dev:{arch}, {manager}: /usr/bin/pg_config\n"
            ),
        ),
        ("dpkg-query", "-S", "/usr/bin/pg_config.libpq-dev"): (1, ""),
        ("dpkg-query", "-L", "libpq-dev"): (
            0,
            "/usr/bin/pg_config\n/usr/include/postgresql/libpq-fe.h\n",
        ),
    }
    real_divert_calls: list[list[str]] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        env = options.get("env")
        key = tuple(command)
        if len(command) == 3 and command[0] == "dpkg-divert" and command[1] in ("--listpackage", "--truename"):
            real_divert_calls.append(list(command))
            return _run_real_dpkg_divert(admindir, instdir, command[1:], env=env)
        if key in query_fixtures:
            rc, stdout = query_fixtures[key]
            return subprocess.CompletedProcess(list(command), rc, stdout, "")
        raise AssertionError(f"unexpected command in strict custody runner: {command!r}")

    return run, real_divert_calls


def test_real_dpkg_divert_positive_pair_cli_chain_refusal_and_verify_diversion_records(
    tmp_path: Path,
) -> None:
    before_sys = _snapshot_system_dpkg()
    arch = _real_native_arch()

    admindir, instdir = _init_temp_dpkg_tree(tmp_path / "valid")
    add_res = _run_real_dpkg_divert(
        admindir,
        instdir,
        [
            "--package",
            "postgresql-common",
            "--divert",
            "/usr/bin/pg_config.libpq-dev",
            "--rename",
            "--add",
            "/usr/bin/pg_config",
        ],
    )
    assert add_res.returncode == 0, add_res.stderr
    relocated = instdir / "usr/bin/pg_config.libpq-dev"
    assert relocated.is_file() and relocated.read_bytes() == _ORIGINAL_PG_CONFIG_SCRIPT
    assert not (instdir / "usr/bin/pg_config").exists()

    src_pkg = _run_real_dpkg_divert(admindir, instdir, ["--listpackage", "/usr/bin/pg_config"])
    src_true = _run_real_dpkg_divert(admindir, instdir, ["--truename", "/usr/bin/pg_config"])
    dst_pkg = _run_real_dpkg_divert(admindir, instdir, ["--listpackage", "/usr/bin/pg_config.libpq-dev"])
    dst_true = _run_real_dpkg_divert(admindir, instdir, ["--truename", "/usr/bin/pg_config.libpq-dev"])
    assert src_pkg.returncode == 0 and src_pkg.stdout == "postgresql-common\n"
    assert src_true.returncode == 0 and src_true.stdout == "/usr/bin/pg_config.libpq-dev\n"
    assert dst_pkg.returncode == 0 and dst_pkg.stdout == "postgresql-common\n"
    assert dst_true.returncode == 0 and dst_true.stdout == "/usr/bin/pg_config.libpq-dev\n"

    diversions_before = (admindir / "diversions").read_text(encoding="utf-8")
    chain_res = _run_real_dpkg_divert(
        admindir,
        instdir,
        [
            "--package",
            "postgresql-common",
            "--divert",
            "/usr/bin/pg_config.chained",
            "--no-rename",
            "--add",
            "/usr/bin/pg_config.libpq-dev",
        ],
    )
    redivert_res = _run_real_dpkg_divert(
        admindir,
        instdir,
        [
            "--package",
            "custom-pkg",
            "--divert",
            "/usr/bin/pg_config.other",
            "--no-rename",
            "--add",
            "/usr/bin/pg_config",
        ],
    )
    assert chain_res.returncode != 0 and chain_res.stderr.strip() != ""
    assert redivert_res.returncode != 0 and redivert_res.stderr.strip() != ""
    assert (admindir / "diversions").read_text(encoding="utf-8") == diversions_before

    installed = _minimal_installed_managers(manager="postgresql-common")
    run, divert_calls = _make_strict_divert_custody_runner(admindir, instdir, arch)
    mgr, mgr_row, truename = custody._verify_diversion_records(
        run, installed, "/usr/bin/pg_config", arch
    )
    assert mgr == "postgresql-common"
    assert mgr_row == installed["postgresql-common:all"]
    assert truename == "/usr/bin/pg_config.libpq-dev"
    assert divert_calls == [
        ["dpkg-divert", "--listpackage", "/usr/bin/pg_config"],
        ["dpkg-divert", "--truename", "/usr/bin/pg_config"],
        ["dpkg-divert", "--listpackage", "/usr/bin/pg_config.libpq-dev"],
        ["dpkg-divert", "--truename", "/usr/bin/pg_config.libpq-dev"],
    ]
    with pytest.raises(AssertionError, match="unexpected command in strict custody runner"):
        run(["/usr/bin/pg_config", "--version"])

    admindir_dev, instdir_dev = _init_temp_dpkg_tree(tmp_path / "valid_dev")
    add_dev_res = _run_real_dpkg_divert(
        admindir_dev,
        instdir_dev,
        [
            "--package",
            "postgresql-common-dev",
            "--divert",
            "/usr/bin/pg_config.libpq-dev",
            "--rename",
            "--add",
            "/usr/bin/pg_config",
        ],
    )
    assert add_dev_res.returncode == 0, add_dev_res.stderr
    installed_dev = _minimal_installed_managers(manager="postgresql-common-dev", architecture=arch)
    run_dev, divert_dev_calls = _make_strict_divert_custody_runner(
        admindir_dev, instdir_dev, arch, manager="postgresql-common-dev"
    )
    mgr_dev, mgr_dev_row, truename_dev = custody._verify_diversion_records(
        run_dev, installed_dev, "/usr/bin/pg_config", arch
    )
    assert mgr_dev == "postgresql-common-dev"
    assert mgr_dev_row == installed_dev[f"postgresql-common-dev:{arch}"]
    assert truename_dev == "/usr/bin/pg_config.libpq-dev"
    assert len(divert_dev_calls) == 4
    assert _snapshot_system_dpkg() == before_sys


@pytest.mark.parametrize(
    "case_name,divert_args,manager_installed,extra_diversions_text,expected_match",
    [
        ("missing_diversion", None, True, None, "refusing local or missing dpkg-divert manager"),
        (
            "local_diversion",
            ["--local", "--divert", "/usr/bin/pg_config.libpq-dev", "--no-rename", "--add", "/usr/bin/pg_config"],
            True,
            None,
            "refusing local or missing dpkg-divert manager",
        ),
        (
            "unknown_manager",
            [
                "--package", "custom-pkg", "--divert", "/usr/bin/pg_config.libpq-dev",
                "--no-rename", "--add", "/usr/bin/pg_config",
            ],
            True,
            None,
            "unknown dpkg-divert manager",
        ),
        (
            "uninstalled_manager",
            [
                "--package", "postgresql-common", "--divert", "/usr/bin/pg_config.libpq-dev",
                "--no-rename", "--add", "/usr/bin/pg_config",
            ],
            False,
            None,
            "diversion manager postgresql-common is not installed",
        ),
        (
            "unexpected_truename",
            [
                "--package", "postgresql-common", "--divert", "/usr/bin/pg_config.other",
                "--no-rename", "--add", "/usr/bin/pg_config",
            ],
            True,
            None,
            "dpkg-divert truename for /usr/bin/pg_config",
        ),
        (
            "malformed_diversions_db",
            None,
            True,
            "/usr/bin/pg_config\nonly-two-lines\n",
            "dpkg-divert --listpackage <path> failed with exit 2",
        ),
        (
            "chained_target_db_entry",
            [
                "--package", "postgresql-common", "--divert", "/usr/bin/pg_config.libpq-dev",
                "--no-rename", "--add", "/usr/bin/pg_config",
            ],
            True,
            "/usr/bin/pg_config.libpq-dev\n/usr/bin/pg_config.chained\npostgresql-common\n",
            "dpkg-divert --listpackage <path> failed with exit 2",
        ),
    ],
    ids=[
        "missing_diversion",
        "local_diversion",
        "unknown_manager",
        "uninstalled_manager",
        "unexpected_truename",
        "malformed_diversions_db",
        "chained_target_db_entry",
    ],
)
def test_real_dpkg_divert_and_custody_refusal_boundaries(
    tmp_path: Path,
    case_name: str,
    divert_args: list[str] | None,
    manager_installed: bool,
    extra_diversions_text: str | None,
    expected_match: str,
) -> None:
    before_sys = _snapshot_system_dpkg()
    arch = _real_native_arch()
    admindir, instdir = _init_temp_dpkg_tree(tmp_path / case_name)
    if divert_args is not None:
        res = _run_real_dpkg_divert(admindir, instdir, divert_args)
        assert res.returncode == 0, res.stderr
    if extra_diversions_text is not None:
        div_file = admindir / "diversions"
        div_file.write_text(div_file.read_text(encoding="utf-8") + extra_diversions_text, encoding="utf-8")

    installed = (
        _minimal_installed_managers(manager="postgresql-common")
        if manager_installed
        else _minimal_installed_managers(manager="")
    )
    run, divert_calls = _make_strict_divert_custody_runner(admindir, instdir, arch)
    with pytest.raises(custody.CustodyError, match=expected_match):
        custody._verify_diversion_records(run, installed, "/usr/bin/pg_config", arch)
    assert divert_calls
    assert _snapshot_system_dpkg() == before_sys
