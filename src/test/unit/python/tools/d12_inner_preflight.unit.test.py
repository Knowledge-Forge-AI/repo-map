"""Pure owner for the ADR 0089 D9 E1 non-consuming inner-daemon exploration.

No Docker, APT, network or ledger: the SDK, containers, exec results and every
ledger entry point are injected doubles, and ``build_candidate`` is a trap.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from ci.python_retention_operations import dynamic_operations
import d12_dependency_preflight as preflight
import d12_libpq_runtime_probe as runtime
import native_apt_prerequisites as apt
from common_lore_index.runtime import python_payload as payload
from common_lore_index.runtime.release import GO_RELEASE_IMAGE as GO, POSTGRES_RELEASE_IMAGE as PG, PYTHON_RELEASE_IMAGE as PY
from repomap_test_support import d12_core_image as d12
import runner_arguments
import test_sandbox

ROOT = Path(__file__).resolve().parents[5]
OWNER = ROOT / d12.NODE_FILE
SOURCE, LIBPQ, KEY = "a" * 64, "17.6-1.pgdg120+1", "/usr/local/share/keyrings/postgres.gpg.asc"
IDENTITY: dict[str, Any] = {"source_sha256": SOURCE, "recipe_sha256": "b" * 64, "dockerfile_sha256": "c" * 64,
                            "context_file_count": 3}
FLAG, PROFILE = ["--d12-core-image-preflight"], ["--d12-core-image-profile", "linux/arm64"]
GO_ARM64 = "sha256:347d64c45df620f4ec8dfe652b4039b0fabb614f4238f6248ac33a56df3caf2d"  # ADR 0090 D1 sealed config
GO_AMD64 = "sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe"
COUNTS = ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
          "unmanaged_build_count", "unmanaged_pull_count")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(d12, "_ADMISSION", None)
    monkeypatch.setattr(preflight, "_EXPLORATION", None, raising=False)  # absent on entry: red is behavioral
    monkeypatch.setattr(d12, "frozen_identity", lambda root, platform: dict(IDENTITY))
    for name in (d12.ENV_PROFILE, d12.ENV_REPORT_DIR):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def trap(tmp_path, monkeypatch):
    """Every ledger, host preflight and build entry point raises; any filesystem touch of the sentinel ledger is
    recorded and raises, so a passing case proves no access at all, not merely unchanged bytes."""
    touched: list[str] = []

    def forbid(name: str):
        def refuse(*_args: Any, **_kwargs: Any):
            raise AssertionError(f"forbidden call: {name}")
        return refuse

    def guard(function):
        def checked(path, *args, **kwargs):
            if not isinstance(path, int) and "ledger-sentinel" in os.fsdecode(path):
                touched.append(os.fsdecode(path))
                raise AssertionError("ledger accessed")
            return function(path, *args, **kwargs)
        return checked

    def observed(box, steps, inventory, platform, bindings):  # the numeric component's injected result (own owner)
        expected, hashes = runtime.binding(steps, inventory, platform, str(bindings["run_id"]))
        return box.world.numeric or runtime.record(expected, hashes, api=170006, machine="aarch64", selected=[
            row for row in expected["table"] if row[0] == "libpq5"], digests=("5" * 64, "6" * 64))

    for module, name in ((os, "open"), (os, "stat"), (os, "lstat"), (io, "open")):
        monkeypatch.setattr(module, name, guard(getattr(module, name)))
    monkeypatch.setattr(runtime, "observe", observed)
    monkeypatch.setattr(d12, "record_budget", forbid("record_budget"))
    monkeypatch.setattr(d12, "admit_profile", forbid("admit_profile"))
    monkeypatch.setattr(d12, "build_candidate", forbid("build_candidate"))
    monkeypatch.setattr(preflight, "preflight", forbid("host preflight"))
    return SimpleNamespace(ledger=tmp_path / "ledger-sentinel" / "BUILD-BUDGET.json", touched=touched)


def _args(tmp_path: Path, *extra: str, report: Path | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    runner_arguments.add_runner_arguments(parser, hygiene_profiles=(), parse_jobs=runner_arguments.parse_jobs,
                                          default_report_root=ROOT / ".test-reports")
    return parser.parse_args(["--suite", "int", "--no-coverage", "--report-dir", str(report or tmp_path / "report"),
                              "--d12-core-image-source-sha256", SOURCE, *extra])


def _route(monkeypatch, args, forwarded=(d12.NODE_ID,), inside=False):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: inside)
    return runner_arguments.validate_pgvector_forwarded_selections(args, list(forwarded), repo_root=ROOT)


@pytest.mark.parametrize("inside", [False, True])
@pytest.mark.parametrize("extra, message", [
    ([*FLAG, *PROFILE, "--d12-core-image-budget-ledger", "L"], "refuses --d12-core-image-budget-ledger"),
    ([*FLAG, "--d12-core-image-budget-ledger", "L"], "refuses --d12-core-image-budget-ledger"),
    (FLAG, "requires --d12-core-image-profile"),  # the flag without a profile refuses even when platform is None
])
def test_exploration_refuses_a_ledger_or_missing_profile_before_any_access(tmp_path, monkeypatch, trap, inside,
                                                                           extra, message):
    args = _args(tmp_path, *[str(trap.ledger) if item == "L" else item for item in extra])
    with pytest.raises(d12.D12ProfileError, match=message):
        _route(monkeypatch, args, inside=inside)
    assert trap.touched == [] and d12._ADMISSION is None and preflight.current_exploration() is None


@pytest.mark.parametrize("extra, forwarded, ambient, message", [
    ([], [d12.NODE_ID, "-x"], False, "exactly the one named node"),
    ([], [d12.NODE_ID, "src/test/int/python/other.int.test.py::t"], False, "exactly the one named node"),
    ([], [], False, "exactly the one named node"),
    ([], [d12.NODE_ID], True, "ambient environment"),
    (["--jobs", "2"], [d12.NODE_ID], False, "--jobs 1"),
    (["--d12-core-image-source-sha256", "d" * 64], [d12.NODE_ID], False, "stale source"),
    (["--report-dir", str(ROOT / ".test-reports")], [d12.NODE_ID], False, "explicit unused --report-dir"),
    (["stale"], [d12.NODE_ID], False, "stale report directory"),
])
def test_exploration_reuses_exact_selection_and_refuses_ambient_or_stale_inputs(tmp_path, monkeypatch, trap, extra,
                                                                               forwarded, ambient, message):
    if extra == ["stale"]:
        extra = []
        (tmp_path / "report").mkdir()
    if ambient:
        monkeypatch.setenv(d12.ENV_PROFILE, "linux/arm64")
    with pytest.raises(d12.D12ProfileError, match=message):
        _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE, *extra), forwarded)
    assert trap.touched == [] and d12._ADMISSION is None


def test_host_exploration_skips_preflight_admission_and_ledger_while_build_mode_still_refuses(tmp_path, monkeypatch,
                                                                                            trap):
    assert _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE)) is None
    assert d12._ADMISSION is None and preflight.current_exploration() is None and trap.touched == []
    assert not (tmp_path / "report").exists(), "the host writes no report and keeps the destination unused"
    with pytest.raises(AssertionError, match="forbidden call: host preflight"):  # build mode is unchanged
        _route(monkeypatch, _args(tmp_path, *PROFILE, "--d12-core-image-budget-ledger", str(tmp_path / "x.json")))


def test_sandbox_exploration_keeps_build_admission_empty(tmp_path, monkeypatch, trap):
    # Corrected R14 test (parent B1/DI-1): the shared slot is rejected. Setup gate and transitions:
    # d12_exploration_admission.unit.test.py.
    _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE), inside=True)
    admitted = preflight.current_exploration()
    assert admitted is not None and d12._ADMISSION is None, admitted
    assert (admitted.platform, admitted.node_id, admitted.source_sha256) == ("linux/arm64", d12.NODE_ID, SOURCE)
    with pytest.raises(d12.D12ProfileError, match="no runner admission"):
        d12.current_admission()
    with pytest.raises(d12.D12ProfileError, match="mixed build and exploration"):
        _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE), inside=True)
    monkeypatch.setattr(preflight, "_EXPLORATION", None)
    monkeypatch.setattr(d12, "_ADMISSION", d12.D12Admission(platform="linux/arm64", node_id=d12.NODE_ID, **IDENTITY))
    with pytest.raises(d12.D12ProfileError, match="mixed build and exploration"):
        _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE), inside=True)
    assert preflight.current_exploration() is None and trap.touched == []


def _owner_test() -> ast.FunctionDef:
    tree = ast.parse(OWNER.read_bytes())
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == d12.NODE_ID.rsplit("::", 1)[1])


def test_owner_imports_the_support_lazily_through_the_canonical_tools_path_only():
    # One module object: the runner's import fills this module's exploration slot, which the root setup gate reads.
    assert Path(str(preflight.__file__)).resolve() == ROOT / "tools/d12_dependency_preflight.py"
    owner_tree, support_tree = ast.parse(OWNER.read_bytes()), ast.parse(Path(str(preflight.__file__)).read_bytes())
    top = {a.name for n in owner_tree.body if isinstance(n, ast.Import) for a in n.names}
    top |= {str(n.module) for n in owner_tree.body if isinstance(n, ast.ImportFrom)}
    assert not {name for name in top if "preflight" in name or name.startswith("tools")}, top
    assert ast.unparse(_owner_test().body[0]) == "import d12_dependency_preflight as inner"
    imported = {a.name for n in ast.walk(support_tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {str(n.module) for n in ast.walk(support_tree) if isinstance(n, ast.ImportFrom)}
    allowed = {
        "d12_libpq_runtime_probe", "d12_native_python_observer", "d12_python_closure", "native_apt_prerequisites",
        "common_lore_index.runtime.release", "repomap_test_support", "repomap_test_support.d12_core_image", "__future__"}
    assert {name for name in imported if name.split(".")[0] not in sys.stdlib_module_names} <= allowed, imported
    assert "sys.path" not in ast.unparse(support_tree) and "sys.path" not in OWNER.read_text(encoding="utf-8")
    assert dynamic_operations(owner_tree) == [] and dynamic_operations(support_tree) == []
    for root in ("src/main/python", "src/test/support/python"):  # product and test support never import tools
        assert not [p for p in (ROOT / root).rglob("*.py") if "d12_dependency_preflight" in p.read_text()], root

def _calls(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Call) and ast.unparse(n.func) == name for n in ast.walk(node))

def _exploration_branch(statements: list[ast.stmt]) -> int:
    return next(i for i, n in enumerate(statements)
                if isinstance(n, ast.If) and ast.unparse(n.test) == "exploration is not None")

def test_owner_returns_inside_try_immediately_before_the_build_and_custody_requires_zero_builds():
    body = next(n for n in _owner_test().body if isinstance(n, ast.Try))
    branch = body.body[index := _exploration_branch(body.body)]
    assert isinstance(branch, ast.If) and _calls(branch, "inner.explore"), ast.unparse(branch)
    assert isinstance(branch.body[-1], ast.Return), "exploration returns inside the try, so custody still runs"
    assert _calls(body.body[index + 1], "d12.build_candidate"), "the exploration return must precede the build"
    assert not any(_calls(n, "d12.build_candidate") for n in body.body[:index])
    custody = next(n for n in ast.walk(ast.Module(body=body.finalbody, type_ignores=[]))
                   if isinstance(n, ast.FunctionDef) and n.name == "custody")
    exit_branch = custody.body[guard := _exploration_branch(custody.body)]
    assert isinstance(exit_branch, ast.If) and _calls(exit_branch, "inner.require_zero_builds")
    assert isinstance(exit_branch.body[-1], ast.Return), ast.unparse(exit_branch)
    assert "counts" in ast.unparse(custody.body[guard + 1]), "the build-mode count assertion follows unchanged"
    assert "assert counts[1:] == [0, 0, 0] and counts[0] <= 1 and (primary is not None or counts[0] == 1), budget" \
        in OWNER.read_text(encoding="utf-8")


@pytest.mark.parametrize("field", COUNTS)
def test_exploration_custody_refuses_any_build_or_pull_count(field):
    zero = dict.fromkeys(COUNTS, 0)
    assert preflight.COUNTS == COUNTS and preflight.GO_CONFIGS == {"linux/amd64": GO_AMD64, "linux/arm64": GO_ARM64}
    assert preflight.require_zero_builds(zero) == zero
    with pytest.raises(preflight.PreflightRefusal, match="not all zero"):
        preflight.require_zero_builds({**zero, field: 1})


BUILDX = "Name: default\nDriver: docker\n\nNodes:\nStatus: running\nBuildKit version: v0.26.0\nPlatforms: {}\n"
BASES: dict[str, dict[str, Any]] = {PG: {"id": "sha256:" + "1" * 64, "config_digest_verified": True},
                                    PY: {"id": "sha256:" + "2" * 64}, GO: {"id": GO_ARM64}}

@pytest.mark.parametrize("platform, arch, offered, bases, classes, message", [
    ("linux/arm64", "aarch64", "linux/arm64, linux/amd64", BASES, ("native", "emulated"), None),
    ("linux/amd64", "x86_64", "linux/amd64, linux/arm64",
     {**BASES, GO: {"id": GO_AMD64}}, ("emulated", "native"), None),
    ("linux/arm64", "aarch64", "linux/arm64", BASES, ("native", "non_executable"), None),
    ("linux/arm64", "x86_64", "linux/arm64", BASES, ("emulated", "native"), "E1 explores native only"),
    ("linux/arm64", "aarch64", None, BASES, None, "no BuildKit"),
    ("linux/arm64", "aarch64", "linux/arm64",
     {**BASES, GO: {"id": "sha256:" + "9" * 64}}, None, "unknown base identity"),
    ("linux/amd64", "x86_64", "linux/amd64", BASES, None, "unknown base identity"),
    ("linux/arm64", "aarch64", "linux/arm64",
     {**BASES, PG: {"id": "sha256:" + "1" * 64}}, None, "unknown base identity"),
])
def test_engine_labels_native_emulated_or_non_executable_and_refuses_unknown_facts(platform, arch, offered, bases,
                                                                                   classes, message):
    text = BUILDX.format(offered) if offered else "Driver: docker\nPlatforms: linux/arm64\n"
    client = SimpleNamespace(info=lambda: {"Architecture": arch}, version=lambda: {"Version": "29"})
    steps: dict[str, Any] = {}
    admission = d12.D12Admission(platform=platform, node_id=d12.NODE_ID, **IDENTITY)
    with pytest.raises(preflight.PreflightRefusal, match=message) if message else nullcontext():
        preflight.engine_facts(steps, client, admission, subprocess.CompletedProcess([], 0, text), bases)
    if classes: assert tuple(steps["engine"]["classification"].values()) == classes, steps
    with pytest.raises(preflight.PreflightRefusal, match="buildx inspect failed"):
        preflight.engine_facts({}, client, admission, subprocess.CompletedProcess([], 1, text), bases)


PLAN = {PY: [("gcc", "12.2.0-14"), ("binutils", "2.40-2"), ("libc6-dev", "2.36-9"), ("libpq-dev", LIBPQ),
             ("libpq5", LIBPQ), ("libssl-dev", "3.5.7-1~deb13u3")], PG: [("libffi8", "3.4.4-1")]}
ROWS = {PG: [("libc6", "2.36-9"), ("libpq5", LIBPQ), ("tzdata", "2025b")],
        PY: [("libc6", "2.36-9"), ("libffi8", "3.4.4-1"), ("libssl3t64", "3.5.7-1~deb13u3")]}
FPR, SUB = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8", "0" * 39 + "1"
LDD = ("\tlinux-vdso.so.1 (0x1)\n\tlibffi.so.8 => /lib/aarch64-linux-gnu/libffi.so.8 (0x2)\n"
       "\tlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x3)\n\t/lib/ld-linux-aarch64.so.1 (0x4)\n")
# Reverse usrmerge: ldd prints /lib paths while dpkg owns only the resolved /usr/lib file.
REAL = {"/lib/aarch64-linux-gnu/libffi.so.8": "/usr/lib/aarch64-linux-gnu/libffi.so.8.1.2",
        "/lib/aarch64-linux-gnu/libc.so.6": "/usr/lib/aarch64-linux-gnu/libc.so.6",
        "/lib/ld-linux-aarch64.so.1": "/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1"}
OWNERS = dict(zip(REAL.values(), ("libffi8", "libc6", "libc6")))


def _closure(extra: str = "") -> str:  # the payload contract's clean report: no exclusion for this Python config
    elves = {p: {"sha256": "1" * 64, "size": 1, "elf": [2, 1, 183], "ldd": t, "ldd_exit": 0} for p, t in (
        ("/usr/local/bin/python3.12", LDD), ("/usr/local/lib/libpython3.so", "\tstatically linked"))}
    base = {"machine": "aarch64", "entries": 2, "digest": "0" * 64, "elves": elves, "dynload_real": payload.DYNLOAD,
            "dynload": [[f"{m}.cpython-312-aarch64-linux-gnu.so", "file"] for m in ("_ctypes", "_ssl")],
            "imports": ["_ctypes", "_ssl"], "failed": {}, "targets": {p: [r, "a" * 64] for p, r in REAL.items()}}
    files = {path: ["file", "1" * 64, 1, 33188] for path in elves}
    retained = payload.verify_retained(files, files, base, None, dict.fromkeys(REAL, "libc6"))
    elves["/usr/local/bin/python3.12"]["ldd"] = LDD + extra  # a raw finding the container did not report
    return json.dumps({"schema": payload.SCHEMA, "architecture": "arm64", "result": "clean", "reasons": [],
                       "baseline": base, "exclusion": None, "retained": retained})


class World:
    def __init__(self) -> None:
        sources = {"/etc/apt/sources.list.d/debian.sources": b"Suites: x\nSigned-By: /usr/share/keyrings/d.gpg\n"}
        pgdg = {"/etc/apt/sources.list.d/pgdg.list": f"deb [ signed-by={KEY} ] http://a/ x-pgdg main\n".encode()}
        self.files = {PG: {**sources, **pgdg, KEY: b"armored", "/usr/share/keyrings/d.gpg": b"debian"},
                      PY: {**sources, "/usr/share/keyrings/d.gpg": b"debian"}}
        self.keys = (0, f"pub:-:4096:1:X:\nfpr:::::::::{FPR}:\nuid:-::::\nsub:-:4096:1:Y:\nfpr:::::::::{SUB}:\n")
        self.closure, self.update, self.corrupt, self.trusted, self.remove = (0, _closure()), (0, ""), False, "yes", ""
        self.created, self.cleaned, self.environments = list[tuple[str, str, str]](), list[str](), set[str]()
        self.numeric: object = None  # a non-record numeric result for the no-fallback refusal case

    def create(self, owner, client, image, command, **options):
        assert command == ["infinity"] and options["entrypoint"] == ["sleep"] and options["environment"] == {}
        self.created.append((options["role"], image, options["network_mode"]))
        return f"c{len(self.created)}", Box(self, image)

    def answer(self, box, command: list[str]) -> tuple[int, str | bytes]:
        joined = " ".join(command[:3])
        if command[0] == "cat":
            return (0, box.files[command[2]]) if command[2] in box.files else (1, b"")
        if command[0] == "find":
            return 0, "\n".join(path for path in box.files if "/sources.list" in path)
        if command[:3] == ["sh", "-c", preflight.KEYS_SH]:
            return self.keys
        if command[:2] == ["sh", "-c"]:
            box.files[command[4]] = b"tampered" if self.corrupt else base64.b64decode(command[5])
            return 0, ""
        if command[0] == "python3":
            return self.closure
        if joined.startswith("dpkg-query -W"):
            return 0, "".join(f"{name}\tarm64\t{version}\tii \t\t\n" for name, version in ROWS[box.image])
        if joined.startswith("dpkg-query -S"):
            return (0, f"{OWNERS[command[2]]}:arm64: {command[2]}\n") if command[2] in OWNERS else (1, "")
        if joined in (fixed := {"apt-get update": self.update, "dpkg --print-architecture": (0, "arm64\n")}):
            return fixed[joined]
        if command[:3] == ["apt-get", "install", "--simulate"]:
            assert "libc6=2.36-9" in command and ("libssl-dev=3.5.7-1~deb13u3" in command) == (box.image == PY)
            lines = [f"{kind} {n} ({v} Example:12 [arm64])" for kind in ("Inst", "Conf") for n, v in PLAN[box.image]]
            return 0, self.remove + "\n".join(lines) + "\n"
        if command == ["apt-get", "indextargets"]:
            return 0, (f"Created-By: Packages\nFilename: /l/P\nTrusted: {self.trusted}\nRepo-URI: http://deb.example/\n"
                       "Origin: Example\nSuite: bookworm\n")
        if command[0] == "/usr/lib/apt/apt-helper":
            return 0, "".join(f"Package: {n}\nVersion: {v}\nArchitecture: arm64\nSize: 10\nFilename: pool/{n}.deb\n"
                              f"SHA256: {hashlib.sha256(n.encode()).hexdigest()}\n\n" for n, v in PLAN[PY] + PLAN[PG])
        raise AssertionError(f"unexpected exec {command[:4]}")


class Box:
    def __init__(self, world: World, image: str) -> None:
        self.world, self.image, self.files = world, image, dict(world.files[image])

    def start(self) -> None: pass

    def exec_run(self, command, environment=None, demux=False):
        self.world.environments.add(json.dumps(environment))
        code, output = self.world.answer(self, list(command))
        return SimpleNamespace(exit_code=code, output=(output if isinstance(output, bytes) else output.encode(), b""))


def _explore(world: World, bases=BASES, packages=(("libpq5", LIBPQ, "arm64"),)):
    reports: list[tuple[str, dict[str, Any]]] = []
    libpq = {"role": "libpq", "resolved": "/usr/lib/a/libpq.so.5.17", "sha256": "e" * 64, "owner": "libpq5"}
    client = SimpleNamespace(info=lambda: {"Architecture": "aarch64"}, version=lambda: {"Version": "29"})
    admission = d12.D12Admission(platform="linux/arm64", node_id=d12.NODE_ID, **IDENTITY)
    try:
        return preflight.explore(
            SimpleNamespace(cleanup=world.cleaned.append), client, admission, bases=bases, availability={},
            inspected=subprocess.CompletedProcess([], 0, BUILDX.format("linux/arm64, linux/amd64")),
            server_inventory={"packages": [list(row) for row in packages], "files": [libpq]}, create=world.create,
            bindings={"run_id": "run-1"}, statvfs=lambda path: SimpleNamespace(f_bavail=2, f_frsize=4096),
            write_report=lambda name, payload: reports.append((name, json.loads(json.dumps(payload, default=str))))
        ), reports
    finally:
        assert [f"c{i}" for i in range(1, len(world.created) + 1)] == world.cleaned, "every owned container is removed"
        assert len(reports) == 1 and reports[0][0] == "exploration", reports


def test_exploration_observes_resolves_and_validates_a_candidate_without_building(trap):
    world = World()
    report, [(_name, saved)] = _explore(world)
    assert world.created == [("d12-explore-trust", PG, "none"), ("d12-explore-closure", PY, "none"),
                             ("d12-explore-builder", PY, "bridge"), ("d12-explore-final", PG, "bridge")]
    assert world.environments <= {json.dumps(apt.APT_ENVIRONMENT), "null"}, world.environments
    labels = {key: saved[key] for key in preflight.LABELS}
    assert labels == preflight.LABELS and saved["result"] == "observed" and saved["refusals"] == []
    assert saved["admission"]["source_sha256"] == SOURCE and saved["bindings"] == {"run_id": "run-1"}
    assert saved["bases"][PG]["id"] == BASES[PG]["id"] and saved["steps"]["capacity"]["free_bytes"] == 8192
    steps = saved["steps"]
    assert steps["trust"]["fingerprints"] == {"primary": [FPR], "subkeys": [SUB]}
    assert steps["closure"]["packages"] == [["libc6", "2.36-9", "arm64"], ["libffi8", "3.4.4-1", "arm64"]]
    assert [p["name"] for p in steps["final_closure"]["packages"]] == ["libffi8"], "only missing closure is added"
    candidate = steps["candidate"]
    assert candidate["valid"] and not candidate["written_to_source"] and candidate["libpq_version"] == 170006
    assert steps.get("libpq_runtime", {}).get("api") == candidate.get("package_forecast") == 170006, candidate
    assert candidate["manifest"]["libpq5_version"] == LIBPQ and report is not None and trap.touched == []


@pytest.mark.parametrize("change, message, created", [
    (lambda w: setattr(w, "keys", (127, "")), "no existing key-listing tool", 2),
    (lambda w: setattr(w, "keys", (2, "")), "key-listing tool exited 2", 2),
    (lambda w: setattr(w, "update", (100, "E: Failed to fetch")), "apt-get update failed with exit 100", 3),
    (lambda w: setattr(w, "corrupt", True), "PGDG trust bytes differ", 3),
    (lambda w: setattr(w, "trusted", "no"), "index trust is unknown", 3),
    (lambda w: setattr(w, "remove", "Remv tzdata [2025b]\n"), "removes an installed package", 3),
    (lambda w: setattr(w, "closure", (0, "not json")), "malformed closure observation", 2),
    (lambda w: setattr(w, "closure", (0, _closure("\tlibx.so.1 => not found\n"))), "unresolved", 2),
    (lambda w: setattr(w, "numeric", {"api": 170006}), "no verified runtime libpq observation", 4),  # no fallback
    ("bases", "unknown base identity", 0),
    ("libpq", "no single libpq5 version", 2),
])
def test_refusals_save_a_partial_report_clean_up_and_never_build(trap, change, message, created):
    world, packages = World(), () if change == "libpq" else (("libpq5", LIBPQ, "arm64"),)
    bases = {**BASES, GO: {"id": "sha256:" + "9" * 64}} if change == "bases" else BASES
    if callable(change): change(world)
    with pytest.raises(preflight.PreflightRefusal, match=message) as refused:
        _explore(world, bases, packages)
    assert "nothing built or consumed" in str(refused.value) and len(world.created) == created, world.created
    if created >= 2:
        assert world.created[1][1] == PY, "trust and closure facts are both kept before any resolution stops"
    assert trap.touched == []
