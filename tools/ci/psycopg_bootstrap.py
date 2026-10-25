#!/usr/bin/env python3
"""Install C Psycopg into one interpreter from hash-locked inputs (ADR 0089 D5/D6, ADR 0093).

The host must be Debian-family and already provide ``gcc``, ``libc6-dev`` and
one installed ``libpq-dev``/``libpq5`` pair. This tool acquires and installs no
system package and adds no repository: it records the existing packages' dpkg
identities, so their custody is the host or runner image's, not a resolution
made here. The shared ``tools/native_apt_prerequisites.py`` attestation or
CI ``dpkg-divert`` custody helper binds ``pg_config`` to the pair before
execution.
It then installs the hash-locked build tools, builds psycopg-c from its
hash-bound sdist without build isolation, installs the Psycopg wheel, and
attests the C implementation with equal header and runtime libpq. Any other
project-lock install then needs wheels only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Sequence

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci import psycopg_pg_config_custody as custody
import native_apt_prerequisites as apt

CI_ROOT = Path(__file__).resolve().parent
APT_PREREQUISITES = CI_ROOT.parent / "native_apt_prerequisites.py"
BUILD_LOCK = CI_ROOT / "psycopg_build.lock"
PROJECT_LOCK = CI_ROOT / "project_dependencies.lock"
PSYCOPG_VERSION = "3.3.6"
ATTEST = """\
import importlib.metadata as md, importlib.util as iu, json, os
os.environ.pop("PSYCOPG_IMPL", None)
import psycopg
from psycopg import pq
print(json.dumps({"psycopg": psycopg.__version__, "psycopg_c": md.version("psycopg-c"),
                  "implementation": pq.__impl__, "libpq_runtime": pq.version(),
                  "libpq_build": pq.__build_version__, "binary": iu.find_spec("psycopg_binary") is not None},
                 sort_keys=True))
"""

Runner = Callable[..., subprocess.CompletedProcess[str]]


class BootstrapError(RuntimeError):
    """A prerequisite, lock entry, install step or attestation is not as required."""


def lock_entry(lock_text: str, name: str) -> str:
    """Return the exact requirement block for one locked distribution, without comments."""
    blocks: list[list[str]] = []
    for line in lock_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if not blocks:
                raise BootstrapError("lock continuation precedes a requirement")
            blocks[-1].append(line.strip())
        else:
            blocks.append([line.strip()])
    found = [block for block in blocks if block[0].split("==", 1)[0] == name]
    if len(found) != 1 or not any(part.startswith("--hash=sha256:") for part in found[0]):
        raise BootstrapError(f"{name} is not locked exactly once with hashes")
    return " ".join(part.rstrip(" \\") for part in found[0]) + "\n"


def native_prerequisites(
    run: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which
) -> dict[str, object]:
    """Record existing compiler and libpq identities; nothing is acquired or installed."""
    try:
        installed, libpq = custody.attest_ci_libpq(run, which=which, realpath=os.path.realpath)
        compiler = apt.command_output(run, ["gcc", "--version"]).strip().splitlines()
    except (apt.PrerequisiteRefused, custody.CustodyError) as error:
        raise BootstrapError(str(error)) from error
    packages = {row["name"]: row["version"] for row in installed.values()
                if row["status"] == "ii" and row["name"] in ("gcc", "libc6-dev", "libpq-dev", "libpq5")}
    if set(packages) != {"gcc", "libc6-dev", "libpq-dev", "libpq5"} or not compiler:
        raise BootstrapError(f"gcc, libc6-dev, libpq-dev and libpq5 are not all installed: {packages}")
    return {
        "acquisition": "none; existing host or runner image packages",
        "compiler": compiler[0],
        "packages": packages,
        "pg_config": libpq["pg_config"]["version"],
        "pg_config_executable": libpq["pg_config"],
        "libpq_dev": libpq["libpq_dev"],
        "libpq5": libpq["libpq5"],
        "source": libpq["source"],
        "source_version": libpq["source_version"],
        "includedir": libpq["includedir"],
        "libdir": libpq["libdir"],
        "paths": libpq["paths"],
        "owners": libpq["owners"],
        "custody": libpq["custody"],
    }


def install_commands(python: str, sdist_requirement: Path, wheel_requirement: Path) -> list[list[str]]:
    pip = [python, "-m", "pip", "install", "--no-cache-dir", "--require-hashes", "--no-deps"]
    return [
        [*pip, "--only-binary", ":all:", "--requirement", str(BUILD_LOCK)],
        [*pip, "--no-build-isolation", "--check-build-dependencies", "--requirement", str(sdist_requirement)],
        [*pip, "--only-binary", ":all:", "--requirement", str(wheel_requirement)],
    ]


def attest(python: str, run: Runner = subprocess.run) -> dict[str, object]:
    environment = {key: value for key, value in os.environ.items() if key != "PSYCOPG_IMPL"}
    completed = run([python, "-I", "-c", ATTEST], capture_output=True, text=True, check=False, env=environment)
    if completed.returncode != 0:
        raise BootstrapError("C Psycopg attestation could not import psycopg")
    lines = (completed.stdout or "").strip().splitlines()
    try:
        payload = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        raise BootstrapError("C Psycopg attestation produced no result")
    if (
        payload.get("psycopg") != PSYCOPG_VERSION
        or payload.get("psycopg_c") != PSYCOPG_VERSION
        or payload.get("implementation") != "c"
        or payload.get("libpq_runtime") != payload.get("libpq_build")
        or payload.get("binary") is not False
    ):
        raise BootstrapError(f"C Psycopg attestation failed: {payload}")
    return payload


def bootstrap(
    python: str, run: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which
) -> dict[str, object]:
    prerequisites = native_prerequisites(run, which)
    lock_text = PROJECT_LOCK.read_text(encoding="utf-8")

    def _run_installs(raw_path: Path, child_env: dict[str, str]) -> None:
        sdist, wheel = raw_path / "psycopg-c.txt", raw_path / "psycopg.txt"
        sdist.write_text(lock_entry(lock_text, "psycopg-c"), encoding="utf-8")
        wheel.write_text(lock_entry(lock_text, "psycopg"), encoding="utf-8")
        for command in install_commands(python, sdist, wheel):
            if run(command, check=False, env=child_env).returncode != 0:
                raise BootstrapError(f"install step failed: {' '.join(command[3:])}")

    try:
        custody.run_build_with_bound_pg_config(
            prerequisites, _run_installs, run=run, realpath=os.path.realpath
        )
    except custody.CustodyError as error:
        raise BootstrapError(str(error)) from error
    return {"native": prerequisites, "attestation": attest(python, run)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        evidence = bootstrap(args.python)
    except (BootstrapError, OSError, ValueError) as error:
        print(f"psycopg bootstrap refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
