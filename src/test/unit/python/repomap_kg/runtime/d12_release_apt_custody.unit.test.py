"""ADR 0089 M2 under the host shell. Stubs on PATH: dpkg, dpkg-query, apt-get, dpkg-deb (and declared
grep/cat errors); other tools are the host's. Proves order, argv, exit status and refusals here only:
not dash, GNU, Debian, real APT or dpkg-deb, cache naming, lock or partial."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

from repomap_kg.runtime.commands import render_server_dockerfile
from repomap_kg.runtime.release import APT_WORKDIR, DebPackage, PlatformPackages, apt_custody_program, render_apt_steps

TOOLS = {tool: shutil.which(tool) for tool in ("sh", "sha256sum", "grep", "cat")}
BASE = ["ii  libc6:arm64=2.36-9+deb12u10", "ii  tzdata:all=2025b-0+deb12u1", "ii  libgcc-s1:armhf=12.2.0-14",
        "rc  oldconf:arm64=1.0-1"]
HOLDS = "libc6=2.36-9+deb12u10 libgcc-s1:armhf=12.2.0-14 tzdata=2025b-0+deb12u1"
QUERY = "dpkg-query -W -f=${db:Status-Abbrev} ${Package}:${Architecture}=${Version}\\n"
STUB = r"""#!/bin/sh
tool=${0##*/}
printf '%s\n' "$tool $*" >> "$STUB/log"
code() { cat "$STUB/rc.$1" 2>/dev/null || echo 0; }
case "$tool" in
dpkg) cat "$STUB/arch"; exit "$(code arch)" ;;
dpkg-query) key=before; test -e "$STUB/queried" && key=after; : > "$STUB/queried"; cat "$STUB/rows"
  exit "$(code "query.$key")" ;;
dpkg-deb) sed -n "s/^$3: //p" "$2"; exit "$(code deb)" ;;
esac
case " $* " in
*" update "*) exit 0 ;;
*" --simulate "*) cat "$STUB/sim"; exit "$(code sim)" ;;
*" --download-only "*) for arg; do case "$arg" in Dir::Cache::Archives=*) cp -RP "$STUB/fetch/." "${arg#*=}" ;; esac
  done; exit "$(code download)" ;;
*" --no-download "*) test "$(code install)" = 0 && cp "$STUB/installed" "$STUB/rows"; exit "$(code install)" ;;
esac
exit 99
"""


def _control(name: str, version: str, architecture: str = "arm64") -> bytes:
    return f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n".encode()


def _deb(name: str, version: str, architecture: str = "arm64") -> DebPackage:
    return DebPackage(name, version, architecture, hashlib.sha256(_control(name, version, architecture)).hexdigest())


def _file(package: DebPackage) -> str:
    return f"{package.name}_{package.version.replace(':', '%3a')}_{package.architecture}.deb"


PACKAGES = (_deb("libpq5", "18.4-1.pgdg120+1"), _deb("gcc", "4:12.2.0-3"),
            _deb("postgresql-client-common", "283.pgdg120+1", "all"))
PINS = "libpq5=18.4-1.pgdg120+1 gcc=4:12.2.0-3 postgresql-client-common=283.pgdg120+1"
ADDED = sorted(f"ii  {p.name}:{p.architecture}={p.version}" for p in PACKAGES)
LIBPQ5 = _file(PACKAGES[0])


class Shell:
    """A stubbed Debian host: ``stub/`` is test state, ``w`` the program's work directory."""

    def __init__(self, root: Path) -> None:
        assert all(TOOLS.values()), f"host tools missing (sha256sum must accept --check --strict): {TOOLS}"
        self.root, self.stub, self.bin, self.work = root, root / "stub", root / "bin", root / "w"
        self.bin.mkdir()
        self.stub.mkdir()
        for tool in ("dpkg", "dpkg-query", "apt-get", "dpkg-deb"):
            self.tool(tool, STUB)
        self.write({"arch": "arm64\n", "rows": BASE, "installed": [*BASE, *ADDED],
                    "sim": "Inst libpq5 (18.4-1.pgdg120+1 PGDG:bookworm-pgdg [arm64])\n"})
        for package in PACKAGES:
            self.fetch(_file(package), _control(package.name, package.version, package.architecture))

    def tool(self, name: str, text: str) -> None:
        (self.bin / name).write_text(text, encoding="utf-8")
        (self.bin / name).chmod(0o755)

    def write(self, files: Mapping[str, str | list[str]]) -> None:
        for name, value in files.items():
            (self.stub / name).write_text(value if isinstance(value, str) else "".join(f"{r}\n" for r in value))

    def fetch(self, name: str, data: bytes) -> Path:
        path = self.stub / "fetch" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run(self, packages: tuple[DebPackage, ...] = PACKAGES) -> tuple[int, list[str]]:
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", STUB=str(self.stub))
        done = subprocess.run([str(TOOLS["sh"]), "-c", apt_custody_program(packages, "arm64", str(self.work))],
                              env=env, capture_output=True, text=True, check=False)
        log = self.stub / "log"
        return done.returncode, log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def shell(tmp_path: Path) -> Shell:
    return Shell(tmp_path)


def _apt(mode: str) -> str:
    if mode == "--simulate":
        return f"apt-get install --simulate --no-install-recommends --no-remove {HOLDS} {PINS}"
    options = "--yes --no-install-recommends --no-remove -o Dir::Cache::Archives=W/cache/"
    return f"apt-get install {options} {mode} {HOLDS} {PINS}"


def test_positive_holds_every_row_and_admits_exactly_the_frozen_archives(shell: Shell) -> None:
    code, log = shell.run()
    assert code == 0 and [call.replace(str(shell.work), "W") for call in log] == [
        "dpkg --print-architecture", QUERY, "apt-get update", _apt("--simulate"), _apt("--download-only"),
        *(f"dpkg-deb --field W/cache/{_file(p)} {field}" for p in PACKAGES
          for field in ("Package", "Version", "Architecture")),
        _apt("--no-download"), QUERY,
    ], log
    assert (shell.stub / "rows").read_text().splitlines() == [*BASE, *ADDED] and not shell.work.exists()


def _failing(tool: str, target: str, *, whole: bool = False) -> Callable[[Shell], None]:
    """grep exits 2 after printing a count; cat exits 0 after a truncated read (``whole``: 1 after a complete one)."""
    read = f'{shlex.quote(str(TOOLS["cat"]))} "$1"; exit 1' if whole else 'sed -n 1p "$1"; exit 0'
    action = 'echo 0; exit 2' if tool == "grep" else read
    return lambda s: s.tool(tool, f'#!/bin/sh\nfor arg; do case "$arg" in */{target}) {action} ;; esac; done\n'
                                  f'exec {shlex.quote(str(TOOLS[tool]))} "$@"\n')


def _cache(kind: str) -> Callable[[Shell], None]:
    def change(s: Shell) -> None:
        archive = s.stub / "fetch" / LIBPQ5
        if kind == "unlisted":  # the simulation's extra package: caught only by exact membership
            s.fetch("libc-bin_2.36-9+deb12u11_arm64.deb", _control("libc-bin", "2.36-9+deb12u11"))
        elif kind == "duplicate":
            s.fetch("libpq5_18.4-1.pgdg120%2b1_arm64.deb", archive.read_bytes())
        elif kind == "missing":
            (s.stub / "fetch" / _file(PACKAGES[1])).unlink()
        elif kind == "symlink":
            (s.root / "elsewhere.deb").write_bytes(archive.read_bytes())
            archive.unlink()
            archive.symlink_to(s.root / "elsewhere.deb")
        elif kind == "flipped":
            archive.write_bytes(archive.read_bytes().replace(b"arm64", b"arm65"))
        else:
            s.fetch(f"partial/{LIBPQ5}", archive.read_bytes())
    return change


UPDATE, DOWNLOAD, INSTALL, Q, SIM = "apt-get update", "--download-only", "--no-download", "dpkg-query", "--simulate"
REFUSALS: dict[str, tuple[Mapping[str, str | list[str]] | Callable[[Shell], None], str, str]] = {
    "iiR": ({"rows": ["iiR libc6:arm64=2.36-9+deb12u10", *BASE[1:]]}, Q, UPDATE),
    "iU": ({"rows": ["iU  libc6:arm64=2.36-9+deb12u10", *BASE[1:]]}, Q, UPDATE),
    "empty-db": ({"rows": []}, Q, UPDATE),
    "bad-token": ({"rows": [*BASE, "ii  Bad_Name:arm64=1"]}, Q, UPDATE),
    "arch": ({"arch": "amd64\n"}, "dpkg --print-architecture", UPDATE),
    "arch-status": ({"rc.arch": "3"}, "dpkg --print-architecture", UPDATE),  # matching output, nonzero status
    "query-status": ({"rc.query.before": "1"}, Q, UPDATE),
    "added-ii": ({"rows": [*BASE, "ii  libpq5:arm64=17.6-1.pgdg120+1"]}, Q, UPDATE),
    "added-rc": ({"rows": [*BASE, "rc  gcc:arm64=4:12.2.0-2"]}, Q, UPDATE),  # B1: no rc-to-ii
    "added-foreign": ({"rows": [*BASE, "ii  libpq5:armhf=18.4-1.pgdg120+1"]}, Q, UPDATE),
    "grep-rows": (_failing("grep", "before"), Q, UPDATE),
    "grep-names": (_failing("grep", "names"), Q, UPDATE),
    # Q is only the last stubbed call; the holds refusals' locations are pinned by the work-directory test below.
    "cat-holds": (_failing("cat", "holds"), Q, UPDATE),  # truncated output, status 0: only the argv cmp refuses
    "cat-holds-status": (_failing("cat", "holds", whole=True), Q, UPDATE),  # matching output, status 1: holds=
    "sim-status": ({"rc.sim": "100"}, SIM, DOWNLOAD),
    "sim-remove": ({"sim": "Remv libgcc-s1:armhf [12.2.0-14]\n"}, SIM, DOWNLOAD),
    "sim-purge": ({"sim": "Purg oldconf:arm64 [1.0-1]\n"}, SIM, DOWNLOAD),
    "sim-upgrade": ({"sim": "Inst libc6 [2.36-9+deb12u10] (2.36-9+deb12u11 Debian [arm64])\n"}, SIM, DOWNLOAD),
    "grep-sim": (_failing("grep", "sim"), SIM, DOWNLOAD),
    **{f"cache-{kind}": (_cache(kind), DOWNLOAD, INSTALL)
       for kind in ("unlisted", "duplicate", "missing", "symlink", "flipped", "partial")},
    "deb-status": ({"rc.deb": "2"}, f"{LIBPQ5} Package", INSTALL),
}


@pytest.mark.parametrize("case", REFUSALS)
def test_each_refusal_stops_before_its_stage(shell: Shell, case: str) -> None:
    change, last, stage = REFUSALS[case]
    if callable(change):
        change(shell)
    else:
        shell.write(change)
    code, log = shell.run()
    assert code != 0 and log and last in log[-1] and not any(stage in call or INSTALL in call for call in log), log


@pytest.mark.parametrize(("whole", "argv"), [(False, ["libc6=2.36-9+deb12u10"]), (True, None)],
                         ids=["cat-holds", "cat-holds-status"])
def test_holds_refusal_stops_at_argv_cmp_or_assignment(shell: Shell, whole: bool, argv: list[str] | None) -> None:
    """Between the rows query and update only unstubbed steps run, so ``W/argv`` locates each refusal: written
    short and then refused by the cmp (the only step before update), or never written past a failed ``holds=``."""
    _failing("cat", "holds", whole=whole)(shell)
    code, log = shell.run()
    written = shell.work / "argv"
    assert code != 0 and log[-1] == QUERY and not any(UPDATE in call for call in log), log
    assert (written.read_text().splitlines() if written.exists() else None) == argv


@pytest.mark.parametrize("field", ["Package", "Version", "Architecture"])
def test_forged_control_field_refuses_before_install(shell: Shell, field: str) -> None:
    values = {"Package": "libpq5", "Version": "18.4-1.pgdg120+1", "Architecture": "arm64"}
    values[field] = {"Package": "libpq6", "Version": "18.9-1.pgdg120+1", "Architecture": "all"}[field]
    forged = shell.fetch(LIBPQ5, _control(values["Package"], values["Version"], values["Architecture"])).read_bytes()
    code, log = shell.run((PACKAGES[0]._replace(sha256=hashlib.sha256(forged).hexdigest()), *PACKAGES[1:]))
    assert code != 0 and log[-1].endswith(f"{LIBPQ5} {field}") and not any(INSTALL in c for c in log), log


def test_stale_work_directory_refuses_before_any_tool(shell: Shell) -> None:
    shell.work.mkdir()
    code, log = shell.run()
    assert code != 0 and log == [], log


def test_failed_no_remove_install_stops_with_rows_unchanged(shell: Shell) -> None:
    shell.write({"rc.install": "100"})
    code, log = shell.run()
    assert code != 0 and INSTALL in log[-1] and (shell.stub / "rows").read_text().splitlines() == BASE, log


@pytest.mark.parametrize("change", [
    {"installed": [BASE[0].replace("deb12u10", "deb12u11"), *BASE[1:], *ADDED]},  # changed held version
    {"installed": [*BASE[:2], BASE[3], *ADDED]},  # removed row: only comm -23 sees it
    {"installed": [*BASE, *ADDED, "ii  libc-bin:arm64=2.36-9+deb12u10"]},  # extra row
    {"rc.query.after": "1"},  # valid rows, nonzero status
])
def test_postcheck_refuses_changed_removed_or_extra_rows(shell: Shell, change: dict[str, str | list[str]]) -> None:
    shell.write(change)
    code, log = shell.run()
    assert code != 0 and INSTALL in log[-2] and log[-1] == QUERY and shell.work.exists(), log


ITEM = PlatformPackages(
    "sha256:" + "b" * 64, ("/etc/apt/sources.list.d/pgdg.list", "c" * 64),
    ("/usr/local/share/keyrings/postgres-archive-keyring.gpg", "d" * 64), ("B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8",),
    "/usr/lib/aarch64-linux-gnu/libpq.so.5.18", "e" * 64, "18.4-1.pgdg120+1",
    (PACKAGES[0], _deb("libpq-dev", "18.4-1.pgdg120+1"), PACKAGES[1]), (_deb("libgdbm6", "1.23-3"),), ("_dbm",))


def test_render_order_pipe_substitution_and_grep_groups() -> None:
    cleanup = " && rm -rf /var/lib/apt/lists/*"
    trust = (f"printf '%s\\n' '{'c' * 64}  /etc/apt/sources.list.d/pgdg.list' "
             f"'{'d' * 64}  /usr/local/share/keyrings/postgres-archive-keyring.gpg' | sha256sum -c - && ")
    builder = render_apt_steps("arm64", ITEM, ITEM.builder, trust_files=True)
    closure = render_apt_steps("arm64", ITEM, ITEM.closure, trust_files=False)
    assert builder == trust + apt_custody_program(ITEM.builder, "arm64") + cleanup
    assert closure == apt_custody_program(ITEM.closure, "arm64") + cleanup
    assert "apt-get" not in trust + cleanup and f"mkdir -m 0700 {APT_WORKDIR} " in closure
    assert render_apt_steps("arm64", ITEM, (), trust_files=True) == "true"
    assert builder.index("set -f") < builder.index("set +f") < builder.index(cleanup)
    tokens = list(shlex.shlex(builder, posix=True, punctuation_chars=True))
    assert tokens.count("|") == 1 and tokens.index("|") < tokens.index("export"), "only the trust check pipes"
    holds = (f"holds=$(cat {APT_WORKDIR}/holds) && set -f && set -- $holds && set +f && printf '%s\\n' \"$@\" > "
             f"{APT_WORKDIR}/argv && cmp {APT_WORKDIR}/holds {APT_WORKDIR}/argv && apt-get update && ")
    assert builder.count("$(") == 1 and holds in builder, "cat's status, then the argv cmp, precede update"
    greps = [index for index, token in enumerate(tokens) if token == "grep"]
    assert len(greps) == 3 and tokens.count("||") == 3, tokens
    for index in greps:  # each grep: no-match exit 1 passes; error exit 2 and any match refuse
        end = tokens.index("||", index)
        assert tokens[index - 1] == "{" and "&&" not in tokens[index:end], tokens[index:end]
        assert tokens[end + 1:end + 7] == ["test", "$?", "-eq", "1", ";", "}"], tokens[end:end + 7]
    assert "apt-get" not in render_server_dockerfile(), "the unfrozen manifest still refuses before APT"
