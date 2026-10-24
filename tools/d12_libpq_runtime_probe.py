#!/usr/bin/env python3
"""ADR 0091 numeric libpq proof (accepted N1-N9, C1-C3), E1 only: host ``observe`` stages, runs once and rechecks;
container ``main`` needs the run-bound marker, installs the libpq5 subset behind ``Guard``, calls PQlibVersion."""

from __future__ import annotations

import base64, ctypes, fnmatch, glob, hashlib, json, os, stat, subprocess, sys
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Sequence

import native_apt_prerequisites as apt

SCHEMA, INPUT_SCHEMA = "repomap-d12-libpq-runtime-v1", "repomap-d12-libpq-input-v1"
MARKER_SCHEMA, RECORD_SCHEMA = "repomap-d12-libpq-marker-v1", "repomap-d12-libpq-record-v1"
ROLE, LABEL = "d12-explore-builder", "org.repomap.test.resource"  # explore's only builder; resource_docker's labels
INPUT_LIMIT, RESULT_LIMIT, CHUNK = 256 * 1024, 128 * 1024, 64 * 1024  # CHUNK: whole base64 groups per argument
STAGE, PROBE, HELPER = "/tmp/repomap-d12-libpq.", "d12_libpq_runtime_probe.py", "native_apt_prerequisites.py"
STAGED, HASHES = ("input.json", "marker.json", PROBE, HELPER), ("input_sha256", "probe_sha256", "helper_sha256")
BOOT = ("import sys; sys.path.insert(0, sys.argv[1]); import d12_libpq_runtime_probe as probe; "
        "raise SystemExit(probe.main(sys.argv[2:]))")
ROOTS = ("/lib", "/usr/lib", "/usr/local/lib", "/opt")  # the bounded loader roots; not every path on a filesystem
FIXED, COPYRIGHT = ("libssl3t64", "libc6"), "/usr/share/doc/libpq5/copyright"  # TLS and glibc rows and bytes stay
ORDER = ("update", "simulate", "download", "install", "mark")  # C1: the helper's only mutating steps, in order
INSTALL = ("apt-get", "install", "--yes", "--no-install-recommends", "--no-remove", "-o")
VERIFIED, FIELDS = "host-rechecked builder result", (apt._NAME, apt._VERSION, apt._ARCH, apt._SHA256)
INPUT_KEYS = {"schema", "role", "run_id", "platform", "libpq5_version", "library", "table"}
RECORD_KEYS = {"schema", "verified", "run_id", "api", "native", "library", "selected", "manifest_sha256", *HASHES}
RESULT_KEYS = {"schema", "result", "role", "run_id", "native", "api", "library", "manifest", "manifest_sha256", "added",
               "verify", "maps", "fixed", *HASHES}
_NATIVE = {"aarch64": "linux/arm64", "arm64": "linux/arm64", "x86_64": "linux/amd64", "amd64": "linux/amd64"}

class ProbeRefused(apt.PrerequisiteRefused):
    """The numeric proof cannot be made exact; a RuntimeError, never an OSError the helper would relabel."""

def canonical(value: Any) -> bytes: return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _text(pattern: Any, value: object) -> bool: return isinstance(value, str) and pattern.fullmatch(value) is not None

def _excluded(line: str, rules: Sequence[Sequence[str]], protected: Sequence[str]) -> bool:
    fields, excluded = line.split(), False  # ADR 0089 D2.3 slim-image filter: missing excluded paths only
    if len(fields) >= 2 and fields[0] == "missing" and fields[-1][:1] == "/" and not any(p in line for p in protected):
        for kind, pattern in rules:
            if fnmatch.fnmatchcase(fields[-1], pattern):
                excluded = kind == "path-exclude"
    return excluded

def pq_lib_version(path: str) -> object:  # load the verified absolute library and call int PQlibVersion(void)
    function = ctypes.CDLL(path).PQlibVersion
    function.argtypes, function.restype = [], ctypes.c_int
    return function()

class Native(NamedTuple):
    """This process's container facts; unit tests substitute each one."""
    root: str = "/"
    execute: Callable[..., Any] = subprocess.run
    system: Callable[[], tuple[object, ...]] = lambda: (sys.platform, os.uname().machine, sys.flags.isolated,
                                                        sys.flags.dont_write_bytecode, sys.flags.optimize, __debug__)
    load: Callable[[str], object] = pq_lib_version
    modules: Callable[[], tuple[str, str]] = lambda: (__file__, str(apt.__file__))
    environ: Mapping[str, str] = os.environ

    def at(self, path: str) -> Path: return Path(os.path.realpath(self.root)) / path.lstrip("/")
    def inside(self, host: str) -> str: return "/" + os.path.relpath(host, os.path.realpath(self.root))

    def libpq_files(self) -> dict[str, str]:  # every libpq-named file or link below the roots, to its real path
        return {self.inside(host): self.inside(os.path.realpath(host)) for root in ROOTS
                for directory, _subdirectories, names in os.walk(self.at(root))
                for host in (os.path.join(directory, n) for n in names if n.startswith("libpq") and ".so" in n)}

    def mapped_libpq(self) -> set[str]:
        maps = self.at("/proc/self/maps").read_text(encoding="utf-8", errors="replace").splitlines()
        return {path for fields in (line.split(None, 5) for line in maps) if len(fields) == 6
                and os.path.basename(path := fields[5].strip()).startswith("libpq")}

def check_input(value: Any) -> dict[str, Any]:  # the bounded probe input: schema, role, run, platform, library, table
    library, table = (value.get("library"), value.get("table")) if isinstance(value, dict) else (None, None)
    path = library.get("path") if isinstance(library, dict) else None
    if not (isinstance(value, dict) and set(value) == INPUT_KEYS and value["schema"] == INPUT_SCHEMA
            and value["role"] == ROLE and isinstance(value["run_id"], str) and 0 < len(value["run_id"]) <= 256
            and value["platform"] in _NATIVE.values() and _text(apt._VERSION, value["libpq5_version"])
            and isinstance(library, dict) and set(library) == {"path", "sha256"} and isinstance(path, str)
            and os.path.normpath(path) == path and path.startswith(tuple(f"{root}/" for root in ROOTS))
            and _text(apt._SHA256, library["sha256"]) and isinstance(table, list) and 0 < len(table) <= 4096
            and all(isinstance(row, list) and len(row) == 4 and all(map(_text, FIELDS, row)) for row in table)):
        raise ProbeRefused("malformed or unbound probe input")
    return value

def members(rows: Any, expected: Mapping[str, Any]) -> list[tuple[str, ...]]:  # exact resolved-table subset
    table, architecture = [tuple(row) for row in expected["table"]], expected["platform"].split("/", 1)[1]
    ok = isinstance(rows, list) and all(isinstance(r, list | tuple) for r in rows)
    found = [tuple(r) for r in rows] if ok else []
    if not found or len({row[0] for row in found if row}) != len(found) or any(table.count(row) != 1 for row in found):
        raise ProbeRefused(f"the selection is not an exact non-duplicate subset of the resolved builder table: {found}")
    if [row[1:3] for row in found if row[0] == "libpq5"] != [(expected["libpq5_version"], architecture)]:
        raise ProbeRefused("the selection does not hold exactly the expected native libpq5 version")
    return [(str(a), str(b), str(c), str(d)) for a, b, c, d in found]

def selected_rows(manifest: Any, expected: Mapping[str, Any]) -> list[tuple[str, ...]]:
    item = manifest if isinstance(manifest, dict) else {}
    head, packages = (item.get("schema"), item.get("native_architecture"), item.get("requested")), item.get("packages")
    if head != (apt.SCHEMA, expected["platform"].split("/", 1)[1], ["libpq5"]) or not isinstance(packages, list) or \
            not all(isinstance(package, dict) for package in packages):
        raise ProbeRefused("the frozen manifest schema, native architecture, request or rows differ")
    return members([[p.get(k) for k in ("name", "version", "architecture", "sha256")] for p in packages], expected)

class Guard:
    """The probe's only runner (C1): the hash-bound helper's exact command shapes, in order, with the C2 gate."""
    def __init__(self, execute: Callable[..., Any], inputs: Mapping[str, Any], cache: Path) -> None:
        self.execute, self.inputs, self.cache, self.installed, self.code = execute, inputs, cache, False, 0
        self.held, self.done, self.pins = list[str](), list[str](), list[str]()
        self.before: Mapping[str, Mapping[str, str]] = {}
        self.manifest: bytes | None = None
    def dependencies(self) -> list[str]:  # the helper's apt-mark names: the frozen selection other than libpq5
        return sorted({row[0] for row in selected_rows(json.loads(self.manifest or b"{}"), self.inputs)} - {"libpq5"})
    def __call__(self, command: Sequence[str], **options: Any) -> Any:
        if (step := self._step(argv := [str(item) for item in command])) is not None:
            if ORDER[len(self.done):len(self.done) + 1] != (step,):
                raise ProbeRefused(f"{step} is out of the exact helper sequence after {self.done}; no repeat or retry")
            if step == "install":
                self._gate(argv)
            if step == "mark" and not (self.installed and argv[2:] and argv[2:] == self.dependencies()):
                raise ProbeRefused("apt-mark auto is not exactly the manifest's dependency names after the one install")
            self.done.append(step)
        completed = self.execute(argv, **options)
        self.code = completed.returncode
        self.installed = self.installed or step == "install" and completed.returncode == 0
        return completed
    def _step(self, c: list[str]) -> str | None:  # a read-only query (None), the next C1 step, or a refusal
        held, prefix, pins = len(self.held), [*INSTALL, f"Dir::Cache::Archives={self.cache}/"], c[8 + len(self.held):]
        if c in (["dpkg", "--print-architecture"], ["dpkg", "--verify", "libpq5"], ["apt-get", "indextargets"],
                 ["dpkg-query", "-W", "-f=" + apt._DPKG_FORMAT]) or len(c) == 3 and (
                c[:2] == ["dpkg-query", "-S"] and c[2].startswith("/")
                or c[:2] == ["dpkg-query", "-L"] and c[2] in FIXED
                or c[:2] == ["/usr/lib/apt/apt-helper", "cat-file"] and c[2].startswith("/var/lib/apt/lists/")
                and "/.." not in c[2]) or len(c) == 6 and c[:2] == ["dpkg-deb", "--field"] and os.path.dirname(
                c[2]) == str(self.cache) and c[3:] == ["Package", "Version", "Architecture"]:
            return None
        if c == ["apt-get", "update"] or c == ["apt-get", "install", "--simulate", "--no-install-recommends",
                                               *self.held, "libpq5"]:
            return "update" if c[1] == "update" else "simulate"
        if len(c) > 8 + held and c[:7] == prefix and c[8:8 + held] == self.held:
            table = {f"{row[0]}={row[1]}" for row in self.inputs["table"]}
            if c[7] == "--download-only" and not self.pins and len(set(pins)) == len(pins) and set(pins) <= table:
                self.pins = pins
                return "download"
            if c[7] == "--no-download" and self.pins and pins == self.pins:
                return "install"
        if c[:2] == ["apt-mark", "auto"]:
            return "mark"
        raise ProbeRefused(f"command outside the hash-bound helper contract refused before dispatch: {' '.join(c[:3])}")
    def _gate(self, argv: list[str]) -> None:  # C1/C2: the just-frozen manifest is exactly the resolved subset
        data, current = (self.cache / "manifest.json").read_bytes(), apt.installed_packages(self)
        rows, listed = selected_rows(manifest := json.loads(data), self.inputs), manifest.get("archives")
        prior_names = {row["name"] for row in (*self.before.values(), *current.values())}
        if clash := sorted({row[0] for row in rows} & prior_names):
            raise ProbeRefused(f"selected packages already have an ii or rc row: {clash}")
        if current != self.before:
            raise ProbeRefused("installed baseline drifted before installation")
        archives = sorted(
            p.name for p in self.cache.iterdir() if p.is_file() and p.name not in ("lock", "manifest.json"))
        arch_shas = sorted(_sha((self.cache / n).read_bytes()) for n in archives)
        if self.pins != [f"{row[0]}={row[1]}" for row in rows] or not isinstance(listed, list) or archives != sorted(
                map(str, listed)) or arch_shas != sorted(r[3] for r in rows):
            raise ProbeRefused("cached archives or install pins drifted from the frozen manifest")
        self.manifest = data

def fixed_state(run: Callable[..., Any], rows: Mapping[str, Mapping[str, str]], native: Native) -> dict[str, Any]:
    state: dict[str, Any] = {}  # the TLS runtime and glibc: one installed row each and every regular owned file's bytes
    for name in FIXED:
        found = [(row["status"], row["architecture"], row["version"]) for row in rows.values() if row["name"] == name]
        if len(found) != 1 or found[0][0] != "ii":
            raise ProbeRefused(f"{name} is not exactly one installed row: {found}")
        files = [native.at(p) for p in apt.command_output(run, ["dpkg-query", "-L", name]).splitlines() if p[:1] == "/"]
        state[name] = [found[0], {str(f): _sha(f.read_bytes()) for f in files if f.is_file() and not f.is_symlink()}]
    return state

def run_internal(marker: str, native: Native) -> dict[str, Any]:  # refuse before any command unless every binding holds
    (platform_name, machine, *flags), stage = native.system(), os.path.dirname(marker)
    if platform_name != "linux" or tuple(flags) != (1, 1, 0, True):
        raise ProbeRefused("not the staged native Linux python3 -I -B process; nothing was run")
    if marker != f"{stage}/marker.json" or not stage.startswith(STAGE) or len(stage) != len(STAGE) + 10 or \
            not stage[len(STAGE):].isalnum() or list(native.modules()) != [f"{stage}/{PROBE}", f"{stage}/{HELPER}"]:
        raise ProbeRefused("the loaded probe or helper is not this run's staged bytes")
    if stat.S_IMODE((directory := native.at(stage)).stat().st_mode) != 0o700 or sorted(
            p.name for p in directory.iterdir()) != sorted(STAGED):
        raise ProbeRefused("the staged directory is not private or not exactly the four staged files")
    if len((data := {n: (directory / n).read_bytes() for n in STAGED})["input.json"]) > INPUT_LIMIT or len(
            data["marker.json"]) > 4096:
        raise ProbeRefused("the staged input or marker exceeds its bound")
    inputs = check_input(json.loads(data["input.json"]))
    hashes = dict(zip(HASHES, map(_sha, (data["input.json"], data[PROBE], data[HELPER]))))
    if json.loads(data["marker.json"]) != {"schema": MARKER_SCHEMA, "role": ROLE, "run_id": inputs["run_id"], **hashes}:
        raise ProbeRefused("the run-bound marker does not bind this role, run, input, probe and helper")
    if _NATIVE.get(str(machine)) != inputs["platform"]:
        raise ProbeRefused("the builder machine is not native for the input platform")
    refusals = sorted(f"{name} is set" for name, value in native.environ.items() if name.startswith("LD_") and value)
    if (preload := native.at("/etc/ld.so.preload")).is_file() and preload.read_text(errors="replace").strip():
        refusals.append("the loader preload file is not empty")  # the adopted loader strengthening, before any command
    allowed, seen = tuple(os.path.realpath(native.at(r)) for r in ROOTS), set[str]()
    for conf in (confs := [native.at("/etc/ld.so.conf")]):  # bounded: at most 64 loader configuration files
        if (real_conf := os.path.realpath(conf)) in seen or len(confs) > 64:
            refusals.append("loader configuration cycle or exceeds 64 files")
            break
        seen.add(real_conf)
        for item in (line.split("#", 1)[0].strip() for line in (conf.read_text(errors="replace").splitlines()
                                                                 if conf.is_file() else [])):
            if item.startswith("include") and item[7:8].isspace() and item[8:].strip().startswith("/"):
                confs += sorted(map(Path, glob.glob(str(native.at(item[8:].strip())))))
            elif item and (os.path.normpath(item) not in ROOTS and not os.path.normpath(item).startswith(
                    tuple(f"{r}/" for r in ROOTS)) or not any(
                    (real := os.path.realpath(native.at(item))) == r or real.startswith(f"{r}/") for r in allowed)):
                refusals.append(f"loader path {item} is outside the bounded roots")
    if refusals:
        raise ProbeRefused("; ".join(refusals))
    architecture, guard = inputs["platform"].split("/", 1)[1], Guard(native.execute, inputs, directory / "cache")
    if apt.command_output(guard, ["dpkg", "--print-architecture"]).strip() != architecture:
        raise ProbeRefused("dpkg's native architecture is not the input platform")
    before = guard.before = apt.installed_packages(guard)
    guard.held = apt.baseline_pins(before, architecture, ["libpq5"])
    if prior := [key for key, row in before.items() if row["name"] == "libpq5"] + sorted(native.libpq_files()) + sorted(
            native.mapped_libpq()):
        raise ProbeRefused(f"prior, private or unowned libpq before install: {prior}")
    fixed = fixed_state(guard, before, native)
    guard.cache.mkdir(mode=0o700)
    evidence = apt.install_prerequisites(guard, ["libpq5"], guard.cache)
    if guard.manifest is None or guard.done != list(ORDER if guard.dependencies() else ORDER[:4]) or evidence.get(
            "requested") != ["libpq5"] or evidence.get("manifest_sha256") != _sha(guard.manifest):
        raise ProbeRefused(f"the helper sequence or manifest differs from one gated install: {guard.done}")
    rows, after = selected_rows(json.loads(guard.manifest), inputs), apt.installed_packages(guard)
    added = sorted(f"{name}:{arch}={version}" for name, version, arch, _ in rows)
    grown = sorted(
        f"{key}={row['version']}" for key, row in after.items() if key not in before and row["status"] == "ii")
    if any(after.get(key) != row for key, row in before.items()) or grown != added or len(after) != len(before) + len(
            added) or sorted(evidence.get("added") or []) != added:
        raise ProbeRefused(f"the installed set is not exactly the gated selection on an unchanged baseline: {grown}")
    if fixed_state(guard, after, native) != fixed:
        raise ProbeRefused("the TLS or glibc rows or bytes changed")
    path, digest, version = inputs["library"]["path"], inputs["library"]["sha256"], inputs["libpq5_version"]
    file, found = native.at(path), native.libpq_files()  # the one native libpq5, its owned aliases, bytes and verify
    pq_rows = [
        (row["status"], row["architecture"], row["version"]) for row in after.values() if row["name"] == "libpq5"]
    if pq_rows != [("ii", architecture, version)] or set(found.values()) != {path} or found.get(
            os.path.join(os.path.dirname(path), "libpq.so.5")) != path or file.is_symlink() or not file.is_file():
        raise ProbeRefused(f"installed libpq5 is not exactly the one owned native file: {pq_rows} {sorted(found)}")
    merged = os.path.realpath(native.at("/lib")) == os.path.realpath(native.at("/usr/lib"))
    if {apt.package_of(guard, "/usr" + item if merged and item.startswith("/lib/") else item) for item in found} != {
            "libpq5"}:
        raise ProbeRefused("installed libpq paths are not all owned by libpq5")
    cfg_d, notice = native.at("/etc/dpkg/dpkg.cfg.d"), native.at(COPYRIGHT)
    rules = [parts for cfg in (sorted(cfg_d.glob("*")) if cfg_d.is_dir() else ()) if cfg.is_file()
             for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines()
             if len(parts := line.split()) == 2 and parts[0] in ("path-exclude", "path-include")]
    v_lines = apt.command_output(guard, ["dpkg", "--verify", "libpq5"], accept=(0, 1)).splitlines()
    bad_verify = (guard.code != 0 and not v_lines) or any(
        not _excluded(line, rules, (path, *found, "libpq.so", COPYRIGHT)) for line in v_lines)
    if problems := [text for text, bad in (  # dpkg --verify is the probe's own post-install check (ADR 0089 D2.3)
            ("the installed library bytes differ from the server library", _sha(file.read_bytes()) != digest),
            ("dpkg --verify libpq5 reports a mismatch", bad_verify),
            ("the libpq5 copyright is absent", notice.is_symlink() or not notice.is_file())) if bad]:
        raise ProbeRefused("; ".join(problems))
    if type(api := native.load(path)) is not int or api <= 0:
        raise ProbeRefused(f"PQlibVersion returned no positive int: {api!r}")
    if (maps := sorted(native.mapped_libpq())) != [path]:
        raise ProbeRefused(f"the process maps do not bind exactly the one verified libpq: {maps}")
    shaped = record(
        inputs, hashes, api=api, machine=str(machine), selected=rows, digests=(_sha(notice.read_bytes()), ""))
    return {"schema": SCHEMA, "result": "observed", "role": ROLE, "run_id": inputs["run_id"], **hashes, "api": api,
            "native": shaped["native"], "library": shaped["library"], "manifest": json.loads(guard.manifest),
            "manifest_sha256": evidence["manifest_sha256"], "added": added, "maps": maps,
            "verify": {"status": "filtered", "rules": rules, "ignored": v_lines} if v_lines else "clean",
            "fixed": {name: value[0][2] for name, value in fixed.items()}}

def binding(steps: Mapping[str, Any], server_inventory: Mapping[str, Any], platform: str,
            run_id: str) -> tuple[dict[str, Any], dict[str, str]]:  # E3's resolved table and server file
    libs = sorted({(f.get("resolved"), f.get("sha256")) for f in server_inventory.get("files", [])
                   if f.get("role") == "libpq" and f.get("owner") == "libpq5"})
    if len(libs) != 1:
        raise ProbeRefused(f"the PostgreSQL base libpq5 file is absent or ambiguous: {libs}")
    pkgs = (steps.get("builder") or {}).get("packages", [])
    table = [[p.get(k) for k in ("name", "version", "architecture", "sha256")] for p in pkgs]
    expected = check_input({
        "schema": INPUT_SCHEMA, "role": ROLE, "run_id": run_id, "platform": platform, "table": table,
        "libpq5_version": steps.get("libpq5_version"), "library": {"path": libs[0][0], "sha256": libs[0][1]}})
    code = (canonical(expected), Path(__file__).read_bytes(), Path(str(apt.__file__)).read_bytes())
    return expected, dict(zip(HASHES, map(_sha, code)))

def record(expected: Mapping[str, Any], hashes: Mapping[str, str], *, api: object, machine: str,
           selected: Sequence[Sequence[str]], digests: tuple[object, object]) -> dict[str, Any]:
    architecture = expected["platform"].split("/", 1)[1]  # the verified record shape; ``check_record`` rebuilds it
    return {"schema": RECORD_SCHEMA, "verified": VERIFIED, "run_id": expected["run_id"], "api": api,
            "native": {"machine": machine, "dpkg": architecture, "platform": expected["platform"]},
            "library": {**expected["library"], "package": "libpq5", "version": expected["libpq5_version"],
                        "architecture": architecture, "copyright_sha256": digests[0]},
            "selected": [list(row) for row in selected], "manifest_sha256": digests[1], **hashes}

def check_record(value: Any, expected: Mapping[str, Any], hashes: Mapping[str, str]) -> int:  # exact record or refuse
    if not (isinstance(value, dict) and set(value) == RECORD_KEYS
            and isinstance(value["native"], dict) and isinstance(value["library"], dict)):
        raise ProbeRefused("no verified runtime libpq observation; a package-derived number is never substituted")
    api, machine = value["api"], str(value["native"].get("machine"))
    digests = (value["library"].get("copyright_sha256"), value["manifest_sha256"])
    rows = members(value["selected"], expected)
    if value != record(expected, hashes, api=api, machine=machine, selected=rows, digests=digests) or type(
            api) is not int or api <= 0 or _NATIVE.get(machine) != expected["platform"] or not all(
            _text(apt._SHA256, d) for d in digests):
        raise ProbeRefused("the runtime libpq observation (library or native identity, rows or hashes) is not bound "
                           f"to these inputs or is not a positive int: {api!r}")
    return api

def consume(value: Any, steps: Mapping[str, Any], server_inventory: Mapping[str, Any], platform: str) -> int:
    """The candidate's only libpq number: a host-verified record still bound to these inputs and code; never derived"""
    if not isinstance(run_id := value.get("run_id") if isinstance(value, dict) else None, str):
        raise ProbeRefused("no verified runtime libpq observation; a package-derived number is never substituted")
    return check_record(value, *binding(steps, server_inventory, platform, run_id))

def verify_result(code: int, stdout: bytes, stderr: bytes, expected: Mapping[str, Any],
                  hashes: Mapping[str, str]) -> dict[str, Any]:  # independent recheck; its own "observed" is not enough
    if len(stdout) > RESULT_LIMIT or stderr.strip():
        raise ProbeRefused(
            f"probe output is oversize or has chatter ({len(stdout)} stdout, {len(stderr)} stderr bytes)")
    try:
        result = json.loads(stdout)
    except ValueError as error:
        raise ProbeRefused("probe output is not exactly one JSON object") from error
    if code == 2 and isinstance(result, dict) and set(result) == {"schema", "result", "refusal"} and (
            result["result"] == "refused"):
        raise ProbeRefused(f"numeric probe refused in the builder: {str(result['refusal'])[:4000]}")
    if code != 0 or not isinstance(result, dict) or set(result) != RESULT_KEYS:
        raise ProbeRefused(f"malformed or failed probe result (exit {code})")
    rows, ver = selected_rows(result["manifest"], expected), result["verify"]
    ok_ver = ver == "clean" or isinstance(ver, dict) and set(ver) == {"status", "rules", "ignored"} and ver[
        "status"] == "filtered" and isinstance(ver["rules"], list) and isinstance(ver["ignored"], list) and bool(
        ver["ignored"]) and all(isinstance(r, list) and len(r) == 2 and r[0] in ("path-exclude", "path-include") and
                                isinstance(r[1], str) for r in ver["rules"]) and all(
        isinstance(line, str) and _excluded(line, ver["rules"], (expected["library"]["path"], "libpq.so", COPYRIGHT))
        for line in ver["ignored"])
    checks = {"schema": SCHEMA, "result": "observed", "role": ROLE, "run_id": expected["run_id"], **hashes,
              "manifest_sha256": _sha(canonical(result["manifest"])), "verify": ver if ok_ver else "clean", "maps": [
                  expected["library"]["path"]], "added": sorted(f"{n}:{a}={v}" for n, v, a, _ in rows)}
    if differ := sorted(key for key, value in checks.items() if result[key] != value):
        raise ProbeRefused(f"probe result identities differ from the host's: {differ}")
    verified = {"schema": RECORD_SCHEMA, "verified": VERIFIED, "run_id": expected["run_id"], "api": result["api"],
                "native": result["native"], "library": result["library"], "selected": [list(row) for row in rows],
                "manifest_sha256": result["manifest_sha256"], **hashes}
    check_record(verified, expected, hashes)  # rebuilds the exact library, native and row identities from the host
    return verified

def observe(container: Any, steps: Mapping[str, Any], server_inventory: Mapping[str, Any], platform: str,
            bindings: Mapping[str, object]) -> dict[str, Any]:  # E3 builder only, after resolve and its header check
    def run(command: list[str]) -> bytes:
        if (done := container.exec_run(command, demux=True)).exit_code != 0:
            raise ProbeRefused(f"builder staging command failed: {command[0]} exited {done.exit_code}")
        return (done.output or (None, None))[0] or b""
    attrs, run_id = getattr(container, "attrs", None) or {}, bindings.get("run_id")
    labels = (attrs.get("Config") or {}).get("Labels") or {}
    owned = {f"{LABEL}.run_id": run_id, f"{LABEL}.role": ROLE, f"{LABEL}.retention": "transient"}
    if not isinstance(run_id, str) or {key: labels.get(key) for key in owned} != owned or attrs.get(
            "Image") != steps["identity"]["python"] or steps["engine"]["classification"].get(platform) != "native":
        raise ProbeRefused("not this run's owned native Python builder container; nothing was staged or run")
    expected, hashes = binding(steps, server_inventory, platform, run_id)
    files = dict(zip(STAGED, (canonical(expected), canonical({"schema": MARKER_SCHEMA, "role": ROLE, "run_id": run_id,
                              **hashes}), Path(__file__).read_bytes(), Path(str(apt.__file__)).read_bytes())))
    if len(files["input.json"]) > INPUT_LIMIT or [_sha(files[n]) for n in (PROBE, HELPER)] != list(hashes.values())[1:]:
        raise ProbeRefused("the probe input exceeds its bound or the staged code changed")
    stage = run(["mktemp", "-d", STAGE + "XXXXXXXXXX"]).decode(errors="replace").strip()
    if not (stage.startswith(STAGE) and len(stage) == len(STAGE) + 10 and stage[len(STAGE):].isalnum()):
        raise ProbeRefused(f"unexpected private stage directory: {stage[:80]!r}")
    for name, payload in files.items():
        encoded = base64.b64encode(payload).decode()
        for start in range(0, len(encoded), CHUNK):  # each argument stays below Linux's per-argument limit
            run(["sh", "-c", 'umask 077 && printf %s "$2" | base64 -d >' + (">" if start else "") + ' "$1"', "sh",
                 f"{stage}/{name}", encoded[start:start + CHUNK]])
    if sorted(run(["find", stage, "-mindepth", "1"]).decode(errors="replace").split()) != sorted(
            f"{stage}/{name}" for name in files) or any(
            run(["cat", "--", f"{stage}/{name}"]) != payload for name, payload in files.items()):
        raise ProbeRefused("staged bytes differ on read-back; nothing was run")
    done = container.exec_run(["python3", "-I", "-B", "-c", BOOT, stage, "--internal", f"{stage}/marker.json"],
                              environment=dict(apt.APT_ENVIRONMENT), demux=True)
    stdout, stderr = done.output or (None, None)
    return verify_result(done.exit_code, stdout or b"", stderr or b"", expected, hashes)

def main(argv: Sequence[str] | None = None, native: Native | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)  # only ``--internal MARKER``; no other entry or option
    try:
        if len(arguments) != 2 or arguments[0] != "--internal":
            raise ProbeRefused("no run-bound staged marker: a host or default invocation runs nothing")
        result = run_internal(arguments[1], native or Native())
    except Exception as error:  # one bounded, redacted refusal object; never a traceback or chatter
        text = apt.bounded_tail(apt.redact(f"{type(error).__name__}: {error}", os.environ))
        result = {"schema": SCHEMA, "result": "refused", "refusal": text or type(error).__name__}
    if len(json.dumps(result, sort_keys=True)) + 1 > RESULT_LIMIT:  # ASCII JSON + newline
        result = {"schema": SCHEMA, "result": "refused", "refusal": "the result exceeds its 128 KiB bound"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "observed" else 2

if __name__ == "__main__":
    raise SystemExit(main())
