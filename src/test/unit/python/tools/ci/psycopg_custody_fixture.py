"""Shared test fixture for CI pg_config custody and C Psycopg bootstrap unit tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from ci import psycopg_bootstrap as bootstrap
from ci import psycopg_pg_config_custody as custody

DEFAULT_ROWS: dict[str, tuple[str, str]] = {
    "gcc": ("4:12.2.0-3", "gcc-defaults"),
    "libc6-dev": ("2.36-9", "glibc"),
    "libpq-dev": ("17.10-1", "postgresql-17"),
    "libpq5": ("17.10-1", "postgresql-17"),
    "postgresql-client-17": ("17.10-1", "postgresql-17"),
    "postgresql-common": ("278", "postgresql-common"),
}
DEFAULT_OWNERS: dict[str, str] = {
    "/usr/bin/pg_config": "libpq-dev",
    "/usr/include/postgresql/libpq-fe.h": "libpq-dev",
    "/usr/lib/aarch64-linux-gnu/libpq.so.5": "libpq5",
}
DEFAULT_PG_CONFIG: dict[str, str] = {
    "--includedir": "/usr/include/postgresql",
    "--libdir": "/usr/lib/aarch64-linux-gnu",
    "--version": "PostgreSQL 17.10",
}
LIBPQ_DEV_ORIGINAL_BYTES = b"#!/bin/sh\n# libpq-dev original pg_config 17.10\nexit 0\n"
LIBPQ_DEV_ORIGINAL_MD5 = hashlib.md5(LIBPQ_DEV_ORIGINAL_BYTES).hexdigest()
LIBPQ_DEV_ORIGINAL_SHA256 = hashlib.sha256(LIBPQ_DEV_ORIGINAL_BYTES).hexdigest()
DIVERTED_USR_BIN = (
    "diversion by postgresql-common from: /usr/bin/pg_config\n"
    "diversion by postgresql-common to: /usr/bin/pg_config.libpq-dev\n"
    "libpq-dev:arm64, postgresql-common: /usr/bin/pg_config\n"
)
DEFAULT_LISTINGS: dict[str, str] = {
    "libpq-dev": "/usr/bin/pg_config\n/usr/include/postgresql/libpq-fe.h\n",
    "libpq5": "/usr/lib/aarch64-linux-gnu/libpq.so.5\n",
    "postgresql-client-17": "/usr/lib/postgresql/17/bin/pg_config\n",
}
DEFAULT_MD5SUMS = (
    f"{LIBPQ_DEV_ORIGINAL_MD5}  usr/bin/pg_config\n"
    f"{'a' * 32}  usr/include/postgresql/libpq-fe.h\n"
)


def format_rows(
    **override: tuple[str, str, str] | tuple[str, str, str, str] | tuple[str, str, str, str, str]
) -> str:
    rows: dict[str, tuple[str, str, str, str, str]] = {
        name: (ver, "ii", src, ver, "arm64") for name, (ver, src) in DEFAULT_ROWS.items()
    }
    for name, spec in override.items():
        if len(spec) == 3:
            rows[name] = (spec[0], spec[1], spec[2], spec[0], "arm64")
        elif len(spec) == 4:
            rows[name] = (spec[0], spec[1], spec[2], spec[3], "arm64")
        else:
            rows[name] = spec
    return "".join(
        f"{name}\t{arch}\t{ver}\t{st} \t{src}\t{sver}\n"
        for name, (ver, st, src, sver, arch) in rows.items()
    )


MATCHING_PACKAGES = format_rows()


def install_host_paths(
    monkeypatch: Any, tmp_path: Path, realpath_map: Mapping[str, str] | None = None
) -> Path:
    rootfs = tmp_path / "rootfs"
    for rel in (
        "usr/bin/pg_config", "usr/bin/pg_config.libpq-dev",
        "bin/pg_config", "bin/pg_config.libpq-dev", "usr/lib/postgresql/17/bin/pg_config",
    ):
        t = rootfs / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(LIBPQ_DEV_ORIGINAL_BYTES)
        t.chmod(0o755)
    mapping = dict(realpath_map or {})
    monkeypatch.setattr(custody, "FS_ROOT", rootfs)

    def fake_realpath(path: str | Path, **_options: object) -> str:
        raw = str(path)
        if (cand := Path(raw)).is_symlink():
            raw = str(cand.readlink())
        return mapping.get(raw, raw)

    monkeypatch.setattr(bootstrap.os.path, "realpath", fake_realpath)
    return rootfs


def make_which(path: str | None = "/usr/bin/pg_config") -> Callable[[str], str | None]:
    return lambda name: path if name == "pg_config" else None


def make_runner(
    *,
    packages: str = MATCHING_PACKAGES,
    native_arch: str = "arm64",
    attestation: Mapping[str, object] | None = None,
    failing: tuple[str, ...] = (),
    owners: Mapping[str, str] | None = None,
    attest_stdout: str | None = None,
    diversions: Mapping[str, str] | None = None,
    divert_managers: Mapping[str, str] | None = None,
    divert_truenames: Mapping[str, str] | None = None,
    listings: Mapping[str, str] | None = None,
    md5sums: str = DEFAULT_MD5SUMS,
    pg_config_outputs: Mapping[str, str] | None = None,
    probe_overrides: Mapping[str, str] | None = None,
    pip_path_links: list[tuple[Path, Path | None]] | None = None,
    on_pip_install: Callable[[], None] | None = None,
) -> tuple[Callable[..., subprocess.CompletedProcess[str]], list[tuple[list[str], Any]]]:
    calls: list[tuple[list[str], Any]] = []
    attest_payload = dict(
        attestation
        or {
            "psycopg": "3.3.6", "psycopg_c": "3.3.6", "implementation": "c",
            "libpq_runtime": 170010, "libpq_build": 170010, "binary": False,
        }
    )
    owned = dict(DEFAULT_OWNERS if owners is None else owners)
    diverted = dict(diversions or {})
    pkg_files = dict(DEFAULT_LISTINGS if listings is None else listings)
    pg_out = {**DEFAULT_PG_CONFIG, **(pg_config_outputs or {})}
    probe_out = dict(probe_overrides or {})
    mgr_map: dict[str, str] = {}
    true_map: dict[str, str] = {}
    for pkey, raw_div in diverted.items():
        if pkey in ("/usr/bin/pg_config", "/bin/pg_config"):
            for ln in raw_div.splitlines():
                if ln.startswith("diversion by ") and " from: " in ln:
                    mgr_map[pkey] = ln[len("diversion by ") :].split(" from: ", 1)[0]
                if ln.startswith("diversion by ") and " to: " in ln:
                    true_map[pkey] = ln.split(" to: ", 1)[1].strip()
            if pkey in mgr_map and pkey in true_map:
                mgr_map[true_map[pkey]] = mgr_map[pkey]
                true_map[true_map[pkey]] = true_map[pkey]
    mgr_map.update(divert_managers or {})
    true_map.update(divert_truenames or {})

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        env = options.get("env")
        calls.append((list(command), dict(env) if isinstance(env, Mapping) else env))
        if command == ["dpkg", "--print-architecture"]:
            if "print-arch" in failing:
                return subprocess.CompletedProcess(command, 1, "", "dpkg error\n")
            return subprocess.CompletedProcess(command, 0, f"{native_arch}\n" if native_arch else "", "")
        if command[1:4] == ["-m", "pip", "install"]:
            if pip_path_links is not None and isinstance(env, Mapping):
                first = Path(str(env.get("PATH", "")).split(bootstrap.os.pathsep)[0])
                link = first / "pg_config"
                pip_path_links.append((first, link.readlink() if link.is_symlink() else None))
            if on_pip_install is not None:
                on_pip_install()
        if command[:2] == ["dpkg-divert", "--listpackage"]:
            out = mgr_map.get(command[2], "")
            return subprocess.CompletedProcess(command, 0, (out + "\n") if out else "", "")
        if command[:2] == ["dpkg-divert", "--truename"]:
            return subprocess.CompletedProcess(command, 0, true_map.get(command[2], command[2]) + "\n", "")
        if command[:3] == ["dpkg-query", "--control-show", "libpq-dev"]:
            return subprocess.CompletedProcess(command, 1 if "--control-show" in failing else 0, md5sums, "")
        if command[:2] == ["dpkg-query", "-S"]:
            q = command[2]
            if q in diverted:
                return subprocess.CompletedProcess(command, 0, diverted[q], "")
            found = owned.get(q)
            return subprocess.CompletedProcess(command, 0 if found else 1, f"{found}:arm64: {q}\n" if found else "", "")
        if command[:2] == ["dpkg-query", "-L"]:
            return subprocess.CompletedProcess(
                command, 0 if command[2] in pkg_files else 1, pkg_files.get(command[2], ""), ""
            )
        if command[0] == "dpkg-query":
            return subprocess.CompletedProcess(command, 0, packages, "")
        if command[0] == "gcc":
            return subprocess.CompletedProcess(command, 0, "gcc (Debian 12.2.0-14) 12.2.0\n", "")
        if command[0].endswith("pg_config") or command[0].endswith("pg_config.libpq-dev"):
            flag, is_priv = command[1], "repomap-psycopg-" in command[0]
            if is_priv and "bound-probe" in failing:
                return subprocess.CompletedProcess(command, 1, "", "probe error\n")
            val = probe_out.get(flag, pg_out[flag]) if is_priv else pg_out[flag]
            return subprocess.CompletedProcess(command, 0, val + "\n", "")
        if command[1:3] == ["-I", "-c"]:
            out = json.dumps(attest_payload) + "\n" if attest_stdout is None else attest_stdout
            return subprocess.CompletedProcess(command, 0, out, "")
        return subprocess.CompletedProcess(command, 1 if any(t in command for t in failing) else 0, "", "")

    return run, calls
