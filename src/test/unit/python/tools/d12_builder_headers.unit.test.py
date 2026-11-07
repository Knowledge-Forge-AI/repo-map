"""Pure owner for the exact matching ``libssl-dev`` selectors (ADR 0089 E2, rebound to Trixie by ADR 0091): E-g
builder resolution and the managed test-runtime install program.

No Docker, APT or network: a recording container double answers the exact argv. The doubles prove argv, refusal
order and manifest flow only, never APT resolution, signatures or current repository contents.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import d12_dependency_preflight as preflight
import d12_libpq_runtime_probe as runtime
import native_apt_prerequisites as apt
from common_lore_index.runtime.release import DebPackage
from repomap_test_support import resource_test_image_commands as commands

SSL, LIBPQ = "3.5.7-1~deb13u3", "18.6-1.pgdg12+2"
DEV = "libssl-dev=3.5.7-1~deb13u3"
REQUEST = ("gcc", "binutils", "libc6-dev", f"libpq-dev={LIBPQ}", f"libpq5={LIBPQ}")
SIMULATE = ["apt-get", "install", "--simulate"]
BASE = (("libc6", "arm64", "2.36-9+deb12u14", "ii "), ("libssl3t64", "arm64", SSL, "ii "),
        ("openssl", "arm64", SSL, "ii "), ("tzdata", "all", "2026b-0+deb12u1", "ii "))
PLAN = (("gcc", "12.2.0-14"), ("binutils", "2.40-2"), ("libc6-dev", "2.36-9+deb12u14"), ("libpq-dev", LIBPQ),
        ("libpq5", LIBPQ), ("libssl-dev", SSL))
TARGET = "Created-By: Packages\nFilename: /l/P\nTrusted: yes\nRepo-URI: http://deb.example/\nOrigin: Debian\n" \
         "Suite: bookworm\n"


def _sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


class Box:
    """One owned container: every exec is recorded and answered from the fixed rows, plan and index."""

    def __init__(self, rows=BASE, plan=PLAN, simulate: int = 0) -> None:
        self.rows, self.plan, self.simulate = rows, plan, simulate
        self.commands: list[list[str]] = []

    def exec_run(self, command, environment=None, demux=False):
        self.commands.append(list(command))
        code, output = self.answer(list(command))
        return SimpleNamespace(exit_code=code, output=(output.encode(), b""))

    def answer(self, command: list[str]) -> tuple[int, str]:
        if command[:2] == ["dpkg-query", "-W"]:
            return 0, "".join(f"{name}\t{arch}\t{version}\t{status}\t\t\n" for name, arch, version, status in self.rows)
        if command == ["apt-get", "update"]:
            return 0, ""
        if command == ["dpkg", "--print-architecture"]:
            return 0, "arm64\n"
        if command[:3] == SIMULATE and DEV not in command and "libssl-dev" in dict(self.plan):  # E2's actual refusal
            return 100, f"libssl-dev : Depends: libssl3 (= 3.0.22-1~deb12u1) but {SSL} is to be installed\n"
        if command[:3] == SIMULATE:
            lines = [f"{kind} {n} ({v} Debian:12/stable [arm64])" for kind in ("Inst", "Conf") for n, v in self.plan]
            return self.simulate, "\n".join(lines) + "\n"
        if command == ["apt-get", "indextargets"]:
            return 0, TARGET
        if command[0] == "/usr/lib/apt/apt-helper":
            return 0, "".join(f"Package: {n}\nVersion: {v}\nArchitecture: arm64\nSize: 10\nFilename: pool/{n}.deb\n"
                              f"SHA256: {_sha(n)}\n\n" for n, v in PLAN)
        raise AssertionError(f"unexpected exec {command[:4]}")


def _before(rows=BASE) -> dict[str, dict[str, str]]:
    return apt.installed_packages(preflight.exec_runner(Box(rows)))


def _simulations(box: Box) -> list[list[str]]:
    return [command for command in box.commands if command[:3] == SIMULATE]


def _without_runtime(*extra: tuple[str, str, str, str]) -> tuple[tuple[str, str, str, str], ...]:
    return (*(row for row in BASE if row[0] != "libssl3t64"), *extra)


def test_exact_native_runtime_appends_one_matching_header_without_mutating_the_request():
    request = list(REQUEST)
    augmented = preflight.builder_request(request, _before(), "arm64")
    assert augmented == [*REQUEST, DEV] and augmented is not request and request == list(REQUEST)
    assert [item for item in augmented if item.partition("=")[0] == "libssl-dev"] == [DEV]
    assert preflight.builder_request(REQUEST, _before(), "arm64") == [*REQUEST, DEV], "a tuple request is copied"


def test_other_callers_and_missing_only_never_gain_or_check_a_header():
    closure = [f"libpq5={LIBPQ}", "libffi8=3.4.4-1"]
    for before in (_before(), _before(_without_runtime())):
        assert preflight.builder_request(closure, before, "arm64") == closure
        assert preflight.builder_request(REQUEST, before, "arm64", missing_only=True) == list(REQUEST)


def test_resolve_simulates_the_exact_selector_with_every_hold_and_binds_it_to_a_trusted_index():
    box = Box()
    result = preflight.resolve(box, "linux/arm64", REQUEST)
    pins = apt.baseline_pins(_before(), "arm64", ())
    assert f"libssl3t64={SSL}" in pins and f"openssl={SSL}" in pins and len(pins) == len(BASE)
    assert _simulations(box) == [[*SIMULATE, "--no-install-recommends", "--no-remove", *pins, *REQUEST, DEV]]
    order = [box.commands.index(c) for c in (["apt-get", "update"], ["dpkg", "--print-architecture"])]
    assert order[0] < order[1] < box.commands.index(_simulations(box)[0])
    header = [item for item in result["packages"] if item["name"] == "libssl-dev"]
    assert [(h["version"], h["architecture"], h["sha256"], h["size"]) for h in header] == [(SSL, "arm64",
                                                                                              _sha("libssl-dev"), 10)]
    assert header[0]["origins"][0]["Origin"] == "Debian" and header[0]["locations"][0]["filename"] == \
        "pool/libssl-dev.deb"
    assert result["trusted_targets"][0]["Suite"] == "bookworm" and result["preexisting_rows"] == len(BASE)


def test_the_bound_header_survives_into_the_validated_candidate_manifest():
    source, keyring = "/etc/apt/sources.list.d/pgdg.list", "/usr/local/share/keyrings/postgres.gpg.asc"
    steps: dict[str, Any] = {
        "builder": preflight.resolve(Box(), "linux/arm64", REQUEST), "final_closure": {"packages": []},
        "libpq5_version": LIBPQ, "identity": {"postgres": "sha256:" + "1" * 64}, "closure": {"imports": ["_ssl"]},
        "trust": {"pgdg_source": source, "sources": {source: {"sha256": "2" * 64}}, "pgdg_keyring": keyring,
                  "keyrings": {keyring: "3" * 64}, "fingerprints": {"primary": ["B97B0AFC" * 5]}}}
    libpq = {"role": "libpq", "owner": "libpq5", "resolved": "/usr/lib/aarch64-linux-gnu/libpq.so.5.18",
             "sha256": "4" * 64}
    # ADR 0091: the candidate consumes only a verified runtime observation; a synthetic one bound to these inputs
    expected, hashes = runtime.binding(steps, {"files": [libpq]}, "linux/arm64", "run-1")
    steps["libpq_runtime"] = runtime.record(expected, hashes, api=180006, machine="aarch64", selected=[
        row for row in expected["table"] if row[0] == "libpq5"], digests=("5" * 64, "6" * 64))
    preflight.candidate(steps, "linux/arm64", {"files": [libpq]})
    builder = steps["candidate"]["manifest"]["builder"]
    header = DebPackage("libssl-dev", SSL, "arm64", _sha("libssl-dev"))
    assert [p for p in builder if p.name.startswith("libssl")] == [header]
    assert steps["candidate"]["valid"] and len(builder) == len(PLAN), builder


def test_final_closure_resolution_keeps_missing_only_without_a_header():
    rows = _without_runtime(*((name, "arm64", version, "ii ") for name, version in PLAN[:3]),
                            ("libpq5", "arm64", LIBPQ, "ii "))
    box = Box(rows, plan=(("libpq-dev", LIBPQ),))
    result = preflight.resolve(box, "linux/arm64", REQUEST, missing_only=True)
    assert _simulations(box)[0][-1] == f"libpq-dev={LIBPQ}" and DEV not in _simulations(box)[0]
    assert [item["name"] for item in result["packages"]] == ["libpq-dev"]


STATES = [  # every runtime or header state but the exact one; shared by both selectors
    (_without_runtime(), "missing runtime"),
    (_without_runtime(("libssl3t64", "arm64", "3.5.5-1~deb13u1", "ii ")), "unknown version"),
    (_without_runtime(("libssl3", "arm64", "3.0.20-1~deb12u2", "ii ")), "legacy Bookworm runtime"),
    (_without_runtime(("libssl3t64", "amd64", SSL, "ii ")), "foreign architecture"),
    ((*BASE, ("libssl3t64", "amd64", SSL, "ii ")), "multiarch"),
    (_without_runtime(("libssl3t64", "arm64", SSL, "rc ")), "status rc"),
    ((*BASE, ("libssl-dev", "arm64", SSL, "ii ")), "existing header ii"),
    ((*BASE, ("libssl-dev", "arm64", SSL, "rc ")), "existing header rc"),
    ((*BASE, ("libssl-dev", "arm64", "3.5.5-1~deb13u1", "ii ")), "existing other header"),
    ((*BASE, ("libssl-dev", "amd64", SSL, "ii ")), "existing foreign header"),
]


@pytest.mark.parametrize("rows, request_, reason", [
    *((rows, REQUEST, reason) for rows, reason in STATES),
    (BASE, (*REQUEST, "libssl-dev"), "header already requested"),
    (BASE, (*REQUEST, DEV), "exact header already requested"),
])
def test_any_other_runtime_or_header_state_refuses_before_simulation(rows, request_, reason):
    box = Box(rows)
    with pytest.raises(preflight.PreflightRefusal, match="builder header refused before simulation"):
        preflight.resolve(box, "linux/arm64", request_)
    assert [c for c in box.commands if c[0] in ("dpkg", "dpkg-query")], reason
    assert _simulations(box) == [] and ["apt-get", "indextargets"] not in box.commands, reason


@pytest.mark.parametrize("before", [
    {"libssl3t64:arm64": "ii libssl3t64 arm64"},
    {"libssl3t64:arm64": {"name": "libssl3t64", "architecture": "arm64", "status": "ii"}},
])
def test_malformed_installed_rows_refuse(before: dict[str, Any]):
    with pytest.raises(preflight.PreflightRefusal, match="builder header refused|malformed installed"):
        preflight.builder_request(REQUEST, before, "arm64")


def test_malformed_package_database_refuses_before_any_simulation():
    box = Box((*BASE, ("libssl-dev", "arm64", SSL, "iU ")))
    with pytest.raises(apt.PrerequisiteRefused, match="not ii/rc"):
        preflight.resolve(box, "linux/arm64", REQUEST)
    assert _simulations(box) == []


@pytest.mark.parametrize("box, error, message", [
    (Box(simulate=100), apt.PrerequisiteRefused, "failed with exit 100"),
    (Box(plan=(*PLAN[:5], ("libssl-dev", "3.0.22-1~deb12u1"))), preflight.PreflightRefusal, "requests not added"),
])
def test_an_unavailable_or_substituted_header_refuses_without_binding(box, error, message):
    with pytest.raises(error, match=message):
        preflight.resolve(box, "linux/arm64", REQUEST)
    assert DEV in _simulations(box)[0] and ["apt-get", "indextargets"] not in box.commands


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_header_is_added_only_inside_resolution_after_the_inventory_and_before_the_simulation():
    source = Path(str(preflight.__file__)).resolve()
    assert source == Path(__file__).resolve().parents[5] / "tools/d12_dependency_preflight.py"
    assert Path(str(apt.__file__)).resolve() == source.parent / "native_apt_prerequisites.py"
    tree = ast.parse(source.read_bytes())
    body = _function(tree, "resolve").body
    lines = [ast.unparse(statement) for statement in body]
    inventory = lines.index("before = apt.installed_packages(run)")
    added = next(i for i, line in enumerate(lines) if "builder_request(" in line)
    simulated = next(i for i, line in enumerate(lines) if "apt.plan(" in line)
    assert inventory < added < simulated, lines
    assert lines[added] == "request = builder_request(request, before, native, missing_only=missing_only)"
    assert "*apt.baseline_pins(before, native, ())" in lines[simulated]
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "builder_request"]
    assert len(calls) == 1, "one call site: E-g/E-h resolution only"
    explore = ast.unparse(_function(tree, "explore"))
    assert "['gcc', 'binutils', 'libc6-dev', f'libpq-dev={libpq}', f'libpq5={libpq}']" in explore
    assert "missing_only=True" in explore and "libssl" not in explore


_SELECTOR = [node for node in ast.parse(commands._INSTALL_AND_PROBE).body
             if isinstance(node, ast.FunctionDef) and node.name == "header_pin"
             or isinstance(node, ast.Assign) and "LIBSSL" in ast.unparse(node.targets[0])]
_DRIVER = ("import json, sys\nrows, path = json.loads(sys.argv[1])\ntry:\n"
           "    print(json.dumps(['selected', header_pin(rows, 'arm64', path)]))\n"
           "except (RuntimeError, FileExistsError) as error:\n"
           "    print(json.dumps([type(error).__name__, str(error)]))\n")


def _runtime_selector(before: dict[str, Any], path: Path) -> list[str]:
    """Run the managed test-runtime selector, exactly as written in the fingerprinted install program, isolated."""
    program = "\n".join(map(ast.unparse, _SELECTOR)) + "\n" + _DRIVER
    done = subprocess.run([sys.executable, "-I", "-c", program, json.dumps([before, str(path)])],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_both_selectors_bind_the_one_exact_trixie_tuple_and_the_runtime_pin_is_transaction_only(tmp_path):
    exact = _SELECTOR[0]
    assert isinstance(exact, ast.Assign) and ast.unparse(exact.targets[0]) == "(LIBSSL, LIBSSL_DEV, LIBSSL_VERSION)"
    assert preflight.HEADER == ("libssl3t64", "libssl-dev", SSL) == ast.literal_eval(exact.value)
    before, path = _before(), tmp_path / "header.pref"
    assert _runtime_selector(before, path) == ["selected", str(path)]
    assert path.read_text() == f"Package: libssl-dev\nPin: version {SSL}\nPin-Priority: 999\n" and before == _before()
    path.write_text("operator\n")
    assert _runtime_selector(before, path)[0] == "FileExistsError"
    assert path.read_text() == "operator\n", "an existing preference is never clobbered"


@pytest.mark.parametrize("rows, reason", STATES)
def test_runtime_selector_refuses_every_other_state_before_any_preference_or_install(tmp_path, rows, reason):
    before, path = _before(rows), tmp_path / "header.pref"
    outcome, message = _runtime_selector(before, path)
    assert outcome == "RuntimeError" and "header state refused before any preference or install" in message, reason
    assert not path.exists() and before == _before(rows), reason
