"""Pure owner for the ADR 0091 numeric libpq runtime proof component (accepted design N1-N9 and C1-C3)."""

from __future__ import annotations
import base64, contextlib, ctypes, hashlib, io, json, subprocess, sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pytest
import d12_dependency_preflight as preflight, d12_libpq_runtime_probe as runtime, native_apt_prerequisites as apt

ROOT = Path(__file__).resolve().parents[5]
PLATFORM, LIBPQ, API, RUN, LIBDIR = "linux/arm64", "18.6-1.pgdg13+2", 180006, "run-1", "/usr/lib/aarch64-linux-gnu"
LIB, STAGE = f"{LIBDIR}/libpq.so.5.18", runtime.STAGE + "a1B2c3D4e5"
SELECTED = (("libpq5", LIBPQ), ("libgssapi-krb5-2", "1.21.3-5"), ("libldap2", "2.6.10+dfsg-1"))
BASE = (("libc6", "2.41-12+deb13u2"), ("libssl3t64", "3.5.7-1~deb13u3"), ("tzdata", "2025b-4"))
LIBRARY, SYSTEM = b"\x7fELF libpq 18.6", ("linux", "aarch64", 1, 1, 0, True)
DEPENDENCIES = ["apt-mark", "auto", "libgssapi-krb5-2", "libldap2"]
TARGETS = ("Created-By: Packages\nFilename: /var/lib/apt/lists/pgdg_Packages\nTrusted: yes\n"
           "Repo-URI: http://apt.example/\nOrigin: PGDG\nSuite: trixie-pgdg\n")
DPKG_RULES = [["path-exclude", "/usr/share/doc/*"], ["path-include", "/usr/share/doc/*/copyright"],
              ["path-include", "/usr/share/doc/libpq5/README*"], ["path-exclude", "/usr/share/locale/*"]]
VERIFY = {
    "verify": (0, f"??5?????? {LIB}\n"), "verify-empty1": (1, ""), "verify-exit2": (2, "dpkg: error\n"),
    "verify-filtered": (1, "missing   /usr/share/doc/libpq5/changelog.gz\nmissing   /usr/share/locale/de/pq.mo\n"),
    "verify-include": (1, "missing   /usr/share/doc/libpq5/README.Debian\n"),
    "verify-lib": (1, f"missing   {LIBDIR}/libpq.so.5\n"),
    "verify-unfiltered": (1, "missing   /usr/share/lintian/overrides/libpq5\n"),
    "verify-sum": (1, "??5?????? /usr/share/doc/libpq5/changelog.gz\n")}

def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _deb(name: str, version: str) -> bytes: return f"archive {name} {version}".encode()

TABLE = [[n, v, "arm64", _sha(_deb(n, v))] for n, v in (*SELECTED, ("gcc", "4:14.2.0-1"), ("libpq-dev", LIBPQ))]
PRIOR = {"row ii": "", "row rc": "", "file": f"{LIBDIR[1:]}/libpq.so.5", "maps": "proc/self/maps",
         "private": "usr/local/lib/python3.12/site-packages/x.libs/libpq-0a.so.5"}
INVENTORY = {"files": [{"role": "libpq", "owner": "libpq5", "resolved": LIB, "sha256": _sha(LIBRARY)}]}

def _steps(table: list[list[str]] = TABLE, version: str = LIBPQ) -> dict[str, Any]:
    return {"builder": {"packages": [dict(zip(("name", "version", "architecture", "sha256"), r)) for r in table]},
            "libpq5_version": version, "identity": {"python": "sha256:" + "2" * 64},
            "engine": {"classification": {PLATFORM: "native"}}}

class World:
    """One owned container: a private filesystem and a recording executor answering only the helper's shapes."""
    def __init__(self, root: Path, selection=SELECTED, rows=(), case: str = "") -> None:
        self.root, self.selection, self.case, self.installed = root, selection, case, False
        self.rows = [(n, "arm64", v, "ii ") for n, v in BASE] + list(rows)
        self.commands, self.loaded, self.api = list[list[str]](), list[str](), API
        rules = "\n".join(" ".join(r) for r in DPKG_RULES + ([["path-exclude", "/usr/lib/*"]] * (case == "verify-lib")))
        for path, text in (
            ("etc/ld.so.conf", "include /etc/ld.so.conf.d/*.conf\n"), (f"{LIBDIR}/libc.so.6", "glibc"),
            ("etc/ld.so.conf.d/a.conf", f"# Multiarch\n/usr/local/lib\n/lib/aarch64-linux-gnu\n{LIBDIR}\n"),
                           ("etc/dpkg/dpkg.cfg.d/docker", rules + "\n"), (f"{LIBDIR}/libssl.so.3", "tls"),
                           ("proc/self/maps", f"aa-bb r-xp 0 00:01 1 {LIBDIR}/libc.so.6\n")):
            (file := root / path.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)
        (root / "lib").symlink_to("usr/lib")

    def run(self, command: list[str], **_options: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        return subprocess.CompletedProcess(list(command), *self.answer(list(command)), "")

    def answer(self, c: list[str]) -> tuple[int, str]:
        if tuple(c) == ("dpkg", "--verify", "libpq5"):
            return VERIFY.get(self.case, (0, ""))
        static: dict[tuple[str, ...], str] = {
            ("dpkg", "--print-architecture"): "arm64\n", ("apt-get", "update"): "",
            ("apt-get", "indextargets"): TARGETS}
        if tuple(c) in static or c[:2] == ["apt-mark", "auto"]:
            return 0, static.get(tuple(c), "")
        if c[:2] == ["dpkg-query", "-W"]:
            late = {"late-rc-pq": [("libpq5", "arm64", LIBPQ, "rc ")], "late-drift": [("x", "all", "1", "rc ")],
                    "late-rc-dep": [("libldap2", "arm64", "2.6.9+dfsg-1", "rc ")]}.get(
                self.case, []) if ["apt-get", "update"] in self.commands and not self.installed else []
            rows = self.rows + late + [(n, "arm64", v, "ii ") for n, v in self.selection if self.installed]
            dl = any("--download-only" in d for d in self.commands)
            rows += [("x", "all", "1", "ii ")] * (self.case == "drift" and dl)
            return 0, "".join(f"{n}\t{a}\t{v}\t{s}\t\t\n" for n, a, v, s in rows)
        if c[:2] == ["dpkg-query", "-L"]:
            return 0, {"libc6": f"/.\n{LIBDIR}/libc.so.6\n", "libssl3t64": f"{LIBDIR}/libssl.so.3\n"}[c[2]]
        if c[:2] == ["dpkg-query", "-S"]:
            owned = self.installed and c[2].startswith(f"{LIBDIR}/libpq.so")
            return (0, f"{'other' if self.case == 'owner' else 'libpq5'}:arm64: {c[2]}\n") if owned else (1, "")
        if c[:3] == ["apt-get", "install", "--simulate"]:
            return 0, "".join(
                f"{k} {n} ({v} PG:13/trixie-pgdg [arm64])\n" for k in ("Inst", "Conf") for n, v in self.selection)
        if c[0] == "/usr/lib/apt/apt-helper":
            return 0, "".join(f"Package: {n}\nVersion: {v}\nArchitecture: arm64\nSize: {len(_deb(n, v))}\n"
                              f"Filename: pool/{n}.deb\nSHA256: {_sha(_deb(n, v))}\n\n" for n, v in self.selection)
        if c[:2] == ["dpkg-deb", "--field"]:
            return 0, "Package: {}\nVersion: {}\nArchitecture: arm64\n".format(*Path(c[2]).name.split("_")[:2])
        if c[:2] == ["apt-get", "install"] and "--download-only" in c:
            for n, v in self.selection:
                data = b"x" if self.case == "archive" and n == "libldap2" else _deb(n, v)
                (Path(c[6].partition("=")[2]) / f"{n}_{v}_arm64.deb").write_bytes(data)
            return 0, ""
        if c[:2] != ["apt-get", "install"] or "--no-download" not in c:
            raise AssertionError(f"the guard dispatched an unexpected command: {c[:4]}")
        self.installed, lib = True, self.root / LIB.lstrip("/")  # the one offline install
        lib.write_bytes(b"other" if self.case == "bytes" else LIBRARY)
        (lib.parent / "libpq.so.5").symlink_to(lib.name)
        for path, text in (("usr/share/doc/libpq5/copyright", "PostgreSQL License\n" * (self.case != "copyright")),
                           ("opt/vendor/libpq.so.5", "copy" * (self.case == "copy")),
                           (f"{LIBDIR[1:]}/libssl.so.3", "tls" if self.case != "tls" else "changed")):
            if text:
                (file := self.root / path).parent.mkdir(parents=True, exist_ok=True)
                file.write_text(text)
        return 0, ""

    def load(self, path: str) -> object:
        self.loaded.append(path)
        extra = "dd-ee r-xp 0 00:01 3 /usr/local/lib/libpq.so.5\n" * (self.case == "maps")
        (maps := self.root / "proc/self/maps").write_text(maps.read_text() + f"bb-cc r-xp 0 00:01 2 {path}\n{extra}")
        return self.api

def _native(world: World, system: tuple[object, ...] = SYSTEM, environ: dict[str, str] | None = None,
            modules: tuple[str, str] = (f"{STAGE}/{runtime.PROBE}", f"{STAGE}/{runtime.HELPER}")) -> runtime.Native:
    return runtime.Native(str(world.root), world.run, lambda: system, world.load, lambda: modules, environ or {})

def _files(steps: dict[str, Any]) -> dict[str, bytes]:
    expected, hashes = runtime.binding(steps, INVENTORY, PLATFORM, RUN)
    return {"input.json": runtime.canonical(expected), "marker.json": runtime.canonical(
                {"schema": runtime.MARKER_SCHEMA, "role": runtime.ROLE, "run_id": RUN, **hashes}),
            runtime.PROBE: (ROOT / "tools/d12_libpq_runtime_probe.py").read_bytes(),
            runtime.HELPER: (ROOT / "tools/native_apt_prerequisites.py").read_bytes()}

def _stage(world: World, files: dict[str, bytes], mode: int = 0o700) -> None:
    (directory := world.root / STAGE.lstrip("/")).mkdir(mode=0o700, parents=True)
    [(directory / name).write_bytes(data) for name, data in files.items()]  # every staged file, then its mode
    directory.chmod(mode)

def _main(world: World, capsys, files=None, mode=0o700, **native: Any) -> tuple[int, dict[str, Any]]:
    _stage(world, files or _files(_steps()), mode)
    code = runtime.main(["--internal", f"{STAGE}/marker.json"], _native(world, **native))
    assert len((out := capsys.readouterr().out).splitlines()) == 1, f"exactly one JSON object and no chatter: {out!r}"
    return code, json.loads(out)

def _sequence(world: World) -> list[str]:
    labels = dict(zip(("update", "--simulate", "--download-only", "--no-download", "auto"), runtime.ORDER))
    return [next(labels[t] for t in c if t in labels)
            for c in world.commands if c[0] in ("apt-get", "apt-mark") and c[1] != "indextargets"]

def test_import_and_default_or_host_invocations_refuse_before_any_package_command(tmp_path):
    (empty := tmp_path / "empty-path").mkdir()
    for arguments, message in (([], "no run-bound staged marker"),
                               (["--internal", f"{STAGE}/marker.json"], "not the staged native Linux")):
        cmd = [sys.executable, "-B", str(ROOT / "tools/d12_libpq_runtime_probe.py"), *arguments]
        done = subprocess.run(cmd, cwd=tmp_path,
                              capture_output=True, text=True, check=False, env={"PATH": str(empty)}, timeout=60)
        result = json.loads(done.stdout)
        assert (done.returncode, done.stderr, len(done.stdout.splitlines())) == (2, "", 1), (arguments, done)
        assert set(result) == {"schema", "result", "refusal"} and message in result["refusal"], result
    imported = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import "
                               "d12_libpq_runtime_probe", str(ROOT / "tools")], capture_output=True, env={}, timeout=60)
    assert (imported.returncode, imported.stdout, imported.stderr) == (0, b"", b""), imported

_NOT_STAGED, _UNBOUND, _OUTSIDE = "not the staged native Linux", "marker does not bind", "outside the bounded roots"
@pytest.mark.parametrize("case, message", [
    ("system", _NOT_STAGED), ("isolated", _NOT_STAGED), ("bytecode", _NOT_STAGED),
    ("optimize", _NOT_STAGED), ("machine", "not native for the input platform"), ("modules", "loaded probe or helper"),
    ("extra", "staged directory"), ("mode", "staged directory"), ("role", _UNBOUND), ("run", _UNBOUND),
    ("probe", _UNBOUND), ("helper", _UNBOUND), ("input", "malformed or unbound probe input"),
    ("oversize", "exceeds its bound"), ("ld", "LD_PRELOAD is set"), ("preload", "preload file is not empty"),
    ("conf", _OUTSIDE), ("conf-dots", _OUTSIDE), ("conf-link", _OUTSIDE), ("conf-cap", "cycle or exceeds 64"),
    ("conf-cycle", "cycle or exceeds 64"),
    *((prior, "prior, private or unowned libpq before install") for prior in PRIOR),
])
def test_bindings_context_loader_or_prior_libpq_refuse_before_any_package_command(tmp_path, capsys, case, message):
    world, files, native = World(tmp_path / "fs"), _files(_steps()), dict[str, Any]()
    marker = json.loads(files["marker.json"])
    if case in PRIOR:  # a prior row (ii or rc), a prior or private copy, or a mapped libpq
        world.rows += [("libpq5", "arm64", LIBPQ, f"{case[-2:]} ")] if case in ("row ii", "row rc") else []
        if prior := PRIOR[case]:
            (world.root / prior).parent.mkdir(parents=True, exist_ok=True)
            (world.root / prior).write_bytes(b"aa-bb r-xp 0 00:01 1 /opt/pq/libpq.so.5\n")
    elif case in ("system", "isolated", "bytecode", "optimize", "machine"):
        native["system"] = {"system": ("darwin", *SYSTEM[1:]), "isolated": (*SYSTEM[:2], 0, *SYSTEM[3:]),
                            "bytecode": (*SYSTEM[:3], 0, *SYSTEM[4:]), "optimize": (*SYSTEM[:4], 1, True),
                            "machine": ("linux", "x86_64", *SYSTEM[2:])}[case]
    elif case == "modules":
        native["modules"] = (f"{LIBDIR}/{runtime.PROBE}", f"{STAGE}/{runtime.HELPER}")
    elif case in ("role", "run"):
        files["marker.json"] = runtime.canonical({**marker, ("role" if case == "role" else "run_id"): "other"})
    elif case in ("probe", "helper"):
        files[runtime.PROBE if case == "probe" else runtime.HELPER] += b"\n# drift\n"
    elif case == "input":
        bad_in = {**json.loads(files["input.json"]), "library": {"path": "lib/libpq.so.5"}}
        files["input.json"] = runtime.canonical(bad_in)
        files["marker.json"] = runtime.canonical({**marker, "input_sha256": _sha(files["input.json"])})
    elif case in ("oversize", "extra"):
        files["input.json" if case == "oversize" else "extra"] = b" " * (runtime.INPUT_LIMIT + 1) * (case == "oversize")
    elif case == "ld":
        native["environ"] = {"LD_PRELOAD": "/opt/x.so"}
    elif case in ("preload", "conf", "conf-dots", "conf-link", "conf-cycle"):
        if case == "conf-link":
            (world.root / "usr/lib/escape").symlink_to("../../home/app/lib")
        (world.root / ("etc/ld.so.preload" if case == "preload" else "etc/ld.so.conf.d/zz.conf")).write_text(
            {"preload": "/opt/x.so\n", "conf": "/home/app/lib\n", "conf-dots": "/usr/lib/../../home/app/lib\n",
             "conf-link": "/usr/lib/escape\n", "conf-cycle": "include /etc/ld.so.conf\n"}[case])
    elif case == "conf-cap":
        [(world.root / f"etc/ld.so.conf.d/c{i:02d}.conf").write_text(f"{LIBDIR}\n") for i in range(64)]
    code, result = _main(world, capsys, files, 0o750 if case == "mode" else 0o700, **native)
    assert (code, result["result"]) == (2, "refused") and message in result["refusal"], result
    read_only = {c[0] for c in world.commands} <= {"dpkg", "dpkg-query"} and _sequence(world) == []
    assert world.commands == [] or case in PRIOR and read_only, f"no package command before refusal: {world.commands}"

@pytest.mark.parametrize("case, message, done", [
    ("foreign", "outside the hash-bound helper contract", 2), ("missing", "does not install requested packages", 2),
    ("hash", "not an exact non-duplicate subset", 3), ("duplicate", "not an exact non-duplicate subset", 3),
    ("arch", "not an exact non-duplicate subset", 3), ("version", "expected native libpq5 version", 3),
    ("rc", "already have an ii or rc row", 3), ("late-rc-pq", "already have an ii or rc row", 3),
    ("late-rc-dep", "already have an ii or rc row", 3), ("late-drift", "drifted before installation", 3),
    ("archive", "does not match the frozen manifest", 3), ("drift", "drifted before installation", 3),
])
def test_every_bad_selection_refuses_through_the_real_helper_before_the_install(tmp_path, capsys, case, message, done):
    table, version = [list(r) for r in TABLE], "18.5-1.pgdg13+1" if case == "version" else LIBPQ
    selection = {"foreign": (*SELECTED, ("libevil", "1.0-1")), "missing": SELECTED[1:]}.get(case, SELECTED)
    if case in ("hash", "arch"):  # the same name and version with another archive hash or architecture
        table[2 if case == "hash" else 1][3 if case == "hash" else 2] = "0" * 64 if case == "hash" else "all"
    table += [list(TABLE[2])] * (case == "duplicate")
    world = World(tmp_path / "fs", selection, [("libldap2", "arm64", "2.6.9+dfsg-1", "rc ")] * (case == "rc"), case)
    code, result = _main(world, capsys, _files(_steps(table, version)))
    assert code == 2 and message in result["refusal"], result
    assert _sequence(world) == list(runtime.ORDER[:done]), f"no install or apt-mark: {world.commands}"

def test_guard_refuses_unknown_repeated_reordered_or_inexact_commands_before_dispatch(tmp_path):
    world, cache = World(tmp_path / "fs"), tmp_path / "cache"
    guard = runtime.Guard(world.run, runtime.binding(_steps(), INVENTORY, PLATFORM, RUN)[0], cache)
    guard.held = ["libc6=2.41-12+deb13u2"]
    download = ["apt-get", "install", "--yes", "--no-install-recommends", "--no-remove", "-o",
                f"Dir::Cache::Archives={cache}/", "--download-only", *guard.held, f"libpq5={LIBPQ}"]
    for command in (["apt-get", "remove", "libpq5"], ["apt-get", "install", "libpq5"], ["dpkg", "-i", "x.deb"],
                    ["sh", "-c", "true"], ["apt-mark", "auto", "libldap2"], ["dpkg-query", "-L", "libpq5"],
                    ["dpkg-deb", "--field", "/elsewhere/x.deb", "Package", "Version", "Architecture"],
                    ["/usr/lib/apt/apt-helper", "cat-file", "/etc/shadow"],
                    ["apt-get", "install", "--simulate", "--no-install-recommends", "libpq5"]):
        with pytest.raises(runtime.ProbeRefused):
            guard(command)
    assert world.commands == [], world.commands
    guard(["apt-get", "update"])
    for command in (["apt-get", "update"], download):  # a repeat, then a skipped simulation
        with pytest.raises(runtime.ProbeRefused, match="out of the exact helper sequence"):
            guard(command)
    assert world.commands == [["apt-get", "update"]], world.commands
    rows = [dict(zip(("name", "version", "architecture", "sha256"), r)) for r in TABLE[:3]]
    manifest = {"schema": apt.SCHEMA, "native_architecture": "arm64", "requested": ["libpq5"], "packages": rows}
    guard.done, guard.installed, guard.manifest = list(runtime.ORDER[:4]), True, runtime.canonical(manifest)
    with pytest.raises(runtime.ProbeRefused, match="apt-mark auto is not exactly"):
        guard(["apt-mark", "auto", "libldap2"])
    guard(DEPENDENCIES)
    assert world.commands[-1] == DEPENDENCIES and guard.done == list(runtime.ORDER), guard.done

_MISMATCH = "reports a mismatch"
@pytest.mark.parametrize("case, api, message", [
    ("", API, None), ("verify-filtered", API, None), ("bytes", API, "differ from the server library"),
    ("copy", API, "not exactly the one owned"), ("owner", API, "not all owned by libpq5"), ("verify", API, _MISMATCH),
    ("verify-include", API, _MISMATCH), ("verify-unfiltered", API, _MISMATCH),
    ("verify-sum", API, _MISMATCH), ("verify-lib", API, _MISMATCH), ("verify-empty1", API, _MISMATCH),
    ("verify-exit2", API, "failed with exit 2"), ("copyright", API, "copyright is absent"),
    ("tls", API, "TLS or glibc"),
    ("maps", API, "process maps"), ("api", True, "PQlibVersion"), ("api", 0, "PQlibVersion"),
    ("api", "180006", "PQlibVersion"),
])
def test_one_gated_offline_install_exact_apt_mark_then_verified_api_or_refusal(tmp_path, capsys, case, api, message):
    world = World(tmp_path / "fs", case=case)
    world.api = api
    code, result = _main(world, capsys)
    assert _sequence(world) == list(runtime.ORDER), world.commands
    assert [c for c in world.commands if c[0] == "apt-mark"] == [DEPENDENCIES], world.commands
    if message is not None:  # post-install custody or API drift refuses after the one install
        assert code == 2 and message in result["refusal"], result
        return
    assert (code, result["result"]) == (0, "observed"), result
    expected_verify: Any = {"status": "filtered", "rules": DPKG_RULES, "ignored": VERIFY["verify-filtered"][
        1].splitlines()} if case == "verify-filtered" else "clean"
    assert world.loaded == [LIB]
    assert (result["api"], result["maps"], result["verify"]) == (API, [LIB], expected_verify), result
    expected, hashes = runtime.binding(_steps(), INVENTORY, PLATFORM, RUN)
    good = (json.dumps(result) + "\n").encode()
    refused = json.dumps({"schema": runtime.SCHEMA, "result": "refused", "refusal": "gate"}).encode()
    record = runtime.verify_result(0, good, b"", expected, hashes)
    assert runtime.consume(record, _steps(), INVENTORY, PLATFORM) == API, record
    assert record["selected"] == [[n, v, "arm64", _sha(_deb(n, v))] for n, v in sorted(SELECTED)], record
    assert record["library"] == {"path": LIB, "sha256": _sha(LIBRARY), "package": "libpq5", "version": LIBPQ,
                                 "architecture": "arm64", "copyright_sha256": _sha(b"PostgreSQL License\n")}, record
    assert not (world.root / STAGE.lstrip("/") / "cache").exists(), "the helper removed its private cache"
    for code, stdout, stderr, expectation in (
            (0, good, b"warning\n", "chatter"), (0, b"[]", b"", "malformed or failed"), (1, good, b"", "malformed"),
            (0, good + b" " * runtime.RESULT_LIMIT, b"", "oversize"), (2, refused, b"", "refused in the"),
            (0, good + good, b"", "not exactly one JSON object")):  # the host's transport recheck
        with pytest.raises(runtime.ProbeRefused, match=expectation):
            runtime.verify_result(code, stdout, stderr, expected, hashes)

@pytest.mark.parametrize("change, message", [
    (lambda r: r.update(api=True), "not a positive int"), (lambda r: r.update(api=0), "not a positive int"),
    (lambda r: r.update(extra=1), "malformed or failed"), (lambda r: r.update(result="refused"), "differ"),
    (lambda r: r.update(input_sha256="0" * 64), "differ"), (lambda r: r.update(probe_sha256="0" * 64), "differ"),
    (lambda r: r.update(manifest_sha256="0" * 64), "differ"), (lambda r: r.update(maps=[LIB, LIB]), "differ"),
    (lambda r: r.update(verify={"status": "filtered", "rules": DPKG_RULES, "ignored": [f"missing {LIB}"]}), "differ"),
    (lambda r: r["library"].update(sha256="0" * 64), "library or native identity"),
    (lambda r: r["native"].update(machine="x86_64"), "not a positive int"),
    (lambda r: r["manifest"]["packages"][0].update(sha256="0" * 64), "not an exact non-duplicate subset"),
    (lambda r: r["manifest"]["packages"].append(r["manifest"]["packages"][0]), "not an exact non-duplicate subset"),
])
def test_host_recheck_rejects_malicious_or_inconsistent_results(tmp_path, capsys, change, message):
    result = _main(World(tmp_path / "fs"), capsys)[1]
    change(result)
    with pytest.raises(runtime.ProbeRefused, match=message):
        runtime.verify_result(0, json.dumps(result).encode(), b"", *runtime.binding(_steps(), INVENTORY, PLATFORM, RUN))

class Box:
    """The owned builder container: label/image facts, staged bytes, and one ``python3`` entry run in-process."""
    def __init__(self, world: World, **labels: str) -> None:
        owned = {"run_id": RUN, "role": runtime.ROLE, "retention": "transient", **labels}
        lbls = {f"{runtime.LABEL}.{k}": v for k, v in owned.items()}
        self.attrs = {"Image": "sha256:" + "2" * 64, "Config": {"Labels": lbls}}
        self.world, self.files, self.tamper, self.stage = world, dict[str, bytes](), False, STAGE
        self.commands = list[list[str]]()

    def exec_run(self, command, environment=None, demux=False) -> SimpleNamespace:
        c, code, output = list(command), 0, b""
        self.commands.append(c)
        if c[0] == "mktemp":
            output = self.stage.encode()
        elif c[:2] == ["sh", "-c"]:
            self.files[c[4]] = self.files.get(c[4], b"") * (">>" in c[2]) + base64.b64decode(c[5])
        elif c[0] in ("find", "cat"):
            output = self.files[c[2]] + b"x" * (self.tamper and c[2].endswith("input.json")) if c[0] == "cat" else \
                "".join(f"{path}\n" for path in sorted(self.files)).encode()
        elif c[:5] == ["python3", "-I", "-B", "-c", runtime.BOOT] and environment == apt.APT_ENVIRONMENT:
            _stage(self.world, {path.rsplit("/", 1)[1]: data for path, data in self.files.items()})
            with contextlib.redirect_stdout(stdout := io.StringIO()):
                code = runtime.main(c[6:], _native(self.world))
            output = stdout.getvalue().encode()
        else:
            raise AssertionError(f"unexpected builder exec {c[:3]}")
        return SimpleNamespace(exit_code=code, output=(output, b""))

@pytest.mark.parametrize("change, message", [
    (None, None), ("chunk", None), ({"run_id": "run-2"}, "owned native Python builder"),
    ({"role": "d12-explore-final"}, "owned native Python builder"), ("image", "owned native Python builder"),
    ({"retention": "retained"}, "owned native Python builder"), ("emulated", "owned native Python builder"),
    ("tamper", "differ on read-back"), ("mktemp", "private stage"),
])
def test_host_driver_checks_ownership_stages_reads_back_runs_once_and_rechecks(tmp_path, monkeypatch, change, message):
    box, steps = Box(World(tmp_path / "fs"), **(change if isinstance(change, dict) else {})), _steps()
    box.tamper, box.stage = change == "tamper", "/var/tmp/x\n" if change == "mktemp" else box.stage
    box.attrs["Image"] = "sha256:" + ("9" if change == "image" else "2") * 64
    steps["engine"]["classification"][PLATFORM] = "emulated" if change == "emulated" else "native"
    monkeypatch.setattr(runtime, "CHUNK", 8 if change == "chunk" else runtime.CHUNK)  # whole base64 groups
    if message is not None:  # a foreign container or staging drift refuses before the probe runs
        with pytest.raises(runtime.ProbeRefused, match=message):
            runtime.observe(box, steps, INVENTORY, PLATFORM, {"run_id": RUN})
        assert "python3" not in [c[0] for c in box.commands], box.commands
        return
    record = runtime.observe(box, steps, INVENTORY, PLATFORM, {"run_id": RUN})
    assert record["api"] == API and runtime.consume(record, _steps(), INVENTORY, PLATFORM) == API, record
    kinds = [c[0] for c in box.commands]
    assert kinds[0] == "mktemp" and kinds[-1] == "python3" and kinds.count("python3") == 1, kinds
    assert kinds.index("find") < kinds.index("cat") and kinds.count("cat") == 4
    assert (kinds.count("sh") > 4) == (change == "chunk"), kinds

def test_pq_lib_version_loads_the_absolute_path_and_sets_the_exact_c_signature(monkeypatch):
    def function() -> int:  # a foreign function stand-in: settable signature attributes and a call
        return 7
    loaded: dict[str, SimpleNamespace] = {}
    monkeypatch.setattr(ctypes, "CDLL", lambda path: loaded.setdefault(path, SimpleNamespace(PQlibVersion=function)))
    assert runtime.pq_lib_version(LIB) == 7 and list(loaded) == [LIB], loaded
    assert (getattr(function, "argtypes"), getattr(function, "restype")) == ([], ctypes.c_int), vars(function)

@pytest.mark.parametrize("case, message", [
    ("none", "no verified runtime libpq observation"), ("empty", "no verified runtime libpq observation"),
    ("verified", "not bound to these inputs"), ("forecast", "differs from the package forecast"),
    ("api", "not a positive int"), ("table", "not an exact non-duplicate subset"),
    ("input", "not bound to these inputs"),
])
def test_candidate_refuses_a_missing_or_unbound_observation_and_never_falls_back(case, message):
    def record(api: object = API, selected: Any = None) -> dict[str, Any]:  # a host-verified record of these inputs
        expected, hashes = runtime.binding(_steps(), INVENTORY, PLATFORM, RUN)
        rows = selected or [row for row in expected["table"] if row[0] in dict(SELECTED)]
        return runtime.record(expected, hashes, api=api, machine="aarch64", selected=rows, digests=("5" * 64, "6" * 64))
    source, keyring = "/etc/apt/sources.list.d/pgdg.list", "/usr/local/share/keyrings/postgres.gpg.asc"
    trust = {"pgdg_source": source, "sources": {source: {"sha256": "2" * 64}}, "pgdg_keyring": keyring,
             "keyrings": {keyring: "3" * 64}, "fingerprints": {"primary": ["B97B0AFC" * 5]}}
    steps, positive = (
        {**_steps(), "final_closure": {"packages": []}, "identity": {"postgres": "sha256:" + "1" * 64},
         "closure": {"imports": ["_ssl"]}, "trust": trust} for _ in range(2))
    positive["libpq_runtime"] = record()
    preflight.candidate(positive, PLATFORM, INVENTORY)  # the control: the same inputs with a bound observation
    assert positive["candidate"]["valid"] and positive["candidate"]["libpq_version"] == API, positive["candidate"]
    bad_args = {"forecast": (170006,), "api": (True,), "table": (API, [["libpq5", LIBPQ, "arm64", "0" * 64]])}
    bad = record(*bad_args.get(case, ()))
    overrides = {"none": None, "empty": {}, "verified": {**bad, "verified": "container said so"},
                 "input": {**bad, "input_sha256": "0" * 64}}
    steps["libpq_runtime"] = overrides.get(case, bad)
    with pytest.raises(preflight.PreflightRefusal, match="candidate manifest refused") as refused:
        preflight.candidate(steps, PLATFORM, INVENTORY)
    assert message in str(refused.value) and "valid" not in steps["candidate"], steps["candidate"]
    assert steps["candidate"]["package_forecast"] == API and steps["candidate"]["libpq_version"] is None, steps
