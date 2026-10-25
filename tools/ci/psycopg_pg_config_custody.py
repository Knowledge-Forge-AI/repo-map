"""CI-only pg_config custody and known libpq-dev diversion attestation (ADR 0093)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence

import native_apt_prerequisites as apt

Runner = Callable[..., subprocess.CompletedProcess[str]]
_CANONICAL_PG_CONFIG_PATHS: dict[str, str] = {
    "/usr/bin/pg_config": "/usr/bin/pg_config.libpq-dev",
    "/bin/pg_config": "/bin/pg_config.libpq-dev",
}
_KNOWN_DIVERSION_MANAGERS = frozenset({"postgresql-common", "postgresql-common-dev"})
_DIVERTED_TARGETS = frozenset(_CANONICAL_PG_CONFIG_PATHS.values())
_DEB_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_DEB_ARCH = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MD5SUM_LINE = re.compile(r"^([0-9a-f]{32})  ([^\s/]\S*)$")
_UPSTREAM_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)+(?:~[A-Za-z0-9.+~]+)?$")
_PG_CONFIG_VERSION = re.compile(
    r"^PostgreSQL\s+([0-9]+(?:\.[0-9]+)+(?:~[A-Za-z0-9.+~]+)?)(?:\s+\(([^()]+)\))?$"
)
_PG_CONFIG_FLAGS: tuple[str, ...] = ("--includedir", "--libdir", "--version")
FS_ROOT: Path | None = None


class CustodyError(RuntimeError):
    """A pg_config custody, diversion, control-record, or build-binding check failed."""


def _fs_path(path: str) -> Path:
    return (FS_ROOT / path.lstrip("/")) if (FS_ROOT is not None and path.startswith("/")) else Path(path)


def controlled_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base_env is None else base_env
    env = {k: v for k, v in source.items() if k != "PSYCOPG_IMPL"}
    env.update({"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "LANGUAGE": ""})
    return env


def command_output(run: Runner, command: Sequence[str], *, accept: Sequence[int] = (0,)) -> str:
    env = controlled_env()
    try:
        res = run(list(command), capture_output=True, text=True, check=False, env=env)
    except OSError as error:
        raise CustodyError(f"{command[0]} is unavailable (a Debian-family environment is required)") from error
    if res.returncode not in accept:
        out = apt.redact(f"{res.stdout or ''}\n{getattr(res, 'stderr', None) or ''}", env)
        detail = f"; redacted output tail: {tail}" if (tail := apt.bounded_tail(out)) else ""
        raise CustodyError(f"{apt.redact(' '.join(command[:3]), env)} failed with exit {res.returncode}{detail}")
    return res.stdout or ""


def extract_debian_upstream_version(debian_version: str) -> str:
    val = debian_version.strip()
    if not val:
        raise CustodyError("empty Debian package version")
    if ":" in val:
        epoch, val = val.split(":", 1)
        if not epoch.isdigit() or not val:
            raise CustodyError(f"invalid epoch in Debian version: {debian_version!r}")
    upstream = val.rsplit("-", 1)[0] if "-" in val else re.sub(r"\+b[0-9]+$", "", val)
    if not _UPSTREAM_VERSION.fullmatch(upstream):
        raise CustodyError(f"invalid upstream version in Debian version: {debian_version!r}")
    return upstream


def pg_config_version_matches_package(tool_version_output: str, package_version: str, source_version: str) -> bool:
    m = _PG_CONFIG_VERSION.fullmatch(tool_version_output.strip())
    if m is None:
        return False
    tool_up, vendor = m.group(1), m.group(2)
    try:
        pkg_up = extract_debian_upstream_version(package_version)
        src_up = extract_debian_upstream_version(source_version)
        if not (tool_up == pkg_up == src_up):
            return False
        if vendor is not None:
            toks = vendor.strip().split()
            if len(toks) != 2 or toks[0] not in {"Debian", "Ubuntu"}:
                return False
            return extract_debian_upstream_version(toks[1]) == tool_up
    except CustodyError:
        return False
    return True


def observe_target_executable(path: str) -> dict[str, Any]:
    fs_target = _fs_path(path)
    try:
        st_b = os.lstat(fs_target)
    except OSError as error:
        raise CustodyError(f"pg_config target {path} is missing or unreadable") from error
    if stat.S_ISLNK(st_b.st_mode):
        raise CustodyError(f"pg_config target {path} must not be a symlink")
    if not stat.S_ISREG(st_b.st_mode):
        raise CustodyError(f"pg_config target {path} is not a regular file")
    if not (st_b.st_mode & 0o111):
        raise CustodyError(f"pg_config target {path} is not executable")
    if st_b.st_size <= 0:
        raise CustodyError(f"pg_config target {path} is empty")
    try:
        raw = fs_target.read_bytes()
        st_a = os.lstat(fs_target)
    except OSError as error:
        raise CustodyError(f"pg_config target {path} could not be read") from error
    def sig(st: os.stat_result) -> tuple[int, int, int, int, int]:
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_mode

    if sig(st_b) != sig(st_a) or len(raw) != st_b.st_size:
        raise CustodyError(f"pg_config target {path} changed during inspection")
    return {
        "md5": hashlib.md5(raw).hexdigest(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": st_b.st_size,
        "filesystem_identity": {"dev": int(st_b.st_dev), "ino": int(st_b.st_ino), "mode": int(st_b.st_mode & 0o777)},
    }


def _rows(installed: Mapping[str, Mapping[str, str]], name: str) -> list[Mapping[str, str]]:
    return [row for row in installed.values() if row["name"] == name and row["status"] == "ii"]


def _verify_libpq_pair(
    run: Runner, installed: Mapping[str, Mapping[str, str]]
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    dev_r, run_r = _rows(installed, "libpq-dev"), _rows(installed, "libpq5")
    if len(dev_r) != 1 or len(run_r) != 1:
        raise CustodyError("libpq-dev and libpq5 are not each installed exactly once")
    dev, runtime = dev_r[0], run_r[0]
    if (dev["version"], dev["source"], dev["source_version"]) != (
        runtime["version"], runtime["source"], runtime["source_version"]
    ):
        raise CustodyError(f"libpq headers and runtime differ: {dev['version']} != {runtime['version']}")
    native = command_output(run, ["dpkg", "--print-architecture"]).strip()
    if not native or native == "all" or not _DEB_ARCH.fullmatch(native):
        raise CustodyError(f"native architecture is unknown: {native!r}")
    if (
        dev["architecture"] != runtime["architecture"]
        or dev["architecture"] in ("", "all")
        or dev["architecture"] != native
    ):
        raise CustodyError(
            f"libpq-dev ({dev['architecture']}) and libpq5 ({runtime['architecture']}) "
            f"architecture mismatch against native {native}"
        )
    return dev, runtime


def _parse_dpkg_search(output: str, path: str, arch: str, mgr: str) -> tuple[list[str], set[str]]:
    div_lines: list[str] = []
    owners: set[str] = set()
    suffix = f": {path}"
    for raw_ln in output.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        if ln.startswith("diversion by "):
            div_lines.append(ln)
            continue
        if not ln.endswith(suffix) or not (prefix := ln[: -len(suffix)].strip()):
            raise CustodyError(f"unexpected dpkg-query -S record for {path}: {ln!r}")
        for raw_item in prefix.split(","):
            item = raw_item.strip()
            if not item:
                raise CustodyError(f"malformed dpkg-query -S owner list for {path}: {ln!r}")
            pkg, sep, qual = item.partition(":")
            allowed_quals = (arch, "all") if pkg == mgr else (arch,)
            if not _DEB_NAME.fullmatch(pkg) or (sep and qual not in allowed_quals):
                raise CustodyError(f"unexpected dpkg-query -S owner {item!r} for {path}")
            owners.add(pkg)
    return div_lines, owners


def _verify_diversion_records(
    run: Runner, installed: Mapping[str, Mapping[str, str]], canonical: str, arch: str
) -> tuple[str, Mapping[str, str], str]:
    exp_target = _CANONICAL_PG_CONFIG_PATHS[canonical]
    mgr = command_output(run, ["dpkg-divert", "--listpackage", canonical]).strip()
    true_p = command_output(run, ["dpkg-divert", "--truename", canonical]).strip()
    if mgr == "LOCAL" or not mgr:
        raise CustodyError(f"refusing local or missing dpkg-divert manager for {canonical}: {mgr!r}")
    if mgr not in _KNOWN_DIVERSION_MANAGERS:
        raise CustodyError(f"unknown dpkg-divert manager for {canonical}: {mgr}")
    mgr_rows = _rows(installed, mgr)
    if len(mgr_rows) != 1 or mgr_rows[0]["architecture"] not in (arch, "all"):
        raise CustodyError(f"diversion manager {mgr} is not installed exactly once")
    if true_p != exp_target or true_p not in _DIVERTED_TARGETS:
        raise CustodyError(f"dpkg-divert truename for {canonical} is {true_p!r}, expected {exp_target!r}")
    target_mgr = command_output(run, ["dpkg-divert", "--listpackage", true_p]).strip()
    target_true = command_output(run, ["dpkg-divert", "--truename", true_p]).strip()
    if target_mgr != mgr:
        raise CustodyError(f"dpkg-divert manager for diverted target {true_p} is {target_mgr!r}, expected {mgr!r}")
    if target_true != true_p:
        raise CustodyError(f"diverted target {true_p} is itself diverted to {target_true!r}")

    exp_div = {f"diversion by {mgr} from: {canonical}", f"diversion by {mgr} to: {true_p}"}
    s_out = command_output(run, ["dpkg-query", "-S", canonical], accept=(0, 1))
    div_lines, owners = _parse_dpkg_search(s_out, canonical, arch, mgr)
    if len(div_lines) != 2 or set(div_lines) != exp_div:
        raise CustodyError(f"inconsistent dpkg-query -S diversion lines for {canonical}: {div_lines}")
    if "libpq-dev" not in owners or not (owners <= {"libpq-dev", mgr}):
        raise CustodyError(f"unexpected dpkg-query -S owners for {canonical}: {sorted(owners)}")

    t_out = command_output(run, ["dpkg-query", "-S", true_p], accept=(0, 1))
    t_divs, t_owners = _parse_dpkg_search(t_out, true_p, arch, mgr)
    if t_divs and (len(t_divs) != 2 or set(t_divs) != exp_div):
        raise CustodyError(f"inconsistent dpkg-query -S diversion lines for {true_p}: {t_divs}")
    if not (t_owners <= {"libpq-dev"}):
        raise CustodyError(f"unexpected dpkg-query -S owners for {true_p}: {sorted(t_owners)}")

    if canonical not in {ln.strip() for ln in command_output(run, ["dpkg-query", "-L", "libpq-dev"]).splitlines()}:
        raise CustodyError(f"libpq-dev file list does not contain {canonical}")
    return mgr, mgr_rows[0], true_p


def _verify_control_md5sums(run: Runner, canonical: str, observed_md5: str) -> dict[str, str]:
    rel = canonical.lstrip("/")
    raw_md5 = command_output(run, ["dpkg-query", "--control-show", "libpq-dev", "md5sums"])
    lines = [ln for ln in raw_md5.splitlines() if ln.strip()]
    if not lines:
        raise CustodyError("libpq-dev md5sums control record is empty")
    matches: list[tuple[str, str]] = []
    for ln in lines:
        m = _MD5SUM_LINE.fullmatch(ln)
        if m is None:
            raise CustodyError(f"malformed libpq-dev md5sums line: {ln!r}")
        if m.group(2) == rel:
            matches.append((m.group(1), m.group(2)))
    if len(matches) != 1:
        raise CustodyError(f"libpq-dev md5sums must contain {rel} exactly once; found {len(matches)}")
    exp_md5, m_path = matches[0]
    if observed_md5 != exp_md5:
        raise CustodyError(f"diverted target md5 mismatch for {m_path}: {observed_md5} != {exp_md5}")
    return {"path": m_path, "md5": exp_md5}


def attest_ci_libpq(
    run: Runner,
    *,
    which: Callable[[str], str | None] = shutil.which,
    realpath: Callable[[str], str] = os.path.realpath,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    try:
        installed = apt.installed_packages(run)
    except apt.PrerequisiteRefused as error:
        raise CustodyError(str(error)) from error
    dev, runtime = _verify_libpq_pair(run, installed)
    exe = which("pg_config")
    if not exe:
        raise CustodyError("pg_config is not on PATH")
    real = realpath(exe)
    try:
        apt.package_of(run, real)
        diverted = False
    except apt.PrerequisiteRefused as error:
        if str(error) != f"{real} is diverted":
            raise CustodyError(str(error)) from error
        diverted = True

    if not diverted:
        try:
            libpq = apt.attest_libpq(run, which=which, realpath=realpath)
        except apt.PrerequisiteRefused as error:
            raise CustodyError(str(error)) from error
        pg_info = libpq["pg_config"]
        if not pg_config_version_matches_package(str(pg_info["version"]), dev["version"], dev["source_version"]):
            raise CustodyError(f"pg_config version {pg_info['version']!r} != libpq-dev {dev['version']}")
        obs = observe_target_executable(str(pg_info["realpath"]))
        return installed, {
            **libpq,
            "custody": {
                "route": "shared_attest_libpq",
                "original_path": exe,
                "diversion_manager": None,
                "destination": str(pg_info["realpath"]),
                "native_architecture": dev["architecture"],
                "control_entry": None,
                "local_integrity_method": "observed_target_sha256",
                "sha256": obs["sha256"],
                "size": obs["size"],
                "filesystem_identity": obs["filesystem_identity"],
            },
        }

    if exe not in _CANONICAL_PG_CONFIG_PATHS or real not in _CANONICAL_PG_CONFIG_PATHS:
        raise CustodyError(f"diverted pg_config {exe} -> {real} is not a canonical path")
    mgr, mgr_row, truename = _verify_diversion_records(run, installed, real, dev["architecture"])
    t_real = realpath(truename)
    if t_real != truename or t_real not in _DIVERTED_TARGETS:
        raise CustodyError(f"diverted target {truename} resolved to unexpected path {t_real}")
    obs = observe_target_executable(t_real)
    ctrl_entry = _verify_control_md5sums(run, real, obs["md5"])

    sel = {flag: command_output(run, [t_real, flag]).strip() for flag in _PG_CONFIG_FLAGS}
    if not pg_config_version_matches_package(sel["--version"], dev["version"], dev["source_version"]):
        raise CustodyError(f"diverted pg_config version {sel['--version']!r} != libpq-dev {dev['version']}")
    paths = {
        "libpq-fe.h": realpath(os.path.join(sel["--includedir"], "libpq-fe.h")),
        "libpq.so.5": realpath(os.path.join(sel["--libdir"], "libpq.so.5")),
    }
    try:
        owners = {name: apt.package_of(run, path) for name, path in paths.items()}
    except apt.PrerequisiteRefused as error:
        raise CustodyError(str(error)) from error
    if owners != {"libpq-fe.h": "libpq-dev", "libpq.so.5": "libpq5"}:
        raise CustodyError(f"libpq header or runtime is not owned by that pair: {owners}")

    return installed, {
        "pg_config": {
            "path": t_real, "realpath": t_real, "package": "libpq-dev",
            "package_version": dev["version"], "version": sel["--version"],
        },
        "libpq_dev": dev["version"],
        "libpq5": runtime["version"],
        "source": dev["source"],
        "source_version": dev["source_version"],
        "includedir": sel["--includedir"],
        "libdir": sel["--libdir"],
        "paths": paths,
        "owners": {"pg_config": "libpq-dev", **owners},
        "custody": {
            "route": "dpkg_divert_libpq_dev_original",
            "original_path": real,
            "diversion_manager": mgr,
            "diversion_manager_version": mgr_row["version"],
            "destination": t_real,
            "native_architecture": dev["architecture"],
            "control_entry": ctrl_entry,
            "local_integrity_method": "local_installed_package_md5sums_plus_sha256",
            "sha256": obs["sha256"],
            "size": obs["size"],
            "filesystem_identity": obs["filesystem_identity"],
        },
    }


def run_build_with_bound_pg_config(
    prerequisites: Mapping[str, Any],
    build_step: Callable[[Path, dict[str, str]], None],
    *,
    run: Runner = subprocess.run,
    realpath: Callable[[str], str] = os.path.realpath,
) -> None:
    pg_info, custody = prerequisites.get("pg_config_executable"), prerequisites.get("custody")
    if not isinstance(pg_info, Mapping) or not isinstance(custody, Mapping):
        raise CustodyError("prerequisites missing pg_config_executable or custody record")
    t_real = str(pg_info["realpath"])
    expected = {
        "--includedir": str(prerequisites["includedir"]),
        "--libdir": str(prerequisites["libdir"]),
        "--version": str(pg_info["version"]),
    }
    exp_sig = (custody["sha256"], custody["size"], custody["filesystem_identity"])
    with tempfile.TemporaryDirectory(prefix="repomap-psycopg-") as raw:
        raw_path = Path(raw)
        bin_dir = raw_path / "bin"
        bin_dir.mkdir(mode=0o700)
        sym = bin_dir / "pg_config"
        sym.symlink_to(t_real)
        if not sym.is_symlink() or realpath(str(sym)) != t_real:
            raise CustodyError(f"private pg_config symlink did not resolve to {t_real!r}")
        before = observe_target_executable(t_real)
        if (before["sha256"], before["size"], before["filesystem_identity"]) != exp_sig:
            raise CustodyError(f"pg_config target {t_real} drifted before build probes")
        child_env = {k: v for k, v in os.environ.items() if k != "PSYCOPG_IMPL"}
        existing = child_env.get("PATH", "")
        child_env["PATH"] = f"{bin_dir}{os.pathsep}{existing}" if existing else str(bin_dir)
        probe_env = controlled_env(child_env)
        for flag, exp_val in expected.items():
            res = run([str(sym), flag], capture_output=True, text=True, check=False, env=probe_env)
            if res.returncode != 0:
                raise CustodyError(f"bound pg_config {flag} probe failed with exit {res.returncode}")
            if (actual := (res.stdout or "").strip()) != exp_val:
                raise CustodyError(f"bound pg_config {flag} output {actual!r} != attested {exp_val!r}")
        build_step(raw_path, child_env)
        after = observe_target_executable(t_real)
        if (after["sha256"], after["size"], after["filesystem_identity"]) != exp_sig:
            raise CustodyError(f"pg_config target {t_real} drifted during build")
