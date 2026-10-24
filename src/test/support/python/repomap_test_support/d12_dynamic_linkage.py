"""ADR 0089 D2 dynamic-linkage evidence for an image that carries C Psycopg.

The module is stdlib-only so its own source can run as the in-image probe
(``python -I -c <source> probe``) with no mount and no network. ``assess``
turns one probe report into the D2 refusals; an empty list is the only pass.
The probe observes a disposable dependency-only image or a candidate image;
it never decides which one is product evidence.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

LIBPQ_SONAME = "libpq.so.5"
# ADR 0089 names PQ*, pg_* and lo_*; psycopg-c also defines its own pg_lltoa and
# pg_ulltoa_n (PostgreSQL-derived numutils.c). Only symbols the actual system
# libpq exports therefore count as libpq symbols; the prefix match is reported.
LIBPQ_SYMBOL = re.compile(r"(?:PQ|pg_|lo_)\w")
LIBRARY_FILE = re.compile(r"libpq[^/]*\.(?:so(?:\.\d+)*|a|dylib)\Z")
_SHT_DYNAMIC, _SHT_DYNSYM, _DT_NEEDED = 6, 11, 1


class ElfDynamic(NamedTuple):
    needed: tuple[str, ...]
    undefined: tuple[str, ...]
    defined: tuple[str, ...]


def _text(table: bytes, offset: int) -> str:
    end = table.find(b"\0", offset)
    return table[offset:end if end >= 0 else len(table)].decode("utf-8", "replace")


def elf_dynamic(data: bytes) -> ElfDynamic:
    """Read DT_NEEDED and dynamic symbols from ELF bytes without executing them."""
    if data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise ValueError("not a supported ELF object")
    wide, order = data[4] == 2, "<" if data[5] == 1 else ">"
    if wide:
        shoff, = struct.unpack_from(order + "Q", data, 0x28)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x3A)
        section, dyn, sym = "IIQQQQIIQQ", "qQ", "IBBHQQ"
    else:
        shoff, = struct.unpack_from(order + "I", data, 0x20)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x2E)
        section, dyn, sym = "IIIIIIIIII", "iI", "IIIBBH"
    headers = [struct.unpack_from(order + section, data, shoff + index * shentsize) for index in range(shnum)]

    def body(header: tuple[int, ...]) -> bytes:
        return data[header[4]:header[4] + header[5]]

    needed: list[str] = []
    undefined: set[str] = set()
    defined: set[str] = set()
    for header in headers:
        kind, link = header[1], header[6]
        if kind == _SHT_DYNAMIC:
            strings, step = body(headers[link]), struct.calcsize(order + dyn)
            raw = body(header)
            for offset in range(0, len(raw) - step + 1, step):
                tag, value = struct.unpack_from(order + dyn, raw, offset)
                if tag == 0:
                    break
                if tag == _DT_NEEDED:
                    needed.append(_text(strings, value))
        elif kind == _SHT_DYNSYM:
            strings, step = body(headers[link]), struct.calcsize(order + sym)
            raw = body(header)
            for offset in range(step, len(raw) - step + 1, step):
                fields = struct.unpack_from(order + sym, raw, offset)
                name = _text(strings, fields[0])
                index = fields[3] if wide else fields[5]
                if name:
                    (undefined if index == 0 else defined).add(name)
    return ElfDynamic(tuple(needed), tuple(sorted(undefined)), tuple(sorted(defined)))


def extension_linkage(path: str, data: bytes, libpq_exports: frozenset[str]) -> dict[str, Any]:
    """Summarize one installed ELF against the symbols the system libpq exports."""
    elf = elf_dynamic(data)
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "needed": list(elf.needed),
        "libpq_undefined": [name for name in elf.undefined if name in libpq_exports],
        "libpq_defined": [name for name in elf.defined if name in libpq_exports],
        "prefix_defined_not_libpq": [n for n in elf.defined if LIBPQ_SYMBOL.match(n) and n not in libpq_exports],
    }


def dpkg_filters(root: Path = Path("/etc/dpkg/dpkg.cfg.d")) -> list[tuple[str, str]]:
    """The image's ``path-exclude``/``path-include`` rules, in dpkg's evaluation order."""
    rules = []
    for config in sorted(root.glob("*")) if root.is_dir() else ():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ("path-exclude", "path-include"):
                rules.append((parts[0], parts[1]))
    return rules


def verify_problems(lines: list[str], rules: list[tuple[str, str]]) -> list[str]:
    """``dpkg --verify`` lines other than files the image's own dpkg filters never installed."""
    problems = []
    for line in lines:
        fields = line.split()
        excluded = False
        if fields[:1] == ["missing"]:
            for kind, pattern in rules:
                if fnmatch.fnmatchcase(fields[-1], pattern):
                    excluded = kind == "path-exclude"
        if not excluded:
            problems.append(line)
    return problems


def _run(*command: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def probe() -> dict[str, Any]:
    """Observe the running interpreter after importing Psycopg; never raises on a missing fact."""
    os.environ.pop("PSYCOPG_IMPL", None)
    import psycopg
    from psycopg import pq

    with open("/proc/self/maps", encoding="utf-8") as maps:
        mapped = sorted({line.split()[-1] for line in maps if "libpq" in line and "/" in line})
    exports = frozenset().union(*(elf_dynamic(Path(os.path.realpath(p)).read_bytes()).defined for p in mapped))
    distribution = importlib.metadata.distribution("psycopg-c")
    extensions = []
    for item in distribution.files or ():
        located = Path(str(distribution.locate_file(item)))
        if located.is_file() and located.read_bytes()[:4] == b"\x7fELF":
            extensions.append(extension_linkage(str(located), located.read_bytes(), exports))
    loaded: list[dict[str, Any]] = []
    rules = dpkg_filters()
    for path in mapped:
        real = os.path.realpath(path)
        owner_line = _run("dpkg", "-S", real) or _run("dpkg", "-S", "/" + real.removeprefix("/usr/"))
        owner = owner_line.split(":", 1)[0] if owner_line else ""
        loaded.append({
            "mapped": path, "real_path": real,
            "sha256": hashlib.sha256(Path(real).read_bytes()).hexdigest(), "owner": owner,
            "owner_version": _run("dpkg-query", "-W", "-f=${Version}", owner) if owner else "",
        })
        verify = subprocess.run(["dpkg", "--verify", owner], capture_output=True, text=True,
                                check=False) if owner else None
        lines = verify.stdout.splitlines() if verify else ["unowned"]
        loaded[-1].update(verify_lines=len(lines), verify_problems=verify_problems(lines, rules)[:40],
                          verify_names_library=any(real in line or path in line for line in lines),
                          verify_returncode=verify.returncode if verify else None,
                          verify_stderr=verify.stderr.strip()[:400] if verify else "")
    distributions = sorted(d.metadata["Name"].lower() for d in importlib.metadata.distributions())
    local_libpq = sorted(str(p) for p in Path("/usr/local").rglob("libpq*") if LIBRARY_FILE.search(p.name))
    return {
        "psycopg": psycopg.__version__, "psycopg_c": distribution.version,
        "implementation": pq.__impl__, "libpq_runtime": pq.version(), "libpq_build": pq.__build_version__,
        # Recorded, not gated: 3.3.6 bounds cancel_safe(timeout=...) only with libpq >= 17.
        "has_cancel_safe": psycopg.capabilities.has_cancel_safe(),
        "psycopg_impl_env": os.environ.get("PSYCOPG_IMPL"),
        "binary_module": importlib.util.find_spec("psycopg_binary") is not None,
        "binary_distribution": "psycopg-binary" in distributions,
        "extensions": extensions, "loaded_libpq": loaded, "usr_local_libpq": local_libpq,
    }


def assess(report: dict[str, Any], *, psycopg_version: str, libpq_version: int | None = None) -> list[str]:
    """Return every unmet D2 condition; the frozen libpq value is checked only when supplied."""
    failures = []
    if report.get("psycopg") != psycopg_version or report.get("psycopg_c") != psycopg_version:
        failures.append(f"psycopg/psycopg-c version differs from {psycopg_version}")
    if report.get("implementation") != "c" or report.get("psycopg_impl_env") is not None:
        failures.append("implementation is not c with PSYCOPG_IMPL unset")
    if report.get("libpq_runtime") != report.get("libpq_build"):
        failures.append("runtime libpq differs from build headers")
    if libpq_version is not None and report.get("libpq_runtime") != libpq_version:
        failures.append(f"runtime libpq differs from frozen {libpq_version}")
    if report.get("binary_module") or report.get("binary_distribution"):
        failures.append("psycopg-binary is present")
    if report.get("usr_local_libpq"):
        failures.append("a private libpq exists under /usr/local")
    referencing = [e for e in report.get("extensions", ()) if e["libpq_undefined"] or e["libpq_defined"]]
    if not referencing:
        failures.append("no psycopg-c ELF references a libpq symbol")
    for item in referencing:
        if LIBPQ_SONAME not in item["needed"]:
            failures.append(f"{item['path']} lacks DT_NEEDED {LIBPQ_SONAME}")
        if item["libpq_defined"]:
            failures.append(f"{item['path']} defines libpq symbols locally")
    loaded = report.get("loaded_libpq", ())
    if len(loaded) != 1:
        failures.append(f"expected exactly one mapped libpq, found {len(loaded)}")
    for item in loaded:
        if not Path(item["real_path"]).name.startswith(LIBPQ_SONAME):
            failures.append(f"unexpected mapped libpq {item['real_path']}")
        if (item["owner"] != "libpq5" or not item["owner_version"] or item["verify_problems"]
                or item["verify_names_library"]):
            failures.append(f"loaded libpq {item['real_path']} is not a verified libpq5 file")
        # dpkg --verify exits 0 (clean) or 1 (problems reported on stdout); anything else did not verify.
        code, error = item.get("verify_returncode"), item.get("verify_stderr")
        if code not in (0, 1) or (code == 0 and error) or (code == 1 and not item["verify_lines"]):
            failures.append(f"dpkg --verify of {item['owner'] or 'an unowned file'} did not complete (exit {code})")
    return failures


def probe_source() -> str:
    """The exact in-image probe program: this module's source plus its entry point."""
    return Path(__file__).read_text(encoding="utf-8")


if __name__ == "__main__" and sys.argv[1:] == ["probe"]:
    print(json.dumps(probe(), sort_keys=True))
