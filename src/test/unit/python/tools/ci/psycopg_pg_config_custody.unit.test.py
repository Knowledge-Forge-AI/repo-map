"""Unit tests for CI-only pg_config custody, known diversion proof, and build-child binding."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import pytest

from ci import psycopg_bootstrap as bootstrap
from ci import psycopg_pg_config_custody as custody
from src.test.unit.python.tools.ci.psycopg_custody_fixture import (
    DEFAULT_LISTINGS,
    DEFAULT_MD5SUMS,
    DEFAULT_OWNERS,
    DIVERTED_USR_BIN,
    LIBPQ_DEV_ORIGINAL_MD5,
    LIBPQ_DEV_ORIGINAL_SHA256,
    format_rows,
    install_host_paths,
    make_runner,
    make_which,
)


class _RunnerOverrides(TypedDict, total=False):
    native_arch: str
    packages: str
    owners: dict[str, str]
    diversions: dict[str, str]
    divert_managers: dict[str, str]
    divert_truenames: dict[str, str]
    listings: dict[str, str]
    md5sums: str


@pytest.mark.parametrize(
    "tool_out,pkg_ver,src_ver,expected",
    [
        ("PostgreSQL 17.10", "17.10-1", "17.10-1", True),
        ("PostgreSQL 17.10 (Debian 17.10-1+b2)", "1:17.10-1+b2", "1:17.10-1", True),
        ("PostgreSQL 17.10 (Debian 17.10-1.pgdg120+1)", "17.10-1.pgdg120+1", "17.10-1.pgdg120+1", True),
        ("PostgreSQL 16.8 (Ubuntu 16.8-0ubuntu0.24.04.1)", "16.8-0ubuntu0.24.04.1", "16.8-0ubuntu0.24.04.1", True),
        ("PostgreSQL 17.10~rc1", "17.10~rc1-1", "17.10~rc1-1", True),
        ("PostgreSQL 17.10", "17.10+b1", "17.10", True),
        ("PostgreSQL 18.1", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (Debian 18.1-1)", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (Debian)", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (17.10-1)", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (Debian 17.10-1 extra)", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (Custom 17.10-1)", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10 (Debian :17.10-1)", "17.10-1", "17.10-1", False),
        ("EnterpriseDB 17.10", "17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10", ":17.10-1", "17.10-1", False),
        ("PostgreSQL 17.10", "", "17.10-1", False),
    ],
)
def test_version_comparator_handles_debian_epochs_rebuilds_and_mismatches(
    tool_out: str, pkg_ver: str, src_ver: str, expected: bool
) -> None:
    assert custody.pg_config_version_matches_package(tool_out, pkg_ver, src_ver) is expected


def test_known_diversion_succeeds_without_sibling_client_package_and_preserves_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_host_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("CALLER_SENTINEL", "untouched")
    monkeypatch.setenv("PSYCOPG_IMPL", "binary")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    before_env = dict(os.environ)

    pkgs = format_rows(**{"postgresql-client-17": ("17.10-1", "rc", "postgresql-17")})
    seen: list[tuple[Path, Path | None]] = []
    run, calls = make_runner(
        packages=pkgs, diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN}, pip_path_links=seen
    )
    ev = bootstrap.bootstrap("/py", run, make_which("/usr/bin/pg_config"))
    assert dict(os.environ) == before_env

    native = ev["native"]
    assert isinstance(native, dict)
    assert native["pg_config_executable"] == {
        "package": "libpq-dev", "package_version": "17.10-1",
        "path": "/usr/bin/pg_config.libpq-dev", "realpath": "/usr/bin/pg_config.libpq-dev",
        "version": "PostgreSQL 17.10",
    }
    rec = native["custody"]
    assert isinstance(rec, dict) and rec["route"] == "dpkg_divert_libpq_dev_original"
    assert rec["original_path"] == "/usr/bin/pg_config" and rec["diversion_manager"] == "postgresql-common"
    assert rec["destination"] == "/usr/bin/pg_config.libpq-dev"
    assert rec["control_entry"] == {"path": "usr/bin/pg_config", "md5": LIBPQ_DEV_ORIGINAL_MD5}
    assert rec["local_integrity_method"] == "local_installed_package_md5sums_plus_sha256"
    assert rec["sha256"] == LIBPQ_DEV_ORIGINAL_SHA256

    assert "/usr/bin/pg_config" not in [cmd[0] for cmd, _ in calls]
    md5_i = next(i for i, (c, _) in enumerate(calls) if c[:3] == ["dpkg-query", "--control-show", "libpq-dev"])
    pg_i = next(i for i, (c, _) in enumerate(calls) if c[0] == "/usr/bin/pg_config.libpq-dev")
    assert md5_i < pg_i
    div_envs = [env for cmd, env in calls if cmd[0] in ("dpkg-divert", "dpkg-query") and env]
    assert all(
        env.get("LC_ALL") == "C.UTF-8" and env.get("LANGUAGE") == ""
        for env in div_envs
        if "LC_ALL" in env and env["LC_ALL"] != "C"
    )
    assert len(seen) == 3
    for temp_bin, target in seen:
        assert target == Path("/usr/bin/pg_config.libpq-dev")
        assert not temp_bin.exists() and not temp_bin.parent.exists()


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"native_arch": ""}, "native architecture is unknown"),
        ({"native_arch": "all"}, "native architecture is unknown"),
        ({"native_arch": "INVALID_ARCH!"}, "native architecture is unknown"),
        ({"native_arch": "amd64"}, "architecture mismatch against native amd64"),
        (
            {"packages": format_rows(**{"libpq-dev": ("17.10-1", "ii", "postgresql-17", "17.10-1", "amd64")})},
            "architecture mismatch against native arm64",
        ),
        ({"divert_managers": {"/usr/bin/pg_config": "LOCAL"}}, "local or missing"),
        ({"divert_managers": {"/usr/bin/pg_config": ""}}, "local or missing"),
        ({"divert_managers": {"/usr/bin/pg_config": "custom-pkg"}}, "unknown dpkg-divert manager"),
        (
            {"packages": format_rows(**{"postgresql-common": ("278", "rc", "postgresql-common")})},
            "diversion manager postgresql-common is not installed",
        ),
        ({"divert_truenames": {"/usr/bin/pg_config": "/usr/bin/pg_config.evil"}}, "dpkg-divert truename"),
        ({"divert_managers": {"/usr/bin/pg_config.libpq-dev": ""}}, "dpkg-divert manager for diverted target"),
        ({"divert_managers": {"/usr/bin/pg_config.libpq-dev": "LOCAL"}}, "dpkg-divert manager for diverted target"),
        (
            {"divert_managers": {"/usr/bin/pg_config.libpq-dev": "postgresql-common-dev"}},
            "dpkg-divert manager for diverted target",
        ),
        (
            {"divert_managers": {"/usr/bin/pg_config.libpq-dev": "custom-pkg"}},
            "dpkg-divert manager for diverted target",
        ),
        ({"divert_truenames": {"/usr/bin/pg_config.libpq-dev": "/usr/bin/pg_config.chained"}}, "itself diverted"),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": (
                        "diversion by postgresql-common from: /usr/bin/pg_config\n"
                        "diversion by postgresql-common-dev to: /usr/bin/pg_config.libpq-dev\n"
                        "libpq-dev:arm64: /usr/bin/pg_config\n"
                    )
                }
            },
            "inconsistent dpkg-query -S diversion lines",
        ),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": (
                        "diversion by postgresql-common from: /usr/bin/pg_config\n"
                        "diversion by postgresql-common to: /usr/bin/pg_config.libpq-dev\n"
                        "postgresql-common: /usr/bin/pg_config\n"
                    )
                }
            },
            "unexpected dpkg-query -S owners",
        ),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": (
                        "diversion by postgresql-common from: /usr/bin/pg_config\n"
                        "diversion by postgresql-common to: /usr/bin/pg_config.libpq-dev\n"
                        "libpq-dev:amd64: /usr/bin/pg_config\n"
                    )
                }
            },
            "unexpected dpkg-query -S owner",
        ),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": DIVERTED_USR_BIN + "extra-pkg:arm64: /usr/bin/other\n"
                }
            },
            "unexpected dpkg-query -S record",
        ),
        (
            {"owners": {**DEFAULT_OWNERS, "/usr/bin/pg_config.libpq-dev": "postgresql-client-17"}},
            "unexpected dpkg-query -S owners for /usr/bin/pg_config.libpq-dev",
        ),
        (
            {"owners": {**DEFAULT_OWNERS, "/usr/bin/pg_config.libpq-dev": "postgresql-common"}},
            "unexpected dpkg-query -S owners for /usr/bin/pg_config.libpq-dev",
        ),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": DIVERTED_USR_BIN,
                    "/usr/bin/pg_config.libpq-dev": "LOCAL: /usr/bin/pg_config.libpq-dev\n",
                }
            },
            "unexpected dpkg-query -S owner",
        ),
        (
            {
                "diversions": {
                    "/usr/bin/pg_config": DIVERTED_USR_BIN,
                    "/usr/bin/pg_config.libpq-dev": "diversion by postgresql-common from: /usr/bin/pg_config\n",
                }
            },
            "inconsistent dpkg-query -S diversion lines for /usr/bin/pg_config.libpq-dev",
        ),
        (
            {"listings": {**DEFAULT_LISTINGS, "libpq-dev": "/usr/include/postgresql/libpq-fe.h\n"}},
            "libpq-dev file list does not contain",
        ),
        ({"md5sums": ""}, "md5sums control record is empty"),
        ({"md5sums": "not-an-md5-line\n"}, "malformed libpq-dev md5sums line"),
        ({"md5sums": f"{'b' * 32}  usr/include/postgresql/libpq-fe.h\n"}, "must contain usr/bin/pg_config"),
        ({"md5sums": DEFAULT_MD5SUMS + f"{LIBPQ_DEV_ORIGINAL_MD5}  usr/bin/pg_config\n"}, "exactly once"),
        ({"md5sums": f"{'0' * 32}  usr/bin/pg_config\n"}, "md5 mismatch"),
    ],
)
def test_known_diversion_refuses_inconsistent_metadata_before_executing_pg_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: _RunnerOverrides, message: str
) -> None:
    install_host_paths(monkeypatch, tmp_path)
    diversions = {"/usr/bin/pg_config": DIVERTED_USR_BIN}
    base: _RunnerOverrides = {"diversions": diversions, **kwargs}
    run, calls = make_runner(**base)
    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.native_prerequisites(run, make_which("/usr/bin/pg_config"))
    assert not [c for c, _ in calls if c[0].endswith("pg_config") or c[0].endswith("pg_config.libpq-dev")]


@pytest.mark.parametrize(
    "native_arch,message",
    [
        ("", "native architecture is unknown"),
        ("all", "native architecture is unknown"),
        ("amd64", "architecture mismatch against native amd64"),
    ],
)
def test_shared_route_refuses_unknown_or_foreign_dpkg_architecture_before_executing_pg_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_arch: str, message: str
) -> None:
    install_host_paths(monkeypatch, tmp_path)
    run, calls = make_runner(native_arch=native_arch)
    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.native_prerequisites(run, make_which("/usr/bin/pg_config"))
    assert not [c for c, _ in calls if c[0].endswith("pg_config")]


def test_known_diversion_accepts_coherent_target_search_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_host_paths(monkeypatch, tmp_path)
    coherent_target = (
        "diversion by postgresql-common from: /usr/bin/pg_config\n"
        "diversion by postgresql-common to: /usr/bin/pg_config.libpq-dev\n"
        "libpq-dev:arm64: /usr/bin/pg_config.libpq-dev\n"
    )
    run, _ = make_runner(
        diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN, "/usr/bin/pg_config.libpq-dev": coherent_target}
    )
    native = bootstrap.native_prerequisites(run, make_which("/usr/bin/pg_config"))
    rec = native["custody"]
    assert isinstance(rec, dict) and rec["route"] == "dpkg_divert_libpq_dev_original"


@pytest.mark.parametrize(
    "target_kind,message",
    [
        ("missing", "missing or unreadable"),
        ("symlink", "must not be a symlink"),
        ("directory", "not a regular file"),
        ("non_exec", "not executable"),
        ("empty", "is empty"),
    ],
)
def test_known_diversion_refuses_unsafe_target_file_states_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_kind: str, message: str
) -> None:
    rootfs = install_host_paths(monkeypatch, tmp_path)
    target = rootfs / "usr/bin/pg_config.libpq-dev"
    target.unlink()
    if target_kind == "symlink":
        target.symlink_to("/usr/bin/pg_config")
    elif target_kind == "directory":
        target.mkdir()
    elif target_kind == "non_exec":
        target.write_bytes(b"#!/bin/sh\n")
        target.chmod(0o644)
    elif target_kind == "empty":
        target.write_bytes(b"")
        target.chmod(0o755)

    run, calls = make_runner(diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN})
    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.native_prerequisites(run, make_which("/usr/bin/pg_config"))
    assert not [c for c, _ in calls if c[0].endswith("pg_config") or c[0].endswith("pg_config.libpq-dev")]


def test_build_binding_refuses_probe_mismatch_and_target_drift_and_cleans_up_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs = install_host_paths(monkeypatch, tmp_path)
    before_env = dict(os.environ)

    probe_links: list[tuple[Path, Path | None]] = []
    bad_run, _ = make_runner(
        diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN},
        probe_overrides={"--version": "PostgreSQL 18.1"},
        pip_path_links=probe_links,
    )
    with pytest.raises(bootstrap.BootstrapError, match="bound pg_config --version output"):
        bootstrap.bootstrap("/py", bad_run, make_which("/usr/bin/pg_config"))
    assert probe_links == [] and dict(os.environ) == before_env

    fail_run, _ = make_runner(diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN}, failing=("bound-probe",))
    with pytest.raises(bootstrap.BootstrapError, match="probe failed"):
        bootstrap.bootstrap("/py", fail_run, make_which("/usr/bin/pg_config"))
    assert dict(os.environ) == before_env

    drift_links: list[tuple[Path, Path | None]] = []
    target_file = rootfs / "usr/bin/pg_config.libpq-dev"

    def mutate_target() -> None:
        target_file.write_bytes(b"#!/bin/sh\n# drifted during build\n")
        target_file.chmod(0o755)

    drift_run, _ = make_runner(
        diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN},
        pip_path_links=drift_links,
        on_pip_install=mutate_target,
    )
    with pytest.raises(bootstrap.BootstrapError, match="drifted during build"):
        bootstrap.bootstrap("/py", drift_run, make_which("/usr/bin/pg_config"))
    assert len(drift_links) == 3
    for temp_bin, _ in drift_links:
        assert not temp_bin.exists() and not temp_bin.parent.exists()
    assert dict(os.environ) == before_env


def test_build_binding_refuses_bad_symlink_resolution_and_pre_probe_drift_before_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs = install_host_paths(monkeypatch, tmp_path)
    before_env = dict(os.environ)
    attested_run, _ = make_runner(diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN})
    prereqs = bootstrap.native_prerequisites(attested_run, make_which("/usr/bin/pg_config"))

    seen_syms: list[Path] = []
    guard_run, guard_calls = make_runner(diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN})
    build_invocations: list[Path] = []

    def bad_sym_realpath(path: str) -> str:
        seen_syms.append(Path(path))
        return "/usr/bin/pg_config.evil"

    with pytest.raises(custody.CustodyError, match="private pg_config symlink did not resolve"):
        custody.run_build_with_bound_pg_config(
            prereqs, lambda raw, _env: build_invocations.append(raw), run=guard_run, realpath=bad_sym_realpath
        )
    assert len(seen_syms) == 1 and seen_syms[0].name == "pg_config"
    assert not seen_syms[0].exists() and not seen_syms[0].parent.exists()
    assert guard_calls == [] and build_invocations == [] and dict(os.environ) == before_env

    target_file = rootfs / "usr/bin/pg_config.libpq-dev"
    target_file.write_bytes(b"#!/bin/sh\n# drifted before probes\n")
    target_file.chmod(0o755)
    with pytest.raises(custody.CustodyError, match="drifted before build probes"):
        custody.run_build_with_bound_pg_config(
            prereqs, lambda raw, _env: build_invocations.append(raw), run=guard_run, realpath=os.path.realpath
        )
    assert guard_calls == [] and build_invocations == [] and dict(os.environ) == before_env


def test_main_returns_exit_2_on_custody_or_build_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_host_paths(monkeypatch, tmp_path)
    run, _ = make_runner(
        diversions={"/usr/bin/pg_config": DIVERTED_USR_BIN}, md5sums=f"{'0' * 32}  usr/bin/pg_config\n"
    )
    real_bootstrap = bootstrap.bootstrap
    monkeypatch.setattr(
        bootstrap, "bootstrap", lambda py: real_bootstrap(py, run, make_which("/usr/bin/pg_config"))
    )
    assert bootstrap.main(["--python", "/py"]) == 2
    err = capsys.readouterr().err
    assert "psycopg bootstrap refused:" in err and "diverted target md5 mismatch" in err
