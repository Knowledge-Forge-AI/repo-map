"""ADR 0089 D4 E-f host owner: canned contract reports and dpkg rows; the enrolled entries are used as-is.

ADR 0103 enrolled the native AMD 3.12.16 default, so AMD positives use that actual entry and its config; held and
foreign (historical 3.12.15 a33c10) AMD states are isolated doubles that must still refuse.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

import pytest

from ci.python_retention_operations import dynamic_operations
import d12_python_closure as closure
from common_lore_index.runtime import python_payload as payload

ENTRY, LIBC, REAL = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"], "/lib/aarch64-linux-gnu/libc.so.6", "/usr/lib/libc.so.6"
NAMES, OK = list(ENTRY.baseline_imports), "\tlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x2)\n"
AMD_CFG = payload.PYTHON_31216_AMD64_CONFIG
FOREIGN_31215_AMD_CFG = "sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1"
LIBC_AMD, REAL_AMD = "/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/x86_64-linux-gnu/libc.so.6"
OK_AMD = f"\tlibc.so.6 => {LIBC_AMD} (0x2)\n"


class Refused(Exception):
    pass


def _amd_entry() -> payload.PayloadExclusion:
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS.get("amd64")
    assert entry is not None, "frozen amd64 exclusion entry required"
    assert entry == payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
    return entry


def _validate_hosted(cl: object, cfg: str = AMD_CFG) -> list[str]:
    fn = getattr(closure, "validate_hosted_closure", None)
    assert callable(fn), "validate_hosted_closure helper is required"
    res = fn(cl, cfg)
    assert isinstance(res, list)
    return res


def _baseline(**changes: Any) -> dict[str, Any]:
    elves = {f"{payload.DYNLOAD}/{n}.cpython-312-aarch64-linux-gnu.so": {
        "sha256": hashlib.sha256(n.encode()).hexdigest(), "size": 1, "elf": [2, 1, 183], "ldd": OK, "ldd_exit": 0}
        for n in NAMES}
    elves[ENTRY.path] = {"sha256": ENTRY.sha256, "size": ENTRY.size, "elf": [2, 1, 183], "ldd_exit": 0,
                         "ldd": OK + "\tlibtcl8.6.so => not found\n\tlibtk8.6.so => not found\n"}
    return {"machine": "aarch64", "entries": len(elves), "digest": "0" * 64, "elves": elves,
            "targets": {LIBC: [REAL, "a" * 64]},
            "dynload": sorted([p.rsplit("/", 1)[1], "file"] for p in elves), "dynload_real": payload.DYNLOAD,
            "imports": NAMES, "failed": {"_tkinter": {"exit": 1, "error": "ImportError"}}, **changes}


def _report(**changes: Any) -> dict[str, Any]:
    baseline = _baseline()
    before = {path: ["file", elf["sha256"], 1, 33188] for path, elf in baseline["elves"].items()}
    after = {**baseline, "elves": {p: e for p, e in baseline["elves"].items() if p != ENTRY.path}, "failed": {},
             "dynload": [row for row in baseline["dynload"] if not ENTRY.path.endswith(row[0])]}
    retained = payload.verify_retained(before, {p: v for p, v in before.items() if p != ENTRY.path}, after, ENTRY,
                                       {LIBC: "libc6"})
    return {"schema": payload.SCHEMA, "architecture": "arm64", "result": "trimmed", "reasons": [], "baseline": baseline,
            "exclusion": payload.classify(baseline, ENTRY), "retained": retained, **changes}


def _amd_baseline(**changes: Any) -> dict[str, Any]:
    entry = _amd_entry()
    elves = {f"{payload.DYNLOAD}/{n}.cpython-312-x86_64-linux-gnu.so": {
        "sha256": hashlib.sha256(n.encode()).hexdigest(), "size": 1, "elf": [2, 1, 62], "ldd": OK_AMD, "ldd_exit": 0}
        for n in entry.baseline_imports}
    for idx in range(4):
        elves[f"/usr/local/bin/py{idx}"] = {
            "sha256": hashlib.sha256(f"py{idx}".encode()).hexdigest(), "size": 1, "elf": [2, 1, 62],
            "ldd": OK_AMD, "ldd_exit": 0}
    elves[entry.path] = {"sha256": entry.sha256, "size": entry.size, "elf": [2, 1, 62], "ldd_exit": 0,
                         "ldd": OK_AMD + "\tlibtk8.6.so => not found\n\tlibtcl8.6.so => not found\n"}
    return {"machine": "x86_64", "entries": 1721, "digest": "0" * 64, "elves": elves,
            "targets": {LIBC_AMD: [REAL_AMD, "a" * 64]},
            "dynload": sorted([p.rsplit("/", 1)[1], "file"] for p in elves if p.startswith(payload.DYNLOAD + "/")),
            "dynload_real": payload.DYNLOAD, "imports": list(entry.baseline_imports),
            "failed": {"_tkinter": {"exit": 1, "error": "ImportError"}}, **changes}


def _amd_report(**changes: Any) -> dict[str, Any]:
    entry, baseline = _amd_entry(), _amd_baseline()
    before = {p: ["file", e["sha256"], e["size"], 33188] for p, e in baseline["elves"].items()}
    after = {**baseline, "entries": 1720, "elves": {p: e for p, e in baseline["elves"].items() if p != entry.path},
             "failed": {}, "dynload": [row for row in baseline["dynload"] if not entry.path.endswith(row[0])]}
    retained = {**payload.verify_retained(before, {p: v for p, v in before.items() if p != entry.path}, after, entry,
                                          {LIBC_AMD: "libc6"}), "entries": 1720}
    return {"schema": payload.SCHEMA, "architecture": "amd64", "result": "trimmed", "reasons": [], "baseline": baseline,
            "exclusion": payload.classify(baseline, entry), "retained": retained, **changes}


class Box:
    def __init__(self, report: dict[str, Any] | str, code: int = 0, *, arch: str = "arm64",
                 real: str = REAL) -> None:
        self.stdout, self.code = report if isinstance(report, str) else json.dumps(report), code
        self.argv, self.arch, self.real = list[list[str]](), arch, real

    def run(self, command: list[str], **_options: Any) -> subprocess.CompletedProcess[str]:
        if command[0] == "python3":
            self.argv.append(command)
            return subprocess.CompletedProcess(command, self.code, self.stdout + "\n", "")
        if command[:2] == ["dpkg-query", "-W"]:
            return subprocess.CompletedProcess(command, 0, f"libc6\t{self.arch}\t2.36-9\tii \t\t\n", "")
        found = command[:3] == ["dpkg-query", "-S", self.real]
        assert command[:2] == ["dpkg-query", "-S"], command
        return subprocess.CompletedProcess(command, int(not found), f"libc6:{self.arch}: {self.real}\n" * found, "")


def _steps(config: str = ENTRY.python_config, native: str = "native", platform: str = "linux/arm64") -> dict[str, Any]:
    return {"identity": {"python": config}, "engine": {"classification": {platform: native}}}


def _facts(box: Box, steps: dict[str, Any], platform: str = "linux/arm64") -> dict[str, Any]:
    try:
        return closure.closure_facts(steps, box.run, platform, refusal=Refused)
    finally:
        assert len(box.argv) == 1, "the contract runs exactly once"


def test_frozen_trim_keeps_raw_findings_records_the_exclusion_and_maps_retained_owners() -> None:
    box = Box(_report())
    facts = _facts(box, _steps())
    assert box.argv[0][:4] == ["python3", "-I", "-B", "-c"] and box.argv[0][4:] == [closure.program(), "arm64"]
    assert closure.program().encode() == Path(payload.__file__).read_bytes(), "the recipe's exact file"
    assert facts["baseline_unresolved"] == [f"{ENTRY.path}: libtcl8.6.so => not found",
                                            f"{ENTRY.path}: libtk8.6.so => not found"], "raw findings retained"
    assert facts["baseline_failed"] == ["_tkinter"] and facts["baseline"]["elves"][ENTRY.path]["size"] == 70584
    assert facts["exclusion"]["sha256"] == ENTRY.sha256 and facts["unresolved"] == [], facts["exclusion"]
    assert facts["imports"] == facts["lib_dynload"] == NAMES and len(NAMES) == 77 and facts["elf_count"] == 77
    assert facts["dependencies"][LIBC]["package"] == "libc6" and facts["packages"] == [("libc6", "2.36-9", "arm64")]
    assert facts["contract"]["exclusion_applies"] and facts["contract"]["program_sha256"] == hashlib.sha256(
        Path(payload.__file__).read_bytes()).hexdigest(), facts["contract"]


def test_native_amd64_exact_config_applies_exclusion_and_retains_tk_first_order() -> None:
    entry = _amd_entry()
    box = Box(_amd_report(), arch="amd64", real=REAL_AMD)
    facts = _facts(box, _steps(config=AMD_CFG, platform="linux/amd64"), "linux/amd64")
    assert box.argv[0] == ["python3", "-I", "-B", "-c", closure.program(), "amd64"]
    assert facts["baseline_unresolved"] == [f"{entry.path}: libtk8.6.so => not found",
                                            f"{entry.path}: libtcl8.6.so => not found"]
    assert sorted(facts["baseline_unresolved"]) == [f"{entry.path}: libtcl8.6.so => not found",
                                                    f"{entry.path}: libtk8.6.so => not found"]
    assert facts["baseline_failed"] == ["_tkinter"] and facts["baseline"]["entries"] == 1721
    assert len(facts["baseline"]["elves"]) == 82 and facts["retained"]["entries"] == 1720
    assert facts["elf_count"] == facts["retained"]["elf_count"] == 81 and facts["unresolved"] == []
    assert facts["exclusion"]["sha256"] == entry.sha256 and facts["exclusion"]["size"] == 62448
    assert facts["imports"] == facts["lib_dynload"] == list(entry.baseline_imports)
    assert facts["packages"] == [("libc6", "2.36-9", "amd64")]
    assert _validate_hosted(facts, AMD_CFG) == []


@pytest.mark.parametrize("steps, platform", [
    (_steps(config="sha256:" + "9" * 64), "linux/arm64"),
    (_steps(native="emulated"), "linux/arm64"),
    (_steps(config=ENTRY.python_config, platform="linux/amd64"), "linux/amd64"),
    (_steps(config="sha256:" + "9" * 64, platform="linux/amd64"), "linux/amd64"),
    (_steps(config=AMD_CFG, native="emulated", platform="linux/amd64"), "linux/amd64"),
])
def test_another_base_config_foreign_arm_config_or_emulation_gets_no_exclusion(steps, platform) -> None:
    assert _amd_entry().python_config == AMD_CFG
    honest = {**_report(), "result": "refused", "exclusion": None, "retained": None,
              "reasons": ["PayloadRefusal: no frozen exclusion applies; unresolved or missing dynamic dependencies"]}
    box = Box(honest, code=1)
    with pytest.raises(Refused, match="unresolved or missing dynamic dependencies"):
        _facts(box, steps, platform)
    assert box.argv[0][-1] == "--no-exclusion" and steps["closure"]["baseline_unresolved"], "raw baseline kept"
    with pytest.raises(Refused, match="does not match the applied contract"):  # an unrequested trim refuses too
        _facts(Box(_report()), dict(steps), platform)


def _retained(**changes: Any) -> dict[str, Any]:
    report = _report()
    return {**report, "retained": {**report["retained"], **changes}}


@pytest.mark.parametrize("report, code, message", [
    (_report(baseline=_baseline(elves={**_baseline()["elves"], "/usr/local/bin/x": {
        "sha256": "c" * 64, "size": 1, "elf": [2, 1, 183], "ldd": "\tlibz.so => not found\n", "ldd_exit": 0}})),
     0, "host classification of the raw baseline refuses"),
    (_report(exclusion={**_report()["exclusion"], "size": 1}), 0, "differs from the container's"),
    (_report(), 1, "payload contract exited 1"),
    (_report(result="clean"), 0, "does not match the applied contract"),
    (_retained(imports=NAMES[1:]), 0, "retained payload proof"),
    (_retained(lib_dynload=[*NAMES, "_tkinter"]), 0, "retained payload proof"),
    (_retained(unresolved=["x"]), 0, "retained payload proof"),
    (_retained(excluded_absent=False), 0, "retained payload proof"),
    (_retained(expected_digest="f" * 64), 0, "retained payload proof"),
    (_retained(owners={LIBC: ""}), 0, "retained payload proof"),
    (_retained(elves={}), 0, "retained payload proof"),
])
def test_host_refuses_a_disagreeing_or_incomplete_container_verdict(report, code, message) -> None:
    steps = _steps()
    with pytest.raises(Refused, match=message):
        _facts(Box(report, code), steps)
    assert steps["closure"]["baseline"] == report["baseline"], "the raw report is kept for the saved E1 report"


@pytest.mark.parametrize("stdout", [
    "not json", "", "[]", json.dumps(_report(schema="other")), json.dumps(_report(extra=1)),
    json.dumps(_report(reasons=["x"])), json.dumps(_report(baseline=_baseline(digest="X" * 64))),
    json.dumps(_report(baseline=_baseline(targets={LIBC: [1, "a" * 64]}))),
])
def test_malformed_reports_refuse_before_any_record(stdout: str) -> None:
    steps = _steps()
    with pytest.raises(Refused, match="malformed closure observation"):
        _facts(Box(stdout), steps)
    assert "closure" not in steps


def test_extracted_module_never_imports_the_preflight_and_product_never_imports_tools() -> None:
    tree, product = (ast.parse(Path(str(m.__file__)).read_bytes()) for m in (closure, payload))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {str(n.module) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert {name for name in imported if name.split(".")[0] not in sys.stdlib_module_names} == {
        "native_apt_prerequisites", "common_lore_index.runtime"}, imported
    assert dynamic_operations(tree) == dynamic_operations(product) == [] and "sys.path" not in ast.unparse(tree)
    assert not [n for n in ast.walk(product) if isinstance(n, (ast.Import, ast.ImportFrom)) and any(
        str(getattr(n, "module", None) or a.name).split(".")[0] not in sys.stdlib_module_names for a in n.names)]
    root = Path(__file__).resolve().parents[5]
    for tree_root in ("src/main/python", "src/test/support/python"):
        assert not [p for p in (root / tree_root).rglob("*.py") if "d12_python_closure" in p.read_text()], tree_root


def _amd_closure() -> dict[str, Any]:
    return _facts(Box(_amd_report(), arch="amd64", real=REAL_AMD),
                  _steps(config=AMD_CFG, platform="linux/amd64"), "linux/amd64")


def _amd_clean_closure() -> dict[str, Any]:
    entry, base = _amd_entry(), _amd_baseline()
    clean_elves = {p: e for p, e in base["elves"].items() if p != entry.path}
    clean_base = {**base, "entries": 1720, "elves": clean_elves, "failed": {},
                  "dynload": [r for r in base["dynload"] if not entry.path.endswith(r[0])]}
    before = {p: ["file", e["sha256"], e["size"], 33188] for p, e in clean_elves.items()}
    ret = {**payload.verify_retained(before, before, clean_base, None, {LIBC_AMD: "libc6"}), "entries": 1720}
    rep: dict[str, Any] = {"schema": payload.SCHEMA, "architecture": "amd64", "result": "clean", "reasons": [],
                           "baseline": clean_base, "exclusion": None, "retained": ret}
    return _facts(Box(rep, arch="amd64", real=REAL_AMD),
                  _steps(config="sha256:" + "8" * 64, platform="linux/amd64"), "linux/amd64")


def test_validate_hosted_closure_accepts_full_trim_clean_contract_and_minimal_legacy_clean() -> None:
    assert _validate_hosted(_amd_closure(), AMD_CFG) == []
    assert _validate_hosted(_amd_clean_closure(), "sha256:" + "8" * 64) == []
    legacy = {"unresolved": [], "baseline_failed": [], "elf_count": 42,
              "retained": {"preserved": True, "unresolved": []}, "imports": ["_ssl", "math"]}
    assert _validate_hosted(legacy, AMD_CFG) == []


@pytest.mark.parametrize("mutate", [
    lambda _c: [],
    lambda c: {**c, "unresolved": ["x"]},
    lambda c: {**c, "elf_count": 0},
    lambda c: {**c, "elf_count": True},
    lambda c: {**c, "retained": None},
    lambda c: {**c, "retained": {**c["retained"], "preserved": False}},
    lambda c: {**c, "retained": {**c["retained"], "preserved": "true"}},
    lambda _c: {"unresolved": [], "baseline_failed": ["_tkinter"], "elf_count": 81,
                "retained": {"preserved": True, "unresolved": []}},
    lambda _c: {"unresolved": [], "baseline_failed": [], "baseline_unresolved": ["x"], "elf_count": 81,
                "retained": {"preserved": True, "unresolved": []}},
    lambda _c: {"unresolved": [], "baseline_failed": [], "exclusion": {"module": "_tkinter"}, "elf_count": 81,
                "retained": {"preserved": True, "unresolved": []}},
    lambda _c: {"unresolved": [], "baseline_failed": [], "elf_count": 81,
                "retained": {"preserved": True, "unresolved": [], "excluded_absent": True}},
    lambda _c: {"unresolved": [], "baseline_failed": [], "elf_count": 81, "contract": {},
                "retained": {"preserved": True, "unresolved": []}},
    lambda c: {**c, "contract": None},
    lambda c: {**c, "contract": {k: v for k, v in c["contract"].items() if k != "exclusion_applies"}},
    lambda c: {**c, "contract": {**c["contract"], "exclusion_applies": False}},
    lambda c: {**c, "contract": {**c["contract"], "exclusion_applies": "true"}},
    lambda c: {**c, "contract": {**c["contract"], "native": "emulated"}},
    lambda c: {**c, "contract": {**c["contract"], "python_config": ENTRY.python_config}},
    lambda c: {**c, "contract": {**c["contract"], "program_sha256": "0" * 64}},
    lambda c: {**c, "contract": {**c["contract"], "exit": 1}},
    lambda c: {**c, "contract": {**c["contract"], "exit": True}},
    lambda c: {**c, "contract": {**c["contract"], "result": "clean"}},
    lambda c: {**c, "contract": {**c["contract"], "reasons": ["x"]}},
    lambda c: {**c, "baseline": None},
    lambda c: {**c, "baseline": {}},
    lambda c: {**c, "baseline": {**c["baseline"], "digest": "Z" * 64}},
    lambda c: {**c, "baseline": {**c["baseline"], "entries": True}},
    lambda c: {**c, "baseline": {**c["baseline"], "imports": "not-a-list"}},
    lambda c: {**c, "baseline": {**c["baseline"], "targets": {LIBC_AMD: [1, "a" * 64]}}},
    lambda c: {**c, "baseline": {**c["baseline"], "dynload": [["only-one"]]}},
    lambda c: (c["baseline"]["elves"][_amd_entry().path].update(size="62448"), c)[1],
    lambda c: {**c, "baseline_failed": []},
    lambda c: {**c, "baseline_failed": ["_tkinter", "math"]},
    lambda c: (c["baseline"]["failed"].update(math={"exit": 1, "error": "err"}), c)[1],
    lambda c: (c["baseline"]["elves"][_amd_entry().path].update(
        ldd=OK_AMD + "\tlibtk8.6.so => not found\n\tlibtcl8.6.so => not found\n\tlibX11.so.6 => not found\n"), c)[1],
    lambda c: {**c, "baseline_unresolved": sorted(c["baseline_unresolved"])},
    lambda c: {**c, "exclusion": None},
    lambda c: {**c, "exclusion": {**c["exclusion"], "size": 1}},
    lambda c: {**c, "exclusion": {**c["exclusion"], "sha256": "0" * 64}},
    lambda c: {**c, "retained": {**c["retained"], "excluded_absent": False}},
    lambda c: {**c, "retained": {**c["retained"], "excluded_absent": None}},
    lambda c: {**c, "retained": {**c["retained"], "expected_digest": "f" * 64}},
    lambda c: {**c, "retained": {**c["retained"], "entries": 1721}},
    lambda c: {**c, "retained": {**c["retained"], "elves": {}}},
    lambda c: {**c, "retained": {**c["retained"], "imports": NAMES[1:]}},
    lambda c: {**c, "retained": {**c["retained"], "lib_dynload": [*NAMES, "_tkinter"]}},
    lambda c: {**c, "retained": {**c["retained"], "owners": {LIBC_AMD: ""}}},
    lambda c: {**c, "retained": {**c["retained"], "elf_count": 80}},
    lambda c: {**c, "elf_count": 82},
    lambda c: {**c, "imports": ["_ssl"]},
    lambda c: {**c, "lib_dynload": ["_ssl"]},
])
def test_validate_hosted_closure_rejects_forged_incomplete_or_malformed_inputs(
    mutate: Callable[[dict[str, Any]], Any]
) -> None:
    candidate = mutate(copy.deepcopy(_amd_closure()))
    violations = _validate_hosted(candidate, AMD_CFG)
    assert violations and all("closure invalid" in v for v in violations), violations


def test_validate_hosted_closure_rejects_non_mapping_and_clean_contract_drift() -> None:
    assert any("closure invalid" in v for v in _validate_hosted(None, AMD_CFG))
    assert any("closure invalid" in v for v in _validate_hosted(_amd_closure(), ENTRY.python_config))
    clean = _amd_clean_closure()
    clean["elf_count"] = 999
    assert any("closure invalid" in v for v in _validate_hosted(clean, "sha256:" + "8" * 64))


def test_foreign_31215_amd_config_and_held_amd_default_refuse_the_trim(monkeypatch: pytest.MonkeyPatch) -> None:
    foreign = copy.deepcopy(_amd_closure())
    foreign["contract"]["python_config"] = FOREIGN_31215_AMD_CFG  # metadata agrees; the enrolled entry does not
    assert _validate_hosted(foreign, FOREIGN_31215_AMD_CFG) == [
        "positive exploration steps.closure invalid: invalid trim contract or config"]
    facts, honest = _amd_closure(), {
        **_amd_report(), "result": "refused", "exclusion": None, "retained": None,
        "reasons": ["PayloadRefusal: no frozen exclusion applies; unresolved or missing dynamic dependencies"]}
    monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", {"arm64": ENTRY})  # isolated held-AMD double
    assert _validate_hosted(facts, AMD_CFG) == [
        "positive exploration steps.closure invalid: invalid trim contract or config"]
    box = Box(honest, code=1, arch="amd64", real=REAL_AMD)
    with pytest.raises(Refused, match="unresolved or missing dynamic dependencies"):
        _facts(box, _steps(config=AMD_CFG, platform="linux/amd64"), "linux/amd64")
    assert box.argv[0][-1] == "--no-exclusion", "a held default never applies the trim"
