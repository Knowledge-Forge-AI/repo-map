"""ADR 0089 baseline-preserving selection and preinstall refusals (no live apt, compiler or backend).

The double is a small resolver over real archive bytes. In its simulation a
``name=version`` argument holds that package at that version; an unheld
installed package may be upgraded to satisfy an exact dependency, and a new
package takes its newest version whose exact dependencies remain satisfiable.
On download and install an installed-version pin is a hold, never a new
archive or a reinstallation; only the remaining pins are cached and installed.
It changes package state only on the final ``--no-download`` install. Whether
live APT's resolver chooses older additions the same way is not exercised.

This double does not model an upgrade when download or install drops a hold.
That mutation belongs to ``d12_apt_prerequisites.unit.test.py``, whose world
models native ``libc-bin``/``libc6`` upgrades; its foreign ``armhf`` row is
checked only by exact command tails, and an unqualified foreign hold fails as a
lookup error inside that double, not as a modelled APT refusal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ci import psycopg_bootstrap

# The hosted-lane bootstrap imports the one canonical helper module; reuse that module object.
apt = psycopg_bootstrap.apt
assert Path(str(apt.__file__)).resolve() == psycopg_bootstrap.APT_PREREQUISITES.resolve(), apt.__file__

OLD, NEW_LIBC = "2.41-12+deb13u2", "2.41-12+deb13u3"
# Installed rows: (name, arch) -> (version, three-character Status-Abbrev, source).
BASE = {("libc6", "arm64"): (OLD, "ii ", "glibc"),
        ("python3-minimal", "arm64"): ("3.13.5-1", "ii ", "python3-defaults"),
        ("tzdata", "all"): ("2025b-4", "ii ", "tzdata"), ("oldconf", "arm64"): ("1.0-1", "rc ", "oldconf")}
# Available versions, newest first: name -> [(version, arch, {dependency: exact version or None})].
Available = dict[str, list[tuple[str, str, dict[str, str | None]]]]
AVAILABLE: Available = {
    "libc6": [(NEW_LIBC, "arm64", {}), (OLD, "arm64", {})],
    "libc6-dev": [(NEW_LIBC, "arm64", {"libc6": NEW_LIBC}), (OLD, "arm64", {"libc6": OLD})],
    "gcc": [("4:14.2.0-1", "arm64", {"libc6-dev": None})],
    "libpq5": [("17.6-1", "arm64", {})],
    "libpq-dev": [("17.6-1", "arm64", {"libpq5": "17.6-1"})],
}
REQUESTED = ["gcc", "libpq-dev", "libpq5"]
ADDED = {"gcc": "4:14.2.0-1", "libc6-dev": OLD, "libpq-dev": "17.6-1", "libpq5": "17.6-1"}


def archive(name: str, version: str, architecture: str) -> bytes:
    return f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n\n".encode() + name.encode() * 64


class Unsatisfiable(Exception):
    pass


class Debian:
    def __init__(self, tmp_path: Path) -> None:
        self.cache = tmp_path / "cache"
        self.rows = dict(BASE)
        self.available = {name: list(versions) for name, versions in AVAILABLE.items()}
        self.targets = [{"Created-By": "Packages", "Trusted": "yes", "Filename": "/lists/main_Packages",
                         "Origin": "Debian", "Label": "Debian", "Suite": "stable", "Codename": "trixie",
                         "Component": "main", "Repo-URI": "http://deb.debian.org/debian/",
                         "Signed-By": "/usr/share/keyrings/debian-archive-keyring.gpg"}]
        self.overrides: dict[tuple[str, str], dict[str, str]] = {}
        self.forced_simulation: str | None = None
        self.removed_at_install: tuple[str, ...] = ()
        self.calls: list[list[str]] = []

    def installed(self, name: str) -> str | None:
        return next((v for (n, _a), (v, s, _src) in self.rows.items() if n == name and s == "ii "), None)

    def resolve(self, arguments: list[str]) -> list[tuple[str, str | None, str, str]]:
        held = {item.split("=", 1)[0].split(":", 1)[0]: item.split("=", 1)[1] for item in arguments if "=" in item}
        chosen: dict[str, tuple[str | None, str, str]] = {}

        def need(name: str, exact: str | None) -> None:
            current = chosen[name][1] if name in chosen else self.installed(name)
            if name in held:
                if exact not in (None, held[name]) or (current is not None and current != held[name]):
                    raise Unsatisfiable(name)
                if current is None:
                    install(name, held[name])
            elif current is not None:
                if exact is not None and exact != current:
                    install(name, exact, previous=current)
            else:
                for version, _arch, _deps in self.available[name]:
                    if exact in (None, version):
                        saved = dict(chosen)
                        try:
                            install(name, version)
                        except Unsatisfiable:
                            chosen.clear()
                            chosen.update(saved)
                        else:
                            return
                raise Unsatisfiable(name)

        def install(name: str, version: str, previous: str | None = None) -> None:
            arch, deps = next((a, d) for v, a, d in self.available[name] if v == version)
            chosen[name] = (previous, version, arch)
            for dependency, exact in deps.items():
                need(dependency, exact)

        for item in arguments:
            name = item.split("=", 1)[0].split(":", 1)[0]
            need(name, held.get(name))
        return [(name, previous, version, arch) for name, (previous, version, arch) in sorted(chosen.items())]

    def record(self, name: str, version: str, arch: str) -> dict[str, str]:
        data = archive(name, version, arch)
        return {"Package": name, "Version": version, "Architecture": arch, "Size": str(len(data)),
                "SHA256": hashlib.sha256(data).hexdigest(), "Filename": f"pool/{name}_{version}.deb",
                **self.overrides.get((name, version), {})}

    def __call__(self, command, **_options):
        self.calls.append(list(command))
        if command[:2] == ["dpkg-query", "-W"]:
            return self.done("".join(f"{n}\t{a}\t{v}\t{s}\t{src}\t{v}\n"
                                     for (n, a), (v, s, src) in sorted(self.rows.items())))
        if command == ["dpkg", "--print-architecture"]:
            return self.done("arm64\n")
        if command == ["apt-get", "update"] or command[:2] == ["apt-mark", "auto"]:
            return self.done("")
        if command == ["apt-get", "indextargets"]:
            return self.done("\n\n".join("\n".join(f"{k}: {v}" for k, v in t.items()) for t in self.targets) + "\n")
        if command[0] == "/usr/lib/apt/apt-helper":
            return self.done("".join("".join(f"{k}: {v}\n" for k, v in self.record(n, v, a).items()) + "\n"
                                     for n, versions in self.available.items() for v, a, _d in versions))
        if command[0] == "dpkg-deb":
            return self.done(Path(command[2]).read_bytes().split(b"\n\n", 1)[0].decode() + "\n")
        pins = [item for item in command[4:] if not item.startswith(("-", "Dir::"))]
        held = {f"{n}={v}" if a in ("arm64", "all") else f"{n}:{a}={v}" for (n, a), (v, s, _) in self.rows.items()
                if s == "ii "}  # an installed-version pin holds that row; download and install add only the rest
        if command[:3] == ["apt-get", "install", "--simulate"]:
            if self.forced_simulation is not None:
                return self.done(self.forced_simulation)
            try:
                plan = self.resolve(pins)
            except Unsatisfiable:
                return self.done("E: Unable to correct problems, you have held broken packages.\n", 100)
            lines = [f"Inst {n} {f'[{p}] ' if p else ''}({v} Debian:13.1/stable [{a}])" for n, p, v, a in plan]
            return self.done("\n".join(lines + [f"Conf {n} ({v} Debian:13.1/stable [{a}])" for n, _p, v, a in plan]))
        if "--download-only" in command:
            for pin in [pin for pin in pins if pin not in held]:
                name, version = pin.split("=", 1)
                arch = next(a for v, a, _d in self.available[name] if v == version)
                (self.cache / f"{name}_{version}.deb").write_bytes(archive(name, version, arch))
            return self.done("")
        if "--no-download" in command:
            if self.removed_at_install and "--no-remove" in command:
                return self.done("E: Packages need to be removed but remove is disabled.\n", 100)
            for name in self.removed_at_install:
                self.rows = {key: row for key, row in self.rows.items() if key[0] != name}
            for pin in [pin for pin in pins if pin not in held]:
                name, version = pin.split("=", 1)
                arch, source = next(a for v, a, _d in self.available[name] if v == version), name
                self.rows[(name, arch)] = (version, "ii ", source)
            return self.done("")
        raise AssertionError(f"unexpected command {command}")

    @staticmethod
    def done(stdout: str, returncode: int = 0):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    def simulations(self) -> list[list[str]]:
        return [c for c in self.calls if "--simulate" in c]

    def downloads(self) -> list[list[str]]:
        return [c for c in self.calls if "--download-only" in c]

    def installs(self) -> list[list[str]]:
        return [c for c in self.calls if "--no-download" in c]


def plain(tmp_path: Path) -> Debian:
    """A world whose only ``libc6-dev`` matches the baseline, so each refusal is attributable to its own case."""
    world = Debian(tmp_path)
    world.available["libc6-dev"] = world.available["libc6-dev"][1:]
    return world


def refuse(world: Debian, message: str, requested: list[str] = REQUESTED) -> None:
    with pytest.raises(apt.PrerequisiteRefused, match=message):
        apt.install_prerequisites(world, requested, world.cache)
    assert world.installs() == [], f"refusal must precede installation: {world.installs()}"
    assert world.rows == BASE, f"refusal changed package state: {world.rows}"


def test_baseline_pins_let_the_resolver_choose_compatible_older_additions(tmp_path):
    world = Debian(tmp_path)
    evidence = apt.install_prerequisites(world, REQUESTED, world.cache)
    simulate = world.simulations()[0]
    assert {"libc6=" + OLD, "python3-minimal=3.13.5-1", "tzdata=2025b-4"} <= set(simulate), simulate
    assert not [item for item in simulate if item.startswith(("oldconf", "tzdata:"))], "rc and arch-all pins"
    assert evidence["added"] == sorted(f"{n}:arm64={v}" for n, v in ADDED.items()), evidence["added"]
    assert world.installed("libc6") == OLD, "the pre-existing libc6 is preserved, not upgraded"
    download, install = world.downloads()[0], world.installs()[0]
    holds = ["libc6=" + OLD, "python3-minimal=3.13.5-1", "tzdata=2025b-4"]  # every ii row; the rc row is not held
    assert "--no-remove" in download and "--no-remove" in install
    assert download[download.index("--download-only") + 1:] == install[install.index("--no-download") + 1:] == [
        *holds, *sorted(f"{n}={v}" for n, v in ADDED.items())], "both carry the holds, then only the additions"
    assert {key: world.rows[key] for key in BASE} == BASE, "held rows keep their version, state and source"
    for item in evidence["packages"]:
        data = archive(item["name"], item["version"], item["architecture"])
        assert (item["sha256"], item["size"]) == (hashlib.sha256(data).hexdigest(), len(data)), item


def test_unconstrained_newest_selection_would_upgrade_the_baseline(tmp_path):
    world = Debian(tmp_path)
    plan = world.resolve(["gcc"])
    assert ("libc6", OLD, NEW_LIBC, "arm64") in plan, "the double upgrades an unheld baseline package"
    held = world.resolve(["libc6=" + OLD, "gcc"])
    assert ("libc6-dev", None, OLD, "arm64") in held and all(row[1] is None for row in held), held


def test_unsatisfiable_baseline_closure_refuses_before_any_download(tmp_path):
    world = Debian(tmp_path)
    world.available["libc6-dev"] = world.available["libc6-dev"][:1]
    refuse(world, "failed with exit 100")
    assert world.downloads() == [] and "libc6=" + OLD in world.simulations()[0]


def test_error_flagged_package_state_refuses(tmp_path):
    world = plain(tmp_path)
    world.rows[("libc6", "arm64")] = (OLD, "iiR", "glibc")
    with pytest.raises(apt.PrerequisiteRefused, match="not ii/rc"):
        apt.install_prerequisites(world, REQUESTED, world.cache)
    assert world.simulations() == [] and world.installs() == []


@pytest.mark.parametrize("simulation,missing", [
    ("", "'gcc', 'libpq-dev', 'libpq5'"),
    ("Inst libpq5 (17.6-1 Debian:13.1/stable [arm64])\nConf libpq5 (17.6-1 Debian:13.1/stable [arm64])\n",
     "'gcc', 'libpq-dev'"),
])
def test_simulation_that_omits_a_requested_package_refuses(tmp_path, simulation, missing):
    world = plain(tmp_path)
    world.forced_simulation = simulation
    refuse(world, f"does not install requested packages: \\[{missing}\\]")
    assert world.downloads() == []


@pytest.mark.parametrize("absent", [
    ("Origin", "Label", "Suite", "Codename", "Component", "Repo-URI", "Signed-By"),
    ("Origin",), ("Repo-URI",), ("Suite", "Codename"),
])
def test_trusted_target_without_resolved_provenance_refuses(tmp_path, absent):
    world = plain(tmp_path)
    world.targets[0] = {key: value for key, value in world.targets[0].items() if key not in absent}
    refuse(world, "provenance is unresolved")
    assert world.downloads() == []


def test_optional_signed_by_absence_is_recorded_not_invented(tmp_path):
    world = plain(tmp_path)
    del world.targets[0]["Signed-By"]
    evidence = apt.install_prerequisites(world, REQUESTED, world.cache)
    assert {origin["Signed-By"] for origin in evidence["trusted_targets"]} == {""}, evidence["trusted_targets"]


def test_distinct_selections_sharing_one_archive_digest_refuse_before_download(tmp_path):
    world = plain(tmp_path)
    forged = world.record("libpq-dev", "17.6-1", "arm64")
    world.overrides[("libpq5", "17.6-1")] = {"SHA256": forged["SHA256"], "Size": forged["Size"]}
    refuse(world, "distinct selections share one archive sha256")
    assert world.downloads() == []


def test_duplicate_digest_in_a_manifest_refuses_archive_verification(tmp_path):
    item = {"name": "libpq5", "version": "17.6-1", "architecture": "arm64", "sha256": "a" * 64, "size": 1}
    tmp_path.joinpath("libpq5.deb").write_bytes(b"x")
    with pytest.raises(apt.PrerequisiteRefused, match="ambiguous archive identity"):
        apt.verify_archives(lambda *_a, **_k: pytest.fail("no dpkg-deb call"), [item, {**item, "name": "x"}], tmp_path)


def test_final_install_aborts_a_removal_instead_of_performing_it(tmp_path):
    world = plain(tmp_path)
    world.removed_at_install = ("python3-minimal",)
    with pytest.raises(apt.PrerequisiteRefused, match="failed with exit 100"):
        apt.install_prerequisites(world, REQUESTED, world.cache)
    install = world.installs()
    assert len(install) == 1 and "--no-remove" in install[0], install
    assert world.rows == BASE, f"the aborted install removed or added packages: {world.rows}"


# Representative failure output: the useful APT constraint must survive; credentials, endpoints,
# private paths, addresses, tokens and environment values must not.
CONSTRAINT = "libc6-dev : Depends: libc6 (= 2.41-12+deb13u3) but 2.41-12+deb13u2 is to be installed"
PRIVATE_ENV = "env-private-value-0123456789"
SENSITIVE = ("s3cr3t-pass", "tok-123456", "private.mirror.internal", "/Users/alice", "/run/secrets", "Bearer-abc",
             PRIVATE_ENV, "10.1.2.3", "\x1b")
FAILED_STDOUT = f"Reading package lists...\nThe following packages have unmet dependencies:\n {CONSTRAINT}\n"
FAILED_STDERR = ("W: Failed to fetch https://user:s3cr3t-pass@private.mirror.internal/debian/dists/trixie/InRelease\n"
                 "W: Authorization: Bearer-abc tok-123456\n\x1b[31mW: Could not resolve 'private.mirror.internal'"
                 " (10.1.2.3) for /Users/alice/.netrc or /run/secrets/apt\x1b[0m\n"
                 f"N: proxy {PRIVATE_ENV}\nE: Unable to correct problems, you have held broken packages.\n")


def leaks(message: str) -> list[str]:
    return [secret for secret in SENSITIVE if secret in message]


def test_simulation_failure_reports_the_redacted_constraint_before_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOMAP_D12_PRIVATE_SETTING", PRIVATE_ENV)
    world = plain(tmp_path)

    def run(command, **options):
        if command[:3] == ["apt-get", "install", "--simulate"]:
            world.calls.append(list(command))
            assert options["env"]["REPOMAP_D12_PRIVATE_SETTING"] == PRIVATE_ENV
            return SimpleNamespace(returncode=100, stdout=FAILED_STDOUT, stderr=FAILED_STDERR)
        return world(command, **options)
    with pytest.raises(apt.PrerequisiteRefused, match="--simulate failed with exit 100") as refused:
        apt.install_prerequisites(run, REQUESTED, world.cache)
    message = str(refused.value)
    assert CONSTRAINT in message and "held broken packages" in message, message
    assert leaks(message) == [], f"diagnostic leaked {leaks(message)}: {message}"
    assert world.downloads() == [] and world.installs() == [] and world.rows == BASE


def test_command_diagnostics_redact_before_bounding():
    secret = "Q7" * 3000  # straddles the tail bound, so bounding before redaction would leak part of it
    tail = (
        f"Err:1 https://mirror.example/debian?sig={secret}\n"
        "E: Unable to correct problems, you have held broken packages.\n")
    for stdout, stderr, kept in (
        (FAILED_STDOUT, tail, CONSTRAINT), ("", "W: filler\n" * 5000 + "E: last\n", "E: last"),
    ):
        done = subprocess.CompletedProcess([], 100, stdout, stderr)
        with pytest.raises(apt.PrerequisiteRefused) as refused:
            apt.command_output(lambda *_a, **_k: done, ["apt-get", "install", "--simulate", "gcc"])
        message = str(refused.value)
        assert "Q7Q7" not in message and kept in message and len(message) <= 4200, (len(message), message[:300])
    quiet = subprocess.CompletedProcess([], 100, "", None)
    with pytest.raises(apt.PrerequisiteRefused, match="^apt-get update failed with exit 100$"):
        apt.command_output(lambda *_a, **_k: quiet, ["apt-get", "update"])


def test_cli_refusal_output_is_redacted(tmp_path, capsys):
    world = plain(tmp_path)
    world.targets[0].update(Trusted="no", Description="https://user:s3cr3t-pass@private.mirror.internal/debian")
    assert apt.main(["install", "--cache", str(world.cache), *REQUESTED], run=world) == 2
    error = capsys.readouterr().err
    assert "Packages index trust is unknown" in error and leaks(error) == [], error
    assert world.installs() == [] and world.rows == BASE
