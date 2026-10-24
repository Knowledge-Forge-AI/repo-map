"""Immutable release image and packaged executable contract."""

import re
import shlex
from types import MappingProxyType
from typing import Iterable, Mapping, NamedTuple, Sequence

POSTGRES_RELEASE_VERSION = "16.15"
PYTHON_RELEASE_VERSION = "3.12.15"
GO_RELEASE_VERSION = "1.26.10"
PSYCOPG_RELEASE_VERSION = "3.3.6"
# ADR 0089 D1: the release base's observed system libpq, frozen by the
# non-consuming platform preflight and never guessed. None is unresolved; the
# rendered recipe then refuses before any package or backend execution.
PSYCOPG_LIBPQ_VERSION: int | None = None
# ADR 0089 D2: the incumbent bundled libpq 17.6 bounded cancel_safe(timeout=...);
# Psycopg 3.3.6 keeps that bound only with libpq >= 17, so the product requires it.
PRODUCT_MINIMUM_LIBPQ_VERSION = 170000
SETUPTOOLS_RELEASE_VERSION = "83.0.0"
WHEEL_RELEASE_VERSION = "0.48.0"
# wheel 0.48.0 declares Requires-Dist packaging>=24.0; 26.3 is the version
# already selected by the repository's hash-locked tooling (ADR 0089 D5).
PACKAGING_RELEASE_VERSION = "26.3"
# Build-only distributions removed before the final image (pip is the base's).
RELEASE_BUILD_ONLY_MODULES = ("pip", "setuptools", "wheel", "packaging")
TYPING_EXTENSIONS_RELEASE_VERSION = "4.16.0"

POSTGRES_RELEASE_IMAGE = (
    "postgres:16.15-trixie@sha256:"
    "9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97"
)
PYTHON_RELEASE_IMAGE = (
    "python:3.12-slim-trixie@sha256:"
    "a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"
)
GO_RELEASE_IMAGE = (
    "golang:1.26.10-bookworm@sha256:"
    "632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af"
)

PACKAGED_PSQL = "/usr/lib/postgresql/16/bin/psql"
PACKAGED_PG_DUMP = "/usr/bin/pg_dump"
PACKAGED_PG_RESTORE = "/usr/bin/pg_restore"

# ADR 0089 D5: the one approved psycopg-c source archive, fetched as an opaque
# file and inspected before any backend execution. Member hashes equal the
# files at the tagged commit; generated C is attributed to this archive only.
PSYCOPG_C_SDIST_URL = (
    "https://files.pythonhosted.org/packages/58/53/"
    "bf15aa48cd6f0ad0039b9f48681d2e76e8564d413af47b13fab50dd03555/psycopg_c-3.3.6.tar.gz"
)
PSYCOPG_C_SDIST_SIZE = 698245
PSYCOPG_C_SDIST_SHA256 = "29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8"
PSYCOPG_TAG_COMMIT = "a67654d1e7afbf9b3a619557838f62de1c790e7c"
PSYCOPG_C_SDIST_MEMBERS = MappingProxyType({
    "LICENSE.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
    "build_backend/cython_backend.py": "2095daa2ef79405fde2c9e2e41d826e9578290b54497c0a84361c1db28008c85",
    "build_backend/psycopg_build_ext.py": "f8f3787b38dbbd80b9b69113c3430e062f9a471be58d3e3266e65a217f9ed2ed",
    "pyproject.toml": "0bc22cfca0a5cb84d25b172a7141df255345f18d6ca79e3db656106d2714a09c",
})
PSYCOPG_C_GENERATED_SOURCES = ("psycopg_c/_psycopg.c", "psycopg_c/pq.c", "psycopg_c/types/numutils.c")
# Hash sets equal tools/ci/psycopg_build.lock and project_dependencies.lock.
RELEASE_WHEEL_REQUIREMENTS = MappingProxyType({
    f"packaging=={PACKAGING_RELEASE_VERSION}": (
        "94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79",
        "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c",
    ),
    f"psycopg=={PSYCOPG_RELEASE_VERSION}": (
        "a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631",
        "c081f2250df751a943036e42db6df4571c66cd0aabe8291a7a506512b12007d2",
    ),
    f"setuptools=={SETUPTOOLS_RELEASE_VERSION}": (
        "025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef",
        "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3",
    ),
    f"typing-extensions=={TYPING_EXTENSIONS_RELEASE_VERSION}": (
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
        "dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5",
    ),
    f"wheel=={WHEEL_RELEASE_VERSION}": (
        "3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab",
        "94800765601e9171bf5d58d066e640662842bcedcbab982b2c90787a2c987322",
    ),
})


class DebPackage(NamedTuple):
    """One Debian package pinned from a signed index (ADR 0089 D3)."""
    name: str
    version: str
    architecture: str
    sha256: str


class PlatformPackages(NamedTuple):
    """Preflight-observed, frozen package and libpq identity for one platform."""

    postgres_config_digest: str
    pgdg_source: tuple[str, str]
    pgdg_keyring: tuple[str, str]
    key_fingerprints: tuple[str, ...]
    libpq_path: str
    libpq_sha256: str
    libpq5_version: str
    builder: tuple[DebPackage, ...]
    closure: tuple[DebPackage, ...]
    lib_dynload: tuple[str, ...]


# ADR 0089 D3: keyed by Docker TARGETARCH. Empty until the platform preflight
# observes both bases and resolves every package from the signed indices.
DYNAMIC_PACKAGE_MANIFEST: Mapping[str, PlatformPackages] = MappingProxyType({})
APT_WORKDIR = "/tmp/repomap-apt"  # M2: root-only private rows and archive cache, removed on success
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TRUST_PATH = re.compile(r"/(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+")
_DEB_NAME, _DEB_VERSION = re.compile(r"[a-z0-9][a-z0-9+.-]+"), re.compile(r"[0-9][A-Za-z0-9.+:~-]*")


def validate_package_manifest(manifest: Mapping[str, PlatformPackages], libpq_version: int | None) -> None:
    """Refuse a frozen manifest whose identities are incomplete, unsafe to render or inconsistent (D3)."""
    if not manifest:
        return
    if set(manifest) - {"amd64", "arm64"} or libpq_version is None:
        raise ValueError("frozen package manifest platforms or libpq version are invalid")
    if libpq_version < PRODUCT_MINIMUM_LIBPQ_VERSION:
        raise ValueError("product libpq lacks bounded cancel_safe; libpq >= 17 is required")
    first = next(iter(manifest.values()))
    for architecture, item in manifest.items():
        trust = (item.pgdg_source, item.pgdg_keyring)
        if (item.pgdg_source[0], item.pgdg_keyring[0]) != (first.pgdg_source[0], first.pgdg_keyring[0]):
            raise ValueError("frozen package manifest trust paths differ by platform")
        if any(not _TRUST_PATH.fullmatch(path) or "/../" in f"{path}/" or not _HEX64.fullmatch(digest)
               for path, digest in trust):
            raise ValueError("frozen package manifest trust file identity is unsafe or incomplete")
        if not item.key_fingerprints or not all(re.fullmatch(r"[0-9A-F]{40}", key) for key in item.key_fingerprints):
            raise ValueError("frozen package manifest signing-key fingerprints are invalid")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", item.postgres_config_digest) or not _HEX64.fullmatch(
                item.libpq_sha256) or not re.fullmatch(r"/usr/lib/[a-z0-9_-]+/libpq\.so\.5(?:\.\d+)+", item.libpq_path):
            raise ValueError("frozen package manifest base or libpq file identity is invalid")
        if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module) for module in item.lib_dynload):
            raise ValueError("frozen package manifest lib-dynload module names are invalid")
        versions = {p.name: p.version for p in item.builder}
        if not item.libpq5_version or versions.get("libpq5") != item.libpq5_version or versions.get(
                "libpq-dev") != item.libpq5_version:
            raise ValueError("frozen builder libpq-dev and libpq5 differ from the runtime libpq5 version")
        for package in (*item.builder, *item.closure):
            if (not _DEB_NAME.fullmatch(package.name) or not _DEB_VERSION.fullmatch(package.version)
                    or package.architecture not in (architecture, "all") or not _HEX64.fullmatch(package.sha256)):
                raise ValueError(f"frozen package {package.name} identity is incomplete")
        # M2: checked last, so every earlier refusal keeps its own message.
        for packages in (item.builder, item.closure):
            for values in ([p.name for p in packages], [p.sha256 for p in packages], [_deb_file(p) for p in packages]):
                if len(set(values)) != len(values):
                    raise ValueError("frozen package manifest repeats a package name, SHA-256 or file")


def _deb_file(package: DebPackage) -> str:
    return f"{package.name}_{package.version.replace(':', '%3a')}_{package.architecture}.deb"


def _lines(values: Iterable[str]) -> str:
    return "printf '%s\\n' " + " ".join(shlex.quote(value) for value in values)


def _none_found(search: str, found: str) -> str:
    """grep's no-match exit 1 passes; its error exit 2 and any match refuse."""
    return f'{{ {search} > {found} || test "$?" -eq 1; }} && test ! -s {found}'


# ADR 0089 M2: a whole dpkg row, built from the validator's own name and version expressions.
_DPKG_ROW = f"(ii|rc)  {_DEB_NAME.pattern}:[a-z0-9]+={_DEB_VERSION.pattern}"
_DPKG_ROWS = "dpkg-query -W -f='${db:Status-Abbrev} ${Package}:${Architecture}=${Version}\\n'"


def apt_custody_program(packages: Sequence[DebPackage], arch: str, workdir: str = APT_WORKDIR) -> str:
    """ADR 0089 M2: install exactly ``packages`` with every installed row held, as one ``&&`` chain."""
    w, files = workdir, {p: f"{workdir}/cache/{_deb_file(p)}" for p in packages}
    pins = " ".join(shlex.quote(f"{p.name}={p.version}") for p in packages)
    apt = f"apt-get install --yes --no-install-recommends --no-remove -o Dir::Cache::Archives={w}/cache/"
    controls = [f"dpkg-deb --field {files[p]} {field} > {w}/ctl && {_lines([value])} > {w}/ctl.want && "
                f"cmp {w}/ctl.want {w}/ctl" for p in packages
                for field, value in (("Package", p.name), ("Version", p.version), ("Architecture", p.architecture))]
    return " && ".join([
        "export LC_ALL=C", f"mkdir -m 0700 {w} {w}/cache {w}/cache/partial",
        f"dpkg --print-architecture > {w}/arch", f"{_lines([arch])} > {w}/arch.want", f"cmp {w}/arch.want {w}/arch",
        f"{_DPKG_ROWS} > {w}/rows", f"sort -o {w}/before {w}/rows", f"test -s {w}/before",
        _none_found(f"grep -Evx {shlex.quote(_DPKG_ROW)} {w}/before", f"{w}/badrows"),
        f"sed -n 's/^ii  //p' {w}/before > {w}/inst",
        f"sed -e 's/^\\([^:]*\\):{arch}=/\\1=/' -e 's/^\\([^:]*\\):all=/\\1=/' {w}/inst > {w}/holds",
        f"test -s {w}/holds",
        # Names from every row, ii and rc, of every architecture: no implicit rc-to-ii transition.
        f"sed -e 's/^..  //' -e 's/:.*//' {w}/before > {w}/names", f"sort -u -o {w}/names {w}/names",
        f"{_lines(sorted(p.name for p in packages))} > {w}/add",
        _none_found(f"grep -Fx -f {w}/add {w}/names", f"{w}/present"),
        # I7 erratum: the assignment carries cat's exit status, which `set -- $(cat …)` would hide.
        f"holds=$(cat {w}/holds)", "set -f", "set -- $holds", "set +f",
        f"printf '%s\\n' \"$@\" > {w}/argv", f"cmp {w}/holds {w}/argv",
        "apt-get update",
        f'apt-get install --simulate --no-install-recommends --no-remove "$@" {pins} > {w}/sim',
        _none_found(f"grep -E '^(Remv|Purg) |^Inst [^ ]+ \\[' {w}/sim", f"{w}/simbad"),
        f'{apt} --download-only "$@" {pins}',
        f"find {w}/cache -mindepth 1 ! -path {w}/cache/lock ! -path {w}/cache/partial > {w}/ls",
        f"sort -o {w}/ls {w}/ls", f"{_lines(sorted(files.values()))} > {w}/want", f"cmp {w}/want {w}/ls",
        f"find {w}/cache -mindepth 1 ! -path {w}/cache/partial ! -type f > {w}/odd", f"test ! -s {w}/odd",
        f"{_lines(f'{p.sha256}  {files[p]}' for p in packages)} > {w}/sums",
        f"sha256sum --check --strict --quiet {w}/sums",
        *controls,
        f'{apt} --no-download "$@" {pins}',
        f"{_DPKG_ROWS} > {w}/rows2", f"sort -o {w}/after {w}/rows2",
        f"comm -23 {w}/before {w}/after > {w}/lost", f"test ! -s {w}/lost", f"comm -13 {w}/before {w}/after > {w}/new",
        f"{_lines(sorted(f'ii  {p.name}:{p.architecture}={p.version}' for p in packages))} > {w}/exp",
        f"cmp {w}/exp {w}/new", f"rm -rf {w}",
    ])


def render_apt_steps(arch: str, item: PlatformPackages, packages: Sequence[DebPackage], *, trust_files: bool) -> str:
    """The builder's unchanged trust check, then custody, then list cleanup; no packages render ``true``."""
    if not packages:
        return "true"
    trust = _lines(f"{digest}  {path}" for path, digest in (item.pgdg_source, item.pgdg_keyring))
    return ((f"{trust} | sha256sum -c - && " if trust_files else "")
            + apt_custody_program(packages, arch) + " && rm -rf /var/lib/apt/lists/*")


# ADR 0089 in-build verification programs (stdlib only), run with ``python -I -c``.
# D5: inspect the opaque archive before any backend execution. argv: archive,
# then a JSON object of size, sha256, version, member hashes and generated C.
RELEASE_SDIST_INSPECTION_PY = """\
import hashlib, io, json, sys, tarfile
path, expected = sys.argv[1], json.loads(sys.argv[2])
data = open(path, "rb").read()
assert len(data) == expected["size"] and hashlib.sha256(data).hexdigest() == expected["sha256"], "archive identity"
root = f"psycopg_c-{expected['version']}/"
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    members = archive.getmembers()
    for member in members:
        assert member.isfile() or member.isdir(), f"link or special member {member.name}"
        inside = member.name == root.rstrip("/") or member.name.startswith(root)
        assert inside and ".." not in member.name.split("/"), member.name
    files = {m.name.removeprefix(root): archive.extractfile(m).read() for m in members if m.isfile()}
info = files["PKG-INFO"].decode()
assert f"\\nVersion: {expected['version']}\\n" in info and "\\nLicense-Expression: LGPL-3.0-only\\n" in info
assert "Requires-Dist:" not in info, "unlisted requirement"
assert not [name for name in files if name.endswith(".pyx")], "Cython sources would request Cython"
for name, digest in expected["members"].items():
    assert hashlib.sha256(files[name]).hexdigest() == digest, name
for name in expected["generated"]:
    assert files.get(name), f"generated C missing: {name}"
print(json.dumps({"members": len(members), "files": len(files)}))
"""
# D2.1: list every ELF in the installed psycopg-c RECORD with readelf; refuse a
# libpq import without DT_NEEDED libpq.so.5 or a locally defined libpq export.
# libpq symbols are those the system libpq.so.5 exports: psycopg-c's own
# PostgreSQL-derived pg_lltoa/pg_ulltoa_n match the pg_ prefix but are not libpq.
RELEASE_BUILD_LINKAGE_PY = """\
import importlib.metadata as md, json, os, re, subprocess
def symbols(path):
    table = subprocess.run(["readelf", "--dyn-syms", "-W", path], check=True, capture_output=True, text=True).stdout
    rows = [line.split() for line in table.splitlines() if re.match(r"\\s*\\d+:", line)]
    return [(row[6], row[7].split("@")[0]) for row in rows if len(row) >= 8]
libdir = subprocess.run(["pg_config", "--libdir"], check=True, capture_output=True, text=True).stdout.strip()
exports = {name for index, name in symbols(os.path.realpath(f"{libdir}/libpq.so.5")) if index != "UND"}
records, referencing = [], 0
distribution = md.distribution("psycopg-c")
for item in distribution.files or ():
    path = str(distribution.locate_file(item))
    with open(path, "rb") as stream:
        if stream.read(4) != b"\\x7fELF":
            continue
    dynamic = subprocess.run(["readelf", "-d", "-W", path], check=True, capture_output=True, text=True).stdout
    needed = re.findall(r"\\(NEEDED\\)\\s+Shared library: \\[([^]]+)\\]", dynamic)
    named = symbols(path)
    undefined = sorted({name for index, name in named if index == "UND" and name in exports})
    defined = sorted({name for index, name in named if index != "UND" and name in exports})
    assert not defined, f"{path} defines libpq symbols {defined}"
    if undefined:
        referencing += 1
        assert "libpq.so.5" in needed, f"{path} lacks DT_NEEDED libpq.so.5"
    records.append({"path": path, "needed": needed, "libpq_undefined": undefined})
assert referencing, "no psycopg-c ELF references libpq"
print(json.dumps({"libpq_exports": len(exports), "extensions": records}, indent=1, sort_keys=True))
"""
# Fail-closed helpers of the final probe (ADR 0089 D2, M1). ``run`` accepts only
# the documented exit codes, and stderr only with a documented non-zero outcome
# (dpkg-query -S "no path found", dpkg --verify problems). ``dynamic`` reads the
# ELF program headers without executing the file, so a static ELF such as the Go
# helper is never handed to ldd, while every dynamic ELF needs ldd success.
# ``LIBRARY_FILE`` names shared or static libraries, never Cython's libpq.pxd.
RELEASE_PROBE_HELPERS_PY = """\
import fnmatch, glob, re, struct, subprocess
LIBRARY_FILE = re.compile(r"libpq[^/]*\\.(?:so(?:\\.\\d+)*|a|dylib)\\Z")
def run(*command, codes=(0,)):
    done = subprocess.run(list(command), capture_output=True, text=True, check=False)
    if done.returncode not in codes or (done.returncode == 0 and done.stderr.strip()):
        raise SystemExit(f"{command[0]} exited {done.returncode}: {done.stderr.strip()[:400]}")
    return done.returncode, done.stdout.strip()
def owner(path):
    for candidate in (path, "/" + path.removeprefix("/usr/")):
        code, text = run("dpkg-query", "-S", candidate, codes=(0, 1))
        if code == 0 and text:
            return text.split(":", 1)[0]
    return ""
def dynamic(path):
    data = open(path, "rb").read()
    wide, order = data[4] == 2, "<" if data[5] == 1 else ">"
    offset = struct.unpack_from(order + ("Q" if wide else "I"), data, 0x20 if wide else 0x1C)[0]
    size, count = struct.unpack_from(order + "HH", data, 0x36 if wide else 0x2A)
    return any(struct.unpack_from(order + "I", data, offset + index * size)[0] == 2 for index in range(count))
def filtered(line, rules):
    excluded = False
    for kind, pattern in rules if line.split()[:1] == ["missing"] else ():
        excluded = kind == "path-exclude" if fnmatch.fnmatchcase(line.split()[-1], pattern) else excluded
    return excluded
def dpkg_rules(root="/etc/dpkg/dpkg.cfg.d"):
    return [line.split() for config in sorted(glob.glob(root + "/*")) for line in open(config)
            if len(line.split()) == 2 and line.split()[0] in ("path-exclude", "path-include")]
"""
# D2.2-D2.3 and D4 final assertions. Expected identities come from the frozen
# manifest through REPOMAP_EXPECT_* environment values set per platform.
RELEASE_FINAL_PROBE_PY = RELEASE_PROBE_HELPERS_PY + """\
import hashlib, importlib.metadata as md, importlib.util as iu, json, os, pathlib, sys
os.environ.pop("PSYCOPG_IMPL", None)
import psycopg
from psycopg import pq
expect = {k.removeprefix("REPOMAP_EXPECT_").lower(): v for k, v in os.environ.items()\
 if k.startswith("REPOMAP_EXPECT_")}
assert pq.__impl__ == "c" and pq.version() == pq.__build_version__ == int(expect["libpq_version"])
# The incumbent bounded cancel_safe(timeout=...); Psycopg 3.3.6 keeps that bound only with libpq >= 17.
assert pq.version() >= int(expect["minimum_libpq"]) and psycopg.capabilities.has_cancel_safe(), "bounded cancel_safe"
assert iu.find_spec("psycopg_binary") is None and "psycopg-binary" not in {d.metadata\
["Name"].lower() for d in md.distributions()}
maps = sorted({line.split()[-1] for line in open("/proc/self/maps") if "libpq" in line and "/" in line})
assert len(maps) == 1, maps
real = os.path.realpath(maps[0])
assert real == expect["libpq_path"] and hashlib.sha256(open(real, "rb").read()).hexdigest() == expect["libpq_sha256"]
assert owner(real) == "libpq5", real
assert run("dpkg-query", "-W", "-f=${Version}", "libpq5")[1] == expect["libpq5_version"]
# The slim base's dpkg path-exclude filters never install docs and locales; only those may be missing.
code, verify = run("dpkg", "--verify", "libpq5", codes=(0, 1))
problems = [line for line in verify.splitlines() if not filtered(line, dpkg_rules()) or real in line]
assert not problems and (code == 0 or verify), (code, problems)
local = [p for p in pathlib.Path("/usr/local").rglob("*") if p.is_file() and not p.is_symlink()]
assert not [p for p in local if LIBRARY_FILE.search(p.name)], "private libpq under /usr/local"
elves = [p for p in local if p.open("rb").read(4) == b"\\x7fELF"]
for path in (p for p in elves if dynamic(str(p))):
    linked = run("ldd", str(path))[1]
    assert "not found" not in linked, f"{path}: {linked}"
    for target in (line.split("=>")[1].split()[0] for line in linked.splitlines() if "=> /" in line):
        assert target.startswith("/usr/local/") or owner(os.path.realpath(target)), target
modules = ["psycopg_c._psycopg", "psycopg_c.pq", *json.loads(expect["lib_dynload"])]
os.environ["LD_BIND_NOW"] = "1"  # the fresh child initializes psycopg before loading its C modules eagerly
run(sys.executable, "-I", "-c", "import psycopg, importlib, sys; [importlib.import_mo\
dule(m) for m in sys.argv[1:]]", *modules)
rows = [line.split("\\t") for line in run("dpkg-query", "-W", "-f=${Package}\\t${db:Status-Abbrev}\\n")[1].splitlines()]
assert rows and all(len(row) == 2 and row[1][:2] in ("ii", "rc") for row in rows), "package database state"
packages = [name for name, state in rows if state.startswith("ii")]
assert not [p for p in packages if p.endswith("-dev") or p in {"gcc", "binutils", "cp\
p"} or p.startswith("gcc-")], packages
build_only = json.loads(expect["build_only_modules"])
assert not [m for m in build_only if iu.find_spec(m)] and not os.path.exists("/usr/local/include")
print(json.dumps({"implementation": pq.__impl__, "libpq": pq.version(), "loaded": real, "elf_checked": len(elves),
                  "has_cancel_safe": psycopg.capabilities.has_cancel_safe()}))
"""


__all__ = [
    "APT_WORKDIR",
    "DYNAMIC_PACKAGE_MANIFEST",
    "DebPackage",
    "GO_RELEASE_IMAGE", "GO_RELEASE_VERSION", "PACKAGED_PG_DUMP",
    "PACKAGED_PG_RESTORE",
    "PACKAGED_PSQL",
    "PACKAGING_RELEASE_VERSION",
    "POSTGRES_RELEASE_IMAGE",
    "POSTGRES_RELEASE_VERSION",
    "PRODUCT_MINIMUM_LIBPQ_VERSION",
    "PSYCOPG_C_GENERATED_SOURCES",
    "PSYCOPG_C_SDIST_MEMBERS",
    "PSYCOPG_C_SDIST_SHA256",
    "PSYCOPG_C_SDIST_SIZE",
    "PSYCOPG_C_SDIST_URL",
    "PSYCOPG_LIBPQ_VERSION",
    "PSYCOPG_RELEASE_VERSION",
    "PSYCOPG_TAG_COMMIT",
    "PYTHON_RELEASE_IMAGE",
    "PYTHON_RELEASE_VERSION",
    "PlatformPackages",
    "RELEASE_BUILD_LINKAGE_PY",
    "RELEASE_BUILD_ONLY_MODULES",
    "RELEASE_FINAL_PROBE_PY",
    "RELEASE_PROBE_HELPERS_PY",
    "RELEASE_SDIST_INSPECTION_PY",
    "RELEASE_WHEEL_REQUIREMENTS",
    "SETUPTOOLS_RELEASE_VERSION",
    "TYPING_EXTENSIONS_RELEASE_VERSION",
    "WHEEL_RELEASE_VERSION",
    "apt_custody_program",
    "render_apt_steps",
    "validate_package_manifest",
]
