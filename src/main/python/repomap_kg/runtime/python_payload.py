"""ADR 0089 D4 exact Python payload contract (stdlib only; ``python -I -B``), shared by the recipe and E1.

Record the raw /usr/local baseline, classify it against the frozen native entry, unlink exactly that one file and
re-prove the rest. It cannot prove the OCI config; the pinned FROM and the host's external resolution bind that.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Any, Callable, Mapping, NamedTuple, Sequence

SCHEMA, ROOT, DYNLOAD = "repomap-python-payload-v1", "/usr/local", "/usr/local/lib/python3.12/lib-dynload"
NATIVE: Mapping[str, str] = MappingProxyType({"aarch64": "arm64", "x86_64": "amd64"})
# ldd lines naming no missing object; any other non-blank line is an unresolved finding.
LDD_RESOLVED = re.compile(r"(?:\S+ => )?/\S+ \(0x[0-9a-f]+\)|linux-vdso\.so\.\d+ \(0x[0-9a-f]+\)|statically linked|"
                          r"not a dynamic executable|ldd: warning: you do not have execution permission for .*")
LDD_TARGET = re.compile(r"(?:=> |^\s*)(/\S+) \(0x", re.M)
_DIGEST, _HEX64 = re.compile(r"sha256:[0-9a-f]{64}"), re.compile(r"[0-9a-f]{64}")
_MODULE, _LIBRARY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*"), re.compile(r"lib[A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*")
_TARGET = re.compile(
    r"/usr/local/lib/python3\.12/lib-dynload/([A-Za-z_][A-Za-z0-9_]*)\.cpython-312-[a-z0-9_]+-linux-gnu\.so")
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class PayloadRefusal(ValueError):
    pass


class PayloadExclusion(NamedTuple):
    architecture: str
    python_index: str
    platform_manifest: str
    python_config: str
    path: str
    sha256: str
    size: int
    elf_machine: int
    module: str
    missing: tuple[str, ...]
    baseline_imports: tuple[str, ...]


# The 77 lib-dynload modules that imported in the Trixie 3.12.15 baseline's fresh LD_BIND_NOW=1 processes
# (ADR 0091; the historical Bookworm 3.12.13 E1 set of 78 also had nis, which this base no longer ships).
ARM64_BASELINE_IMPORTS = (
    "_asyncio", "_bisect", "_blake2", "_bz2", "_codecs_cn", "_codecs_hk", "_codecs_iso2022", "_codecs_jp",
    "_codecs_kr", "_codecs_tw", "_contextvars", "_crypt", "_csv", "_ctypes", "_ctypes_test", "_curses",
    "_curses_panel", "_datetime", "_dbm", "_decimal", "_elementtree", "_gdbm", "_hashlib", "_heapq", "_json",
    "_lsprof", "_lzma", "_md5", "_multibytecodec", "_multiprocessing", "_opcode", "_pickle", "_posixshmem",
    "_posixsubprocess", "_queue", "_random", "_sha1", "_sha2", "_sha3", "_socket", "_sqlite3", "_ssl",
    "_statistics", "_struct", "_testbuffer", "_testcapi", "_testclinic", "_testimportmultiple",
    "_testinternalcapi", "_testmultiphase", "_testsinglephase", "_uuid", "_xxinterpchannels",
    "_xxsubinterpreters", "_xxtestfuzz", "_zoneinfo", "array", "audioop", "binascii", "cmath", "fcntl", "grp",
    "math", "mmap", "ossaudiodev", "pyexpat", "readline", "resource", "select", "spwd", "syslog",
    "termios", "unicodedata", "xxlimited", "xxlimited_35", "xxsubtype", "zlib",
)
# The 77 lib-dynload modules independently observed in the native x86_64 Trixie 3.12.15 baseline (ADR 0094).
AMD64_BASELINE_IMPORTS = (
    "_asyncio", "_bisect", "_blake2", "_bz2", "_codecs_cn", "_codecs_hk", "_codecs_iso2022", "_codecs_jp",
    "_codecs_kr", "_codecs_tw", "_contextvars", "_crypt", "_csv", "_ctypes", "_ctypes_test", "_curses",
    "_curses_panel", "_datetime", "_dbm", "_decimal", "_elementtree", "_gdbm", "_hashlib", "_heapq", "_json",
    "_lsprof", "_lzma", "_md5", "_multibytecodec", "_multiprocessing", "_opcode", "_pickle", "_posixshmem",
    "_posixsubprocess", "_queue", "_random", "_sha1", "_sha2", "_sha3", "_socket", "_sqlite3", "_ssl",
    "_statistics", "_struct", "_testbuffer", "_testcapi", "_testclinic", "_testimportmultiple",
    "_testinternalcapi", "_testmultiphase", "_testsinglephase", "_uuid", "_xxinterpchannels",
    "_xxsubinterpreters", "_xxtestfuzz", "_zoneinfo", "array", "audioop", "binascii", "cmath", "fcntl", "grp",
    "math", "mmap", "ossaudiodev", "pyexpat", "readline", "resource", "select", "spwd", "syslog",
    "termios", "unicodedata", "xxlimited", "xxlimited_35", "xxsubtype", "zlib",
)
# OCI identities of the pinned Trixie index's arm64 and amd64 children (ADR 0091, ADR 0094).
PYTHON_PAYLOAD_EXCLUSIONS: Mapping[str, PayloadExclusion] = MappingProxyType({
    "arm64": PayloadExclusion(
        "arm64", "sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        "sha256:6c6ae3622772575c3ac02ecb2b02a06d05f19e1713a0cbff476ef37bca79e90f",
        "sha256:7efd45553a98be3d940b73600550669831c0be34f30c521159e7030a91fcdee6",
        f"{DYNLOAD}/_tkinter.cpython-312-aarch64-linux-gnu.so",
        "9fe4f2c93a746b000a15ebb6fbb71ea33b3b7888efb70e3c1296fac8b30c2c96", 70584, 183,  # EM_AARCH64
        "_tkinter", ("libtcl8.6.so", "libtk8.6.so"), ARM64_BASELINE_IMPORTS),
    "amd64": PayloadExclusion(
        "amd64", "sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        "sha256:e8a38829209aea82774882e5157e1f7c3e8c8393ff53a697b3580896e57f345c",
        "sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1",
        f"{DYNLOAD}/_tkinter.cpython-312-x86_64-linux-gnu.so",
        "4505ea29e626d11865106c975d7bed84d472bc6a4c0f2aedd670c6a3ecf233a8", 62448, 62,  # EM_X86_64
        "_tkinter", ("libtcl8.6.so", "libtk8.6.so"), AMD64_BASELINE_IMPORTS),
})


def validate_exclusion(entry: PayloadExclusion, architecture: str) -> None:
    match, names = _TARGET.fullmatch(entry.path), entry.baseline_imports
    if (entry.architecture != architecture or architecture not in NATIVE.values()
            or not all(_DIGEST.fullmatch(d) for d in (entry.python_index, entry.platform_manifest, entry.python_config))
            or not _HEX64.fullmatch(entry.sha256) or match is None or match.group(1) != entry.module
            or type(entry.size) is not int or entry.size <= 0 or type(entry.elf_machine) is not int
            or entry.elf_machine <= 0 or not entry.missing or list(entry.missing) != sorted(set(entry.missing))
            or not all(_LIBRARY.fullmatch(library) for library in entry.missing) or not names
            or list(names) != sorted(set(names)) or not all(map(_MODULE.fullmatch, names)) or entry.module in names):
        raise PayloadRefusal(f"payload exclusion entry for {architecture!r} is not exact")


def _digest(entries: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _logical(mount: Path, path: Path) -> str:
    real, base = os.path.realpath(path), os.path.realpath(mount)
    return "/" + os.path.relpath(real, base) if real.startswith(base.rstrip("/") + "/") else f"outside:{real}"


def _walk(mount: Path) -> tuple[dict[str, list[Any]], dict[str, bytes]]:
    """Every /usr/local entry, links not followed: kind, SHA-256 or link target, size, mode; and ELF heads."""
    entries: dict[str, list[Any]] = {}
    heads: dict[str, bytes] = {}
    for directory, dirs, files in os.walk(mount / ROOT.lstrip("/")):
        for name in (*dirs, *files):
            real = Path(directory, name)
            info, logical = os.lstat(real), "/" + real.relative_to(mount).as_posix()
            if stat.S_ISREG(info.st_mode):
                data = real.read_bytes()
                entries[logical] = ["file", hashlib.sha256(data).hexdigest(), len(data), info.st_mode]
                if data[:4] == b"\x7fELF":
                    heads[logical] = data[:20]
            elif stat.S_ISLNK(info.st_mode):
                entries[logical] = ["symlink", os.readlink(real), 0, info.st_mode]
            else:
                entries[logical] = ["dir" if stat.S_ISDIR(info.st_mode) else "other", "", 0, info.st_mode]
    return entries, heads


def observe(run: Runner, mount: Path, executable: str, machine: str) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    entries, heads = _walk(mount)
    elves: dict[str, dict[str, Any]] = {}
    for path, head in sorted(heads.items()):
        done = run(["ldd", str(mount / path.lstrip("/"))], capture_output=True, text=True, check=False)
        machine_bytes = int.from_bytes(head[18:20], "little" if head[5:6] == b"\x01" else "big")
        elves[path] = {"sha256": entries[path][1], "size": entries[path][2], "ldd_exit": done.returncode,
                       "elf": [head[4], head[5], machine_bytes] if len(head) == 20 else [],
                       "ldd": (done.stdout or "") + (done.stderr or "")}
    dynload = sorted([path.rsplit("/", 1)[1], value[0]] for path, value in entries.items()
                     if path.rsplit("/", 1)[0] == DYNLOAD and path.endswith(".so"))
    imports: list[str] = []
    failed: dict[str, dict[str, Any]] = {}
    for module in sorted({name.split(".", 1)[0] for name, _kind in dynload}):
        if not _MODULE.fullmatch(module):
            failed[module] = {"exit": None, "error": "not an importable module name"}
            continue
        done = run([executable, "-I", "-B", "-c", f"import {module}"], env={**os.environ, "LD_BIND_NOW": "1"},
                   capture_output=True, text=True, check=False)
        if done.returncode == 0:
            imports.append(module)
        else:
            error = ((done.stderr or "").strip().splitlines() or [""])[-1]
            failed[module] = {"exit": done.returncode, "error": error[:400]}
    targets = {target: [
        _logical(mount, file), hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None]
               for target in sorted({t for elf in elves.values() for t in LDD_TARGET.findall(elf["ldd"])})
               for file in [mount / target.lstrip("/")]}
    return entries, {"machine": machine, "entries": len(entries), "digest": _digest(entries), "elves": elves,
                     "dynload": dynload, "dynload_real": _logical(mount, mount / DYNLOAD.lstrip("/")),
                     "imports": imports, "failed": failed, "targets": targets}


def unresolved(elves: Mapping[str, Mapping[str, Any]]) -> list[str]:
    found: list[str] = []
    for path, elf in sorted(elves.items()):
        lines = [line.strip() for line in str(elf["ldd"]).splitlines() if line.strip()]
        found.extend(f"{path}: {line}" for line in lines if not LDD_RESOLVED.fullmatch(line))
        found.extend([] if lines else [f"{path}: malformed empty ldd output"])
    return found


def lib_dynload_modules(observed: Mapping[str, Any]) -> list[str]:
    return sorted({str(name).split(".", 1)[0] for name, _kind in observed["dynload"]})


def classify(baseline: Mapping[str, Any], entry: PayloadExclusion | None) -> dict[str, Any] | None:
    """Exactly the frozen entry is excluded, or nothing may be broken."""
    lost, modules, imports = unresolved(baseline["elves"]), lib_dynload_modules(baseline), list(baseline["imports"])
    failed = sorted(set(modules) - set(imports))
    if set(imports) - set(modules) or sorted(baseline["failed"]) != failed or imports != sorted(imports):
        raise PayloadRefusal("malformed observation: import results do not match the lib-dynload names")
    if any(real is None for real, _digest in baseline["targets"].values()):
        raise PayloadRefusal("malformed observation: an ldd-resolved dependency is not a regular file")
    if entry is None:
        if lost or failed:
            raise PayloadRefusal(f"no frozen exclusion applies; unresolved or missing dynamic dependencies: "
                                 f"{lost[:20]}; non-importing lib-dynload modules: {failed}")
        return None
    name, elf, reasons = entry.path.rsplit("/", 1)[1], baseline["elves"].get(entry.path), list[str]()
    if NATIVE.get(baseline["machine"]) != entry.architecture:
        reasons.append(f"native architecture {baseline['machine']!r} is not {entry.architecture}")
    if baseline["dynload_real"] != DYNLOAD:
        reasons.append(f"lib-dynload resolves to {baseline['dynload_real']}")
    if [n for n, _kind in baseline["dynload"] if n.split(".", 1)[0] == entry.module] != [name] \
            or [name, "file"] not in baseline["dynload"]:
        reasons.append(f"{entry.module} is absent, duplicated, a symlink or not a regular file")
    if elf is None or [elf["sha256"], elf["size"], elf["elf"]] != [entry.sha256, entry.size, [2, 1, entry.elf_machine]]:
        reasons.append("target hash, size or ELF class/machine differs from the frozen identity")
    if sorted(lost) != [f"{entry.path}: {library} => not found" for library in entry.missing]:
        reasons.append(f"unresolved findings are not exactly the frozen missing pair: {lost[:20]}")
    if failed != [entry.module] or imports != list(entry.baseline_imports):
        reasons.append(f"non-importing modules {failed} or the baseline imports differ from the frozen set")
    if reasons:
        raise PayloadRefusal("frozen exclusion refused: " + "; ".join(reasons))
    return {**entry._asdict(), "missing": list(entry.missing), "baseline_imports": len(entry.baseline_imports),
            "reason": "unusable Tk bridge: Tcl/Tk libraries are absent from the base"}


def remove_exclusion(mount: Path, entry: PayloadExclusion) -> None:
    """Unlink the one classified regular file after re-checking its bytes; no glob or other path."""
    file = mount / entry.path.lstrip("/")
    if not stat.S_ISREG(os.lstat(file).st_mode) or hashlib.sha256(file.read_bytes()).hexdigest() != entry.sha256:
        raise PayloadRefusal("the excluded file changed between classification and removal")
    os.unlink(file)


def owners(run: Runner, targets: Mapping[str, Sequence[Any]]) -> dict[str, str]:
    """The existing rule: each resolved dependency is CPython's own or has a dpkg owner."""
    found: dict[str, str] = {}
    for target, (real, _digest) in sorted(targets.items()):
        found[target] = "cpython" if str(real).startswith(ROOT + "/") else ""
        for candidate in dict.fromkeys((str(real), "/" + str(real).removeprefix("/usr/"))):
            if found[target]:
                break
            done = run(["dpkg-query", "-S", candidate], capture_output=True, text=True, check=False)
            if done.returncode == 0 and done.stdout.strip():
                found[target] = done.stdout.split(":", 1)[0].strip()
    return found


def verify_retained(before: Mapping[str, list[Any]], after_entries: Mapping[str, list[Any]],
                    after: Mapping[str, Any], entry: PayloadExclusion | None,
                    ownership: Mapping[str, str]) -> dict[str, Any]:
    removed = None if entry is None else entry.path
    expected = {path: value for path, value in before.items() if path != removed}
    wanted = lib_dynload_modules(after) if entry is None else list(entry.baseline_imports)
    reasons = []
    if changed := sorted(p for p in {*expected, *after_entries} if expected.get(p) != after_entries.get(p)):
        reasons.append(f"payload entries differ besides the exclusion: {changed[:20]}")
    if removed is not None and removed in after_entries:
        reasons.append(f"{removed} is still present")
    if lost := unresolved(after["elves"]):
        reasons.append(f"retained ELF dependencies are unresolved: {lost[:20]}")
    if unowned := sorted(target for target, owner in ownership.items() if not owner):
        reasons.append(f"retained dependencies have no CPython or dpkg owner: {unowned[:20]}")
    if after["imports"] != wanted or after["failed"] or lib_dynload_modules(after) != wanted:
        reasons.append(f"retained imports {after['imports']} or failures {sorted(after['failed'])} differ")
    if reasons:
        raise PayloadRefusal("retained payload refused: " + "; ".join(reasons))
    return {"entries": len(after_entries), "digest": _digest(after_entries), "expected_digest": _digest(expected),
            "elf_count": len(after["elves"]), "elves": {path: elf["sha256"] for path, elf in after["elves"].items()},
            "unresolved": [], "imports": list(after["imports"]), "lib_dynload": lib_dynload_modules(after),
            "targets": dict(after["targets"]), "owners": dict(ownership),
            "excluded_absent": None if removed is None else removed not in after_entries, "preserved": True}


def main(argv: Sequence[str], *, run: Runner = subprocess.run, mount: Path = Path("/"),
         executable: str = sys.executable, machine: Callable[[], str] = platform.machine,
         exclusions: Mapping[str, PayloadExclusion] = PYTHON_PAYLOAD_EXCLUSIONS) -> int:
    """``ARCH [--no-exclusion]``: print one JSON report; exit 0 only for a clean or exactly trimmed payload."""
    architecture, options = (argv[0] if argv else ""), list(argv[1:])
    report: dict[str, Any] = {"schema": SCHEMA, "architecture": architecture, "result": "refused", "reasons": [],
                              "baseline": None, "exclusion": None, "retained": None}
    try:
        if options not in ([], ["--no-exclusion"]):
            raise PayloadRefusal(f"usage: ARCH [--no-exclusion], not {list(argv)}")
        if not sys.dont_write_bytecode:
            raise PayloadRefusal("bytecode writes would change the payload; run with -B")
        if NATIVE.get(native := machine()) != architecture:
            raise PayloadRefusal(f"native architecture {native!r} is not {architecture!r}")
        entry = None if options else exclusions.get(architecture)
        if entry is not None:
            validate_exclusion(entry, architecture)
        before, baseline = observe(run, mount, executable, native)
        report["baseline"] = baseline  # the complete raw findings, recorded before any removal
        report["exclusion"] = classify(baseline, entry)
        after_entries, after = before, baseline
        if entry is not None:
            remove_exclusion(mount, entry)
            after_entries, after = observe(run, mount, executable, native)
        report["retained"] = verify_retained(before, after_entries, after, entry, owners(run, after["targets"]))
        report["result"] = "clean" if entry is None else "trimmed"
    except (PayloadRefusal, OSError) as error:
        report["reasons"].append(f"{type(error).__name__}: {error}"[:4000])
    print(json.dumps(report, sort_keys=True))
    return 0 if report["result"] != "refused" else 1


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
# ADR 0096 Decision 3: narrow amd64 base-support package check for gcc-14-base.
RELEASE_FINAL_PACKAGE_CHECK_PY = """\
import os, stat
GCC14_BASE_DIRS = {"/", "/.", "/usr", "/usr/share", "/usr/share/doc", "/usr/share/doc/gcc-14-base"}
GCC14_BASE_DOCS = {
    "/usr/share/doc/gcc-14-base/README.Debian.amd64.gz",
    "/usr/share/doc/gcc-14-base/TODO.Debian",
    "/usr/share/doc/gcc-14-base/changelog.Debian.gz",
    "/usr/share/doc/gcc-14-base/copyright",
}
def gcc14_base_allowed(packages, root=""):
    if packages.count("gcc-14-base") != 1:
        return False
    code, meta = run(
        "dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${Architecture}\\t${db:Status-Abbrev}\\n",
        "gcc-14-base", codes=(0, 1),
    )
    rows = [line.split("\\t") for line in meta.splitlines() if line]
    if code != 0 or len(rows) != 1 or rows[0][:3] != ["gcc-14-base", "14.2.0-19", "amd64"]:
        return False
    if len(rows[0]) != 4 or rows[0][3] not in ("ii", "ii "):
        return False
    code, files = run("dpkg-query", "-L", "gcc-14-base:amd64", codes=(0, 1))
    listed = {line.strip() for line in files.splitlines() if line.strip()}
    required = {"/usr", "/usr/share", "/usr/share/doc", "/usr/share/doc/gcc-14-base"} | GCC14_BASE_DOCS
    if code != 0 or not (required <= listed <= (GCC14_BASE_DIRS | GCC14_BASE_DOCS)):
        return False
    if not (listed & {"/", "/."}) or any(p.endswith((".h", ".hpp")) or "/include/" in p for p in listed):
        return False
    rules = dpkg_rules(f"{root}/etc/dpkg/dpkg.cfg.d" if root else "/etc/dpkg/dpkg.cfg.d")
    for path in sorted(listed & GCC14_BASE_DIRS):
        target = (root or path) if path in ("/", "/.") else f"{root}{path}"
        try:
            mode = os.lstat(target).st_mode
        except OSError:
            return False
        if not stat.S_ISDIR(mode):
            return False
    for path in sorted(GCC14_BASE_DOCS):
        target = f"{root}{path}"
        if not os.path.lexists(target):
            if not filtered(f"missing   {path}", rules):
                return False
            continue
        try:
            mode = os.lstat(target).st_mode
            magic = open(target, "rb").read(4) if stat.S_ISREG(mode) else b""
        except OSError:
            return False
        if not stat.S_ISREG(mode) or (mode & 0o111) != 0 or magic == b"\\x7fELF":
            return False
    code, verify = run("dpkg", "--verify", "gcc-14-base:amd64", codes=(0, 1))
    if code != 0 and not verify:
        return False
    for line in verify.splitlines():
        if len(line.split()) != 2 or line.split()[1] not in GCC14_BASE_DOCS or not filtered(line, rules):
            return False
    return True
def forbidden_packages(packages, root=""):
    offending = [p for p in packages if p.endswith("-dev") or p in {"gcc", "binutils", "cpp"} or p.startswith("gcc-")]
    if "gcc-14-base" in offending and gcc14_base_allowed(packages, root=root):
        return [p for p in offending if p != "gcc-14-base"]
    return offending
"""


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
