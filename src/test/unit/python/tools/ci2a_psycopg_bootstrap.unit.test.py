"""ADR 0089 D5/D6: hash-locked C Psycopg bootstrap, lock guards and hash copies (no live install)."""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from ci import check_generated_drift as drift
from ci import psycopg_bootstrap as bootstrap
from repomap_kg.runtime import release

ROOT = Path(__file__).resolve().parents[5]
SDIST = "29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8"


def _locked(lock: str) -> dict[str, tuple[str, set[str]]]:
    entries: dict[str, tuple[str, set[str]]] = {}
    for block in re.split(r"\n(?=[a-z])", (ROOT / "tools/ci" / lock).read_text(encoding="utf-8")):
        head = re.match(r"([a-z0-9-]+)==(\S+)", block)
        if head:
            entries[head[1]] = (head[2], set(re.findall(r"--hash=sha256:([0-9a-f]{64})", block)))
    return entries


# Requires-Dist of each locked build tool without an extra marker, from the
# PyPI JSON metadata of the exact locked versions (wheel 0.48.0: packaging>=24.0;
# setuptools 83.0.0 and packaging 26.3 declare none). A new requirement must be
# added here and to the lock together; pip check enforces it inside each build.
BUILD_TOOL_REQUIRES = {"packaging": (), "setuptools": (), "wheel": (("packaging", (24, 0)),)}


def test_locks_hold_exactly_the_approved_distributions_and_hashes():
    build = _locked("psycopg_build.lock")
    project = _locked("project_dependencies.lock")
    assert {name: version for name, (version, _) in build.items()} == {
        "packaging": "26.3", "setuptools": "83.0.0", "wheel": "0.48.0"}
    assert build["packaging"][1] == {"94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79",
                                     "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"}
    pre_review = _locked("pre_review_python.lock")
    assert pre_review["packaging"] == build["packaging"], "the already selected packaging pin and hashes"
    assert project["psycopg"] == ("3.3.6", {"a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631",
                                            "c081f2250df751a943036e42db6df4571c66cd0aabe8291a7a506512b12007d2"})
    assert project["psycopg-c"] == ("3.3.6", {SDIST}) and "psycopg-binary" not in project
    assert project["typing-extensions"][0] == "4.16.0"


def test_every_build_tool_requirement_is_satisfied_inside_the_build_lock():
    build = _locked("psycopg_build.lock")
    assert set(BUILD_TOOL_REQUIRES) == set(build), "every locked tool has a recorded requirement set"
    for tool, requirements in BUILD_TOOL_REQUIRES.items():
        for name, minimum in requirements:
            assert name in build, f"{tool} requires {name}, which the build lock does not hold"
            assert tuple(int(part) for part in build[name][0].split(".")) >= minimum, (tool, name)


def test_release_constants_and_sandbox_dockerfile_copy_the_lock_hashes_exactly():
    locked = {**_locked("psycopg_build.lock"), **_locked("project_dependencies.lock")}
    for requirement, hashes in release.RELEASE_WHEEL_REQUIREMENTS.items():
        name, version = requirement.split("==")
        assert locked[name] == (version, set(hashes)), requirement
    assert release.PSYCOPG_C_SDIST_SHA256 == SDIST and release.PSYCOPG_C_SDIST_SIZE == 698245
    dockerfile = (ROOT / "tools/test_sandbox/Dockerfile").read_text(encoding="utf-8")
    for name in ("packaging", "setuptools", "wheel", "psycopg"):
        locked_version, locked_hashes = locked[name]
        line = next(item for item in dockerfile.splitlines() if f'"{name}=={locked_version} --hash' in item)
        assert set(re.findall(r"--hash=sha256:([0-9a-f]{64})", line)) == locked_hashes, name
    assert dockerfile.count(SDIST) == 2 and "psycopg[binary]" not in dockerfile
    assert "RUN --network=none" in dockerfile and "--no-build-isolation --check-build-dependencies" in dockerfile


def test_lock_resolution_never_runs_a_build_backend_and_build_lock_takes_no_dependencies():
    policy = drift.LockPolicy(drift.PYPI_INDEX, "2026-09-18T13:22:58Z", "0" * 64)
    assert ("psycopg_build.in", "psycopg_build.lock") in drift.PYTHON_LOCKS
    project = drift.compile_command("uv", "project_dependencies.in", "project_dependencies.lock", policy)
    assert project[project.index("--build-constraint") + 1] == drift.BUILD_REFUSAL_PATH and "--no-build" not in project
    for source, lock in (
        ("pre_review_python.in", "pre_review_python.lock"), ("psycopg_build.in", "psycopg_build.lock"),
    ):
        command = drift.compile_command("uv", source, lock, policy)
        assert "--no-build" in command and ("--no-deps" in command) == (lock == "psycopg_build.lock"), command
    assert drift.BUILD_REFUSAL_CONSTRAINTS == "setuptools<0\nwheel<0\n"


def test_build_refusal_constraint_exists_only_while_its_command_runs(tmp_path, monkeypatch):
    (tmp_path / "tools/ci").mkdir(parents=True)
    seen = []

    def fake_run(command, **_):
        seen.append((tmp_path / drift.BUILD_REFUSAL_PATH).read_text(encoding="utf-8"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(drift.subprocess, "run", fake_run)
    drift.run(["uv", "--build-constraint", drift.BUILD_REFUSAL_PATH], cwd=tmp_path, env={})
    assert seen == [drift.BUILD_REFUSAL_CONSTRAINTS] and not (tmp_path / drift.BUILD_REFUSAL_PATH).exists()


def test_lock_entry_returns_one_hashed_requirement_line():
    text = (ROOT / "tools/ci/project_dependencies.lock").read_text(encoding="utf-8")
    assert bootstrap.lock_entry(text, "psycopg-c") == (
        f"psycopg-c==3.3.6 ; implementation_name != 'pypy' --hash=sha256:{SDIST}\n")
    with pytest.raises(bootstrap.BootstrapError, match="exactly once with hashes"):
        bootstrap.lock_entry("psycopg-c==3.3.6\n", "psycopg-c")


ROWS = {"gcc": ("4:12.2.0-3", "gcc-defaults"), "libc6-dev": ("2.36-9", "glibc"),
        "libpq-dev": ("17.10-1", "postgresql-17"), "libpq5": ("17.10-1", "postgresql-17"),
        "postgresql-client-17": ("17.10-1", "postgresql-17")}


def _rows(**override):
    rows = {**{name: (version, "ii", source) for name, (version, source) in ROWS.items()}, **override}
    return "".join(f"{name}\tarm64\t{version}\t{status} \t{source}\t{version}\n"
                   for name, (version, status, source) in rows.items())


MATCHING = _rows()
OWNERS = {"/usr/bin/pg_config": "libpq-dev", "/usr/include/postgresql/libpq-fe.h": "libpq-dev",
          "/usr/lib/aarch64-linux-gnu/libpq.so.5": "libpq5"}
PG_CONFIG = {"--includedir": "/usr/include/postgresql", "--libdir": "/usr/lib/aarch64-linux-gnu",
             "--version": "PostgreSQL 17.10"}


@pytest.fixture
def host_paths(monkeypatch):
    # The fakes own every queried path; a real host symlink must not redirect them.
    monkeypatch.setattr(bootstrap.os.path, "realpath", lambda path, **_options: path)


def _which(path="/usr/bin/pg_config"):
    return lambda name: path if name == "pg_config" else None


def _runner(packages=MATCHING, attestation=None, failing=(), owners=None, attest_stdout=None):
    calls = []
    attest = attestation or {"psycopg": "3.3.6", "psycopg_c": "3.3.6", "implementation": "c",
                             "libpq_runtime": 170010, "libpq_build": 170010, "binary": False}
    owned = OWNERS if owners is None else owners

    def run(command, **options):
        calls.append((command, options.get("env")))
        if command[:2] == ["dpkg-query", "-S"]:
            found = owned.get(command[2])
            out = f"{found}:arm64: {command[2]}\n" if found else ""
            return SimpleNamespace(returncode=0 if found else 1, stdout=out)
        if command[0] == "dpkg-query":
            return SimpleNamespace(returncode=0, stdout=packages)
        if command[0] == "gcc" or command[0].endswith("pg_config"):
            text = "gcc (Debian 12.2.0-14) 12.2.0" if command[0] == "gcc" else PG_CONFIG[command[1]]
            return SimpleNamespace(returncode=0, stdout=text + "\n")
        if command[1:3] == ["-I", "-c"]:
            out = json.dumps(attest) + "\n" if attest_stdout is None else attest_stdout
            return SimpleNamespace(returncode=0, stdout=out)
        return SimpleNamespace(returncode=1 if any(token in command for token in failing) else 0, stdout="")
    return run, calls


def test_bootstrap_installs_build_tools_then_builds_without_isolation_and_attests_c(host_paths):
    run, calls = _runner()
    evidence = bootstrap.bootstrap("/py", run, _which())
    installs = [command for command, _ in calls if command[1:4] == ["-m", "pip", "install"]]
    assert installs[0][-2:] == ["--requirement", str(bootstrap.BUILD_LOCK)] and ":all:" in installs[0]
    assert "--no-build-isolation" in installs[1] and "--check-build-dependencies" in installs[1]
    assert all("--require-hashes" in command and "--no-deps" in command for command in installs)
    native, attestation = evidence["native"], evidence["attestation"]
    assert isinstance(native, dict) and native["libpq5"] == "17.10-1", native
    assert native["acquisition"].startswith("none") and native["packages"]["gcc"] == "4:12.2.0-3"
    assert isinstance(attestation, dict) and attestation["implementation"] == "c", attestation
    assert all("PSYCOPG_IMPL" not in (env or {}) for _command, env in calls)
    assert not [command for command, _ in calls if command[0] in ("apt-get", "apt", "dpkg")], "no system install"


@pytest.mark.parametrize("packages,attestation,failing,message", [
    (_rows(libpq5=("18.1-1", "ii", "postgresql-18")), None, (), "headers and runtime differ"),
    (_rows(**{"libpq-dev": ("17.10-1", "rc", "postgresql-17")}), None, (), "not each installed exactly once"),
    (_rows(**{"libc6-dev": ("2.36-9", "rc", "glibc")}), None, (), "are not all installed"),
    (None, {"implementation": "python"}, (), "attestation failed"),
    (None, None, ("--no-build-isolation",), "install step failed"),
])
def test_bootstrap_refuses_mismatched_headers_fallback_or_failed_build(packages, attestation, failing, message,
                                                                        host_paths):
    run, _calls = _runner(packages or MATCHING, attestation=attestation, failing=failing)
    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.bootstrap("/py", run, _which())


@pytest.mark.parametrize("owners,message", [
    ({**OWNERS, "/usr/bin/pg_config": "postgresql-client-16"}, "owned by postgresql-client-16"),
    ({key: value for key, value in OWNERS.items() if not key.endswith("libpq-fe.h")}, "not owned by that pair"),
    ({**OWNERS, "/usr/lib/aarch64-linux-gnu/libpq.so.5": "libpq-private"}, "not owned by that pair"),
])
def test_pg_config_headers_and_runtime_must_be_owned_by_the_one_libpq_pair(owners, message, host_paths):
    run, _calls = _runner(owners=owners)
    with pytest.raises(bootstrap.BootstrapError, match=message):
        bootstrap.native_prerequisites(run, _which())


def test_relocated_path_pg_config_is_bound_by_its_own_realpath_package(monkeypatch):
    relocated, real = "/opt/runner/bin/pg_config", "/usr/lib/postgresql/17/bin/pg_config"
    monkeypatch.setattr(bootstrap.os.path, "realpath", lambda path, **_options: real if path == relocated else path)
    run, calls = _runner(owners={**OWNERS, real: "postgresql-client-17"})
    native = bootstrap.native_prerequisites(run, _which(relocated))
    executable, owners = native["pg_config_executable"], native["owners"]
    assert isinstance(executable, dict) and executable["realpath"] == real
    assert isinstance(owners, dict) and owners["pg_config"] == "postgresql-client-17"
    queried = [command for command, _env in calls if command[0].endswith("pg_config")]
    assert {command[0] for command in queried} == {relocated} and all(c[1] != "--bindir" for c in queried)
    unowned, _calls = _runner(owners=OWNERS)
    with pytest.raises(bootstrap.BootstrapError, match="owned by no package"):
        bootstrap.native_prerequisites(unowned, _which(relocated))


@pytest.mark.parametrize("stdout", ["", "\n", "not json\n", "[1]\n"])
def test_empty_or_malformed_attestation_refuses_with_a_bounded_error(stdout):
    run, _calls = _runner(attest_stdout=stdout)
    with pytest.raises(bootstrap.BootstrapError, match="produced no result"):
        bootstrap.attest("/py", run)


def test_a_host_without_dpkg_refuses_explicitly():
    def missing(command, **_options):
        raise FileNotFoundError(command[0])
    with pytest.raises(bootstrap.BootstrapError, match="Debian-family environment is required"):
        bootstrap.native_prerequisites(missing, _which())


def test_unit_lane_builds_c_psycopg_before_a_wheel_only_project_closure():
    wf_path = ROOT / ".github/workflows/repomap-unit-tests.yml"
    if not wf_path.is_file():
        wf_path = ROOT / ".github/workflows/repomap-release-qualification.yml"
    workflow = wf_path.read_text(encoding="utf-8")
    bootstrap_step = workflow.index("run: python tools/ci/psycopg_bootstrap.py --python python")
    closure_step = workflow.index("tools/ci/project_dependencies.lock\n")
    assert bootstrap_step < closure_step, "C Psycopg must be built before the closure step"
    assert 'PIP_ONLY_BINARY: ":all:"' in workflow[bootstrap_step:closure_step], "the closure must refuse sdist builds"
