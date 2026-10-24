"""ADR 0089 D5/D6 preinstallation custody of native prerequisites (no live apt, compiler or backend).

An in-memory Debian world answers the helper's exact commands: a dpkg database, trusted ``Packages``
indexes, and a mirror whose archives are real bytes. Like APT, every operation holds an installed package
only through an explicit installed-version pin; otherwise its newer candidate is selected.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from ci import psycopg_bootstrap

ROOT = Path(__file__).resolve().parents[5]
apt = psycopg_bootstrap.apt  # reuse the bootstrap's statically imported canonical helper module
assert Path(str(apt.__file__)).resolve() == ROOT / "tools/native_apt_prerequisites.py", apt.__file__

BASE = {"libc-bin": ("arm64", "2.41-12", "glibc"), "libc6": ("arm64", "2.41-12", "glibc"),
        "libgcc-s1": ("armhf", "14.2.0-19", "gcc-14"), "python3-minimal": ("arm64", "3.13.5-1", "python3-defaults")}
UPGRADES = {name: ("arm64", "2.41-12+deb13u4", "glibc") for name in ("libc-bin", "libc6")}  # essential, newer
NEW = {"gcc": ("arm64", "4:14.2.0-1", "gcc-defaults"), "libpq-dev": ("arm64", "17.6-1", "postgresql-17"),
       "libpq5": ("arm64", "17.6-1", "postgresql-17"), "postgresql-common-dev": ("all", "278", "postgresql-common")}
REQUESTED = ["gcc", "libpq-dev", "libpq5"]
HELD = ["libc-bin=2.41-12", "libgcc-s1:armhf=14.2.0-19", "python3-minimal=3.13.5-1", "libc6=2.41-12"]


def archive(name: str, version: str, architecture: str) -> bytes:
    return f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n\n".encode() + name.encode() * 64


def upgrade(name: str, old: str, new: str) -> list[str]:
    return [f"Inst {name} [{old}] ({new} Debian:13.2/stable [arm64]) []",
            f"Conf {name} ({new} Debian:13.2/stable [arm64])"]


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.cache = tmp_path / "cache"
        self.rows = {name: (arch, version, "ii", source) for name, (arch, version, source) in BASE.items()}
        self.mirror = {name: archive(name, version, arch) for name, (arch, version, _s) in {**NEW, **UPGRADES}.items()}
        self.simulation = [f"{verb} {name} ({version} Debian:13.1/stable [{arch}])"
                           for verb in ("Inst", "Conf") for name, (arch, version, _s) in NEW.items()]
        self.targets = [{"Created-By": "Packages", "Trusted": "yes", "Filename": "/lists/main_Packages",
                         "Origin": "Debian", "Label": "Debian", "Suite": "stable", "Codename": "trixie",
                         "Component": "main", "Repo-URI": "http://deb.debian.org/debian/"}]
        self.index = {"/lists/main_Packages": [self.record(name) for name in NEW]}
        self.calls: list[list[str]] = []
        self.frozen: bytes | None = None
        self.modes: set[int] = set()
        self.on_download: Callable[[World], object] | None = None
        self.on_install: Callable[[World], object] | None = None
        self.simulate_exit = 0

    def record(self, name: str, **override: str) -> dict[str, str]:
        arch, version, _source = NEW[name]
        data = self.mirror[name]
        return {"Package": name, "Version": version, "Architecture": arch, "Size": str(len(data)),
                "SHA256": hashlib.sha256(data).hexdigest(), "Filename": f"pool/{name}.deb", **override}

    def dpkg_rows(self) -> str:
        return "".join(f"{name}\t{arch}\t{version}\t{status} \t{source}\t{version}\n"
                       for name, (arch, version, status, source) in sorted(self.rows.items()))

    def __call__(self, command, **options):
        self.calls.append(list(command))
        if command[:2] == ["dpkg-query", "-W"]:
            return self.done(self.dpkg_rows())
        if command == ["dpkg", "--print-architecture"]:
            return self.done("arm64\n")
        if command == ["apt-get", "update"] or command[:2] == ["apt-mark", "auto"]:
            return self.done("")
        if command == ["apt-get", "indextargets"]:
            return self.done("\n\n".join("\n".join(f"{k}: {v}" for k, v in t.items()) for t in self.targets) + "\n")
        if command[0] == "/usr/lib/apt/apt-helper":
            records = self.index[command[2]]
            return self.done("".join("".join(f"{k}: {v}\n" for k, v in r.items()) + "Description: x\n more\n\n"
                                     for r in records))
        if command[0] == "dpkg-deb":
            head = Path(command[2]).read_bytes().split(b"\n\n", 1)[0].decode()
            return self.done(head + "\n")
        if command[:2] == ["apt-get", "install"] and "--simulate" in command:
            plan = [line for n in self.unheld(command) for line in upgrade(n, self.rows[n][1], UPGRADES[n][1])]
            return self.done("\n".join(self.simulation + plan) + "\n", self.simulate_exit)
        if command[:2] == ["apt-get", "install"] and "--download-only" in command:
            for name in self.added(command, "--download-only") + self.unheld(command):
                (self.cache / f"{name}.deb").write_bytes(self.mirror[name])
            if self.on_download:
                self.on_download(self)
            return self.done("")
        if command[:2] == ["apt-get", "install"] and "--no-download" in command:
            self.frozen = (self.cache / "manifest.json").read_bytes()
            self.modes = {path.stat().st_mode & 0o777 for path in self.cache.glob("*.deb")}
            if self.unheld(command):  # the verified frozen cache never holds an upgrade's archive
                return self.done("E: Unable to fetch some archives\n", 100)
            for name in self.added(command, "--no-download"):
                self.rows[name] = (NEW[name][0], NEW[name][1], "ii", NEW[name][2])
            if self.on_install:
                self.on_install(self)
            return self.done("")
        raise AssertionError(f"unexpected command {command}")

    @staticmethod
    def done(stdout: str, returncode: int = 0):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    def added(self, command: list[str], flag: str) -> list[str]:  # an installed-version pin holds; others add NEW
        holds = {f"{n}={v}" if a in ("arm64", "all") else f"{n}:{a}={v}" for n, (a, v, _t, _s) in self.rows.items()}
        pins = [pin.split("=", 1) for pin in command[command.index(flag) + 1:] if pin not in holds]
        assert all(NEW[name][1] == version for name, version in pins), pins
        return [name for name, _version in pins]

    def unheld(self, command: list[str]) -> list[str]:
        return [name for name in UPGRADES if f"{name}={self.rows[name][1]}" not in command]

    def installs(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["apt-get", "install"]
                and not {"--simulate", "--download-only"}.intersection(c)]

    def downloads(self) -> list[list[str]]:
        return [c for c in self.calls if "--download-only" in c]


def test_exact_frozen_archives_are_installed_only_after_binding_and_verification(tmp_path):
    world = World(tmp_path)
    _alias(world)  # libpq5's bytes are also advertised by a second trusted index under another path
    evidence = apt.install_prerequisites(world, [*REQUESTED, "libc6"], world.cache)  # libc6 is already installed
    verbs = [" ".join(c[:2]) for c in world.calls]
    assert verbs.index("apt-get update") < verbs.index("apt-get indextargets") < world.calls.index(
        world.downloads()[0]) < world.calls.index(world.installs()[0])
    pins = sorted(f"{name}={version}" for name, (_a, version, _s) in NEW.items())
    install, download = world.installs()[0], world.downloads()[0]
    simulate = next(c for c in world.calls if "--simulate" in c)
    assert simulate[simulate.index("--no-install-recommends") + 1:] == [*HELD, *REQUESTED], "the simulated holds"
    assert download[download.index("--download-only") + 1:] == install[install.index("--no-download") + 1:] == [
        *HELD, *pins], "download and installation carry the simulated holds and only the frozen additions"
    assert f"Dir::Cache::Archives={world.cache}/" in install and evidence["already_installed"] == {"libc6": "2.41-12"}
    assert {name: world.rows[name][1] for name in BASE} == {name: version for name, (_a, version, _s) in BASE.items()}
    assert world.modes == {0o444}, "frozen archives are read-only before installation"
    assert world.frozen is not None
    manifest = json.loads(world.frozen)
    assert hashlib.sha256(world.frozen).hexdigest() == evidence["manifest_sha256"]
    assert manifest["packages"] == evidence["packages"] and len(manifest["archives"]) == len(NEW)
    for item in evidence["packages"]:
        data = world.mirror[item["name"]]
        assert (item["sha256"], item["size"]) == (hashlib.sha256(data).hexdigest(), len(data))
        assert item["origins"][0]["Origin"] == "Debian" and item["origins"][0]["Codename"] == "trixie"
    libpq5 = next(item for item in manifest["packages"] if item["name"] == "libpq5")
    assert [(place["filename"], place["Suite"]) for place in libpq5["locations"]] == [
        ("pool/libpq5.deb", "stable"), ("pool/updates/libpq5.deb", "stable-security")], "every path keeps its index"
    assert libpq5["filename"] == "pool/libpq5.deb" and "not the path" in manifest["filename_role"]
    assert evidence["added"] == sorted(f"{n}:{a}={v}" for n, (a, v, _s) in NEW.items())
    assert world.calls[world.calls.index(install) + 1] == ["apt-mark", "auto", "postgresql-common-dev"]
    assert evidence["reproducibility"].endswith("not release reproducibility")
    assert not world.cache.exists(), "verified archives are discarded after installation"


def _alias(world, target=(), **record):
    world.targets.append({**world.targets[0], "Filename": "/lists/security_Packages", "Suite": "stable-security",
                          **dict(target)})
    world.index["/lists/security_Packages"] = [world.record("libpq5", **{"Filename": "pool/updates/libpq5.deb",
                                                                          **record})]


def _md5_only(world):
    record = world.index["/lists/main_Packages"][0]
    record["MD5sum"] = hashlib.md5(b"x").hexdigest()
    del record["SHA256"]


def _foreign(world):
    world.simulation = [line.replace("[all]", "[amd64]") for line in world.simulation]


def _unconfigured(world):
    world.simulation = [line for line in world.simulation if not line.startswith("Conf gcc ")]


@pytest.mark.parametrize("mutate,message", [
    (lambda world: world.simulation.extend(upgrade("libc6", "2.41-12", "2.41-12+deb13u1")),
     "changes installed libc6:arm64 2.41-12 -> 2.41-12\\+deb13u1"),
    (lambda world: world.simulation.append("Remv python3-minimal [3.13.5-1]"), "removes an installed package"),
    (lambda world: world.index["/lists/main_Packages"].pop(), "has 0 trusted index identities"),
    (lambda world: _alias(world, SHA256="0" * 64), "libpq5=17.6-1:arm64 has 2 trusted index identities"),
    (lambda world: _alias(world, Size="1"), "libpq5=17.6-1:arm64 has 2 trusted index identities"),
    (lambda world: world.targets[0].update(Trusted="no"), "trust is unknown or absent"),
    (lambda world: _alias(world, {"Trusted": "no"}), "trust is unknown or absent"),
    (lambda world: _alias(world, {"Origin": ""}), "provenance is unresolved"),
    (lambda world: _alias(world, Filename=""), "libpq5 has a trusted index record without a Filename"),
    (_md5_only, "no exact SHA-256"),
    (_foreign, "foreign architecture"),
    (lambda world: world.simulation.append("Inst libpq5"), "unrecognized simulated transaction line"),
    (_unconfigured, "configures a different package set"),
    (lambda world: setattr(world, "simulate_exit", 100), "failed with exit 100"),
])
def test_unprovable_transaction_refuses_before_download_or_install(tmp_path, mutate, message):
    world = World(tmp_path)
    mutate(world)
    with pytest.raises(apt.PrerequisiteRefused, match=message):
        apt.install_prerequisites(world, REQUESTED, world.cache)
    assert world.downloads() == [] and world.installs() == []
    assert dict(world.rows) == {name: (arch, version, "ii", source) for name, (arch, version, source) in BASE.items()}


def _flip_byte(world):
    path = world.cache / "libpq5.deb"
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))


@pytest.mark.parametrize("mutate,message", [
    (_flip_byte, "libpq5.deb does not match the frozen manifest"),
    (lambda world: (world.cache / "libssl3t64.deb").write_bytes(archive("libssl3t64", "3.5.1-1", "arm64")),
     "libssl3t64.deb does not match the frozen manifest"),
    (lambda world: (world.cache / "gcc.deb").unlink(), "cached archives are missing"),
    (lambda world: world.rows.__setitem__("libc6", ("arm64", "2.41-12+deb13u1", "ii", "glibc")),
     "drifted before installation"),
])
def test_downloaded_bytes_and_state_are_verified_before_install(tmp_path, mutate, message):
    world = World(tmp_path)
    world.on_download = mutate
    with pytest.raises(apt.PrerequisiteRefused, match=message):
        apt.install_prerequisites(world, REQUESTED, world.cache)
    assert len(world.downloads()) == 1 and world.installs() == []


def test_index_record_must_describe_the_archive_control_fields(tmp_path):
    world = World(tmp_path)
    forged = archive("libpq5", "17.7-1", "arm64")
    world.mirror["libpq5"] = forged
    world.index["/lists/main_Packages"][2] = world.record("libpq5")
    with pytest.raises(apt.PrerequisiteRefused, match="control fields differ"):
        apt.install_prerequisites(world, REQUESTED, world.cache)
    assert world.installs() == []


def test_installed_state_is_rechecked_after_installation(tmp_path):
    world = World(tmp_path)
    world.on_install = lambda w: w.rows.__setitem__("libc6", ("arm64", "2.41-13", "ii", "glibc"))
    with pytest.raises(apt.PrerequisiteRefused, match="differs from the frozen manifest"):
        apt.install_prerequisites(world, REQUESTED, world.cache)


def test_installed_request_is_pinned_and_an_empty_transaction_installs_nothing(tmp_path):
    world = World(tmp_path)
    world.rows["libpq5"] = ("arm64", "17.5-1", "ii", "postgresql-17")
    world.simulation = []
    evidence = apt.install_prerequisites(world, ["libpq5"], world.cache)
    simulate = next(c for c in world.calls if "--simulate" in c)
    assert simulate[-1] == "libpq5=17.5-1" and evidence["already_installed"] == {"libpq5": "17.5-1"}
    assert evidence["packages"] == [] and world.downloads() == [] and world.installs() == []


@pytest.mark.parametrize("requested,setup,message", [
    (["gcc", "Bad Name"], None, "names are not exact"),
    (["gcc"], "cache", "cache is not empty"),
    (["gcc"], "half", "not ii/rc"),
])
def test_invalid_request_cache_or_database_refuses_first(tmp_path, requested, setup, message):
    world = World(tmp_path)
    if setup == "cache":
        world.cache.mkdir()
        (world.cache / "stale.deb").write_bytes(b"stale")
    if setup == "half":
        world.rows["libc6"] = ("arm64", "2.41-12", "iU", "glibc")
    with pytest.raises(apt.PrerequisiteRefused, match=message):
        apt.install_prerequisites(world, requested, world.cache)
    assert world.downloads() == [] and world.installs() == []


LIBPQ = {"libpq-dev": ("arm64", "17.6-1", "ii", "postgresql-17"), "libpq5": ("arm64", "17.6-1", "ii", "postgresql-17"),
         "postgresql-client-17": ("arm64", "17.6-1", "ii", "postgresql-17"),
         "postgresql-common": ("all", "278", "ii", "postgresql-common")}
OWNED = {"/usr/lib/postgresql/17/bin/pg_config": "postgresql-client-17", "/usr/bin/pg_config": "postgresql-common",
         "/usr/include/postgresql/libpq-fe.h": "libpq-dev", "/usr/lib/aarch64-linux-gnu/libpq.so.5.17": "libpq5"}
LINKS = {"/opt/relocated/bin/pg_config": "/usr/lib/postgresql/17/bin/pg_config",
         "/usr/lib/aarch64-linux-gnu/libpq.so.5": "/usr/lib/aarch64-linux-gnu/libpq.so.5.17"}


def libpq_world(rows=LIBPQ, owned=OWNED, diverted=()):
    calls = []

    def run(command, **_options):
        calls.append(list(command))
        if command[:2] == ["dpkg-query", "-W"]:
            return World.done("".join(f"{n}\t{a}\t{v}\t{s} \t{src}\t{v}\n" for n, (a, v, s, src) in rows.items()))
        if command[:2] == ["dpkg-query", "-S"]:
            if command[2] in diverted:
                return World.done(f"diversion by local from: {command[2]}\n")
            owner = owned.get(command[2])
            return World.done(f"{owner}:arm64: {command[2]}\n" if owner else "", 0 if owner else 1)
        if command[0].endswith("/pg_config"):
            values = {"--includedir": "/usr/include/postgresql", "--libdir": "/usr/lib/aarch64-linux-gnu",
                      "--version": "PostgreSQL 17.6"}
            return World.done(values[command[1]] + "\n")
        raise AssertionError(f"unexpected command {command}")
    return run, calls


def attest(run, executable="/opt/relocated/bin/pg_config"):
    return apt.attest_libpq(run, which=lambda name: executable if name == "pg_config" else None,
                            realpath=lambda path: LINKS.get(path, path))


def test_relocated_path_pg_config_is_bound_by_realpath_not_bindir():
    run, calls = libpq_world()
    evidence = attest(run)
    assert evidence["pg_config"] == {"path": "/opt/relocated/bin/pg_config", "package": "postgresql-client-17",
                                     "realpath": "/usr/lib/postgresql/17/bin/pg_config",
                                     "package_version": "17.6-1", "version": "PostgreSQL 17.6"}
    assert evidence["owners"] == {"pg_config": "postgresql-client-17", "libpq-fe.h": "libpq-dev",
                                  "libpq.so.5": "libpq5"}
    assert evidence["paths"]["libpq.so.5"] == "/usr/lib/aarch64-linux-gnu/libpq.so.5.17"
    queried = [c for c in calls if c[0].endswith("pg_config")]
    assert {c[0] for c in queried} == {"/opt/relocated/bin/pg_config"} and ["--bindir"] not in [c[1:] for c in queried]


@pytest.mark.parametrize("executable,rows,owned,diverted,message", [
    ("/usr/bin/pg_config", LIBPQ, OWNED, (), "owned by postgresql-common, not by the postgresql-17 17.6-1"),
    ("/opt/unowned/pg_config", LIBPQ, OWNED, (), "owned by no package"),
    ("/opt/relocated/bin/pg_config", {**LIBPQ, "libpq5": ("arm64", "18.1-1", "ii", "postgresql-18")}, OWNED, (),
     "headers and runtime differ"),
    ("/opt/relocated/bin/pg_config", {k: v for k, v in LIBPQ.items() if k != "libpq-dev"}, OWNED, (),
     "not each installed exactly once"),
    ("/opt/relocated/bin/pg_config", LIBPQ, {**OWNED, "/usr/include/postgresql/libpq-fe.h": "libpq-private"}, (),
     "not owned by that pair"),
    ("/opt/relocated/bin/pg_config", LIBPQ, OWNED, ("/usr/lib/postgresql/17/bin/pg_config",), "is diverted"),
    (None, LIBPQ, OWNED, (), "not on PATH"),
])
def test_pg_config_header_and_runtime_must_share_one_libpq_source(executable, rows, owned, diverted, message):
    run, _calls = libpq_world(rows, owned, diverted)
    with pytest.raises(apt.PrerequisiteRefused, match=message):
        attest(run, executable)


def test_cli_writes_evidence_or_refuses_with_status_two(tmp_path, capsys):
    world = World(tmp_path)
    assert apt.main(["install", "--cache", str(world.cache), "Bad"], run=world) == 2
    assert "apt prerequisites refused: requested package names" in capsys.readouterr().err
    assert world.calls == []
    world.simulation = []
    world.rows["gcc"] = ("arm64", "4:14.2.0-1", "ii", "gcc-defaults")
    target = tmp_path / "evidence" / "apt.json"
    assert apt.main(["install", "--cache", str(world.cache), "--evidence", str(target), "gcc"], run=world) == 0
    assert json.loads(target.read_text())["already_installed"] == {"gcc": "4:14.2.0-1"}
    assert json.loads(capsys.readouterr().out)["schema"] == apt.SCHEMA


def test_sandbox_recipe_binds_helper_bytes_in_identity_label_args_and_staged_context(tmp_path, monkeypatch):
    import test_sandbox as sandbox

    images, context, image_id = sandbox._images, tmp_path / "context", "sha256:" + "5" * 64
    context.mkdir()
    dockerfile, decoy = context / "Dockerfile", context / "apt_prerequisites.py"
    dockerfile.write_bytes((ROOT / "tools/test_sandbox/Dockerfile").read_bytes())
    decoy.write_bytes((ROOT / "tools/test_sandbox/apt_prerequisites.py").read_bytes())  # the wrapper is never staged
    helper_bytes = (ROOT / "tools/native_apt_prerequisites.py").read_bytes()
    recipe = images.sandbox_recipe(images.sandbox_recipe_inputs(dockerfile))
    stale = images.sandbox_recipe({"Dockerfile": dockerfile.read_bytes(), "apt_prerequisites.py": helper_bytes + b"#"})
    labels, calls, staged = [stale, recipe], [], {}

    def runner(command, **_options):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            config = {sandbox.IMAGE_OWNER_LABEL: "true", sandbox.IMAGE_RECIPE_LABEL: labels.pop(0)}
            return World.done(json.dumps({"Id": image_id, "Config": {"Labels": config}}))
        if command[:2] == ["docker", "build"]:
            staged.update({path.name: path.read_bytes() for path in Path(command[-1]).iterdir()})
        return World.done(image_id + "\n" if command[:3] == ["docker", "image", "ls"] else "")

    assert sandbox.ensure_sandbox_image(dockerfile=dockerfile, runner=runner) == image_id
    build = next(command for command in calls if command[:2] == ["docker", "build"])
    assert stale != recipe != hashlib.sha256(dockerfile.read_bytes()).hexdigest(), "helper bytes invalidate"
    assert staged == {"Dockerfile": dockerfile.read_bytes(), "apt_prerequisites.py": helper_bytes}
    assert build[4:8] == ["--build-arg", f"REPOMAP_SANDBOX_RECIPE={recipe}", "--build-arg",
                          f"REPOMAP_SANDBOX_APT_HELPER_SHA256={hashlib.sha256(helper_bytes).hexdigest()}"]
    monkeypatch.setitem(images.SANDBOX_CONTEXT_SOURCES, "apt_prerequisites.py", tmp_path / "absent.py")
    calls.clear()
    with pytest.raises(RuntimeError, match="context file is absent: apt_prerequisites.py"):
        sandbox.ensure_sandbox_image(dockerfile=dockerfile, runner=runner)
    assert calls == []


def test_sandbox_recipe_installs_native_packages_only_through_the_checked_helper():
    text = (ROOT / "tools/test_sandbox/Dockerfile").read_text(encoding="utf-8")
    lines = text.replace("\\\n", " ").splitlines()
    assert "apt-get install" not in text and "ARG REPOMAP_SANDBOX_APT_HELPER_SHA256" in lines
    check = next(line for line in lines if "sha256sum --check --strict" in line)
    assert '"${REPOMAP_SANDBOX_APT_HELPER_SHA256}" /usr/local/lib/repomap/apt_prerequisites.py' in check
    assert check.index("sha256sum") < check.index("apt_prerequisites.py install") and "libpq-dev" in check.split()
    built = next(line for line in lines if "attest-libpq" in line)
    assert built.startswith("RUN --network=none") and built.index("attest-libpq") < built.index("pip install")
    assert 'org.repomap.test.sandbox.apt-helper="${REPOMAP_SANDBOX_APT_HELPER_SHA256}"' in text
