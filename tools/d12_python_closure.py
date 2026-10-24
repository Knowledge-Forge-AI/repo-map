"""ADR 0089 D4 E-f, extracted from the preflight (runner and refusal injected): the closure container runs the
recipe's exact payload contract file; its exclusion applies only natively on the frozen Python config."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import native_apt_prerequisites as apt
from repomap_kg.runtime import python_payload as payload

KEYS = {"schema", "architecture", "result", "reasons", "baseline", "exclusion", "retained"}
BASELINE = {"machine", "entries", "digest", "elves", "dynload", "dynload_real", "imports", "failed", "targets"}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def program() -> str:
    return Path(payload.__file__).read_text(encoding="utf-8")


def contract_argv(platform: str, applies: bool) -> list[str]:
    return ["python3", "-I", "-B", "-c", program(), platform.split("/", 1)[1], *([] if applies else ["--no-exclusion"])]


def _report(stdout: str, refusal: Callable[[str], Exception]) -> dict[str, Any]:
    try:
        report = json.loads(stdout.splitlines()[-1])
        base = report["baseline"]
        if (set(report) != KEYS or report["schema"] != payload.SCHEMA or (report["result"] == "refused") != bool(
                report["reasons"]) or report["result"] not in ("clean", "trimmed", "refused") or not (
                base is None and report["result"] == "refused" or set(base) == BASELINE
                and _hex(base["digest"]) and type(base["entries"]) is int and isinstance(base["machine"], str)
                and isinstance(base["failed"], dict) and all(isinstance(m, str) for m in base["imports"])
                and all(_hex(e["sha256"]) and type(e["size"]) is int and isinstance(e["ldd"], str)
                        and isinstance(e["elf"], list) for e in base["elves"].values())
                and all(isinstance(real, str) for real, _digest in base["targets"].values())
                and all(isinstance(name, str) and isinstance(kind, str) for name, kind in base["dynload"]))):
            raise ValueError("report shape")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise refusal(f"malformed closure observation ({type(error).__name__})") from error
    return report


def _check(report: Mapping[str, Any], exit_code: int, entry: payload.PayloadExclusion | None) -> None:
    baseline, retained = report["baseline"], report["retained"]
    if report["result"] == "refused" or exit_code != 0 or baseline is None:
        raise payload.PayloadRefusal("; ".join(report["reasons"]) or f"payload contract exited {exit_code}")
    if report["result"] != ("clean" if entry is None else "trimmed"):
        raise payload.PayloadRefusal(f"payload result {report['result']} does not match the applied contract")
    try:
        expected = payload.classify(baseline, entry)
    except payload.PayloadRefusal as error:
        raise payload.PayloadRefusal(f"the host classification of the raw baseline refuses: {error}") from error
    if expected != report["exclusion"]:
        raise payload.PayloadRefusal("the host classification of the raw baseline differs from the container's")
    removed = None if entry is None else entry.path
    wanted = baseline["imports"] if entry is None else list(entry.baseline_imports)
    if (not isinstance(retained, dict) or retained.get("unresolved") != [] or retained.get("preserved") is not True
            or retained.get("elves") != {p: e["sha256"] for p, e in baseline["elves"].items() if p != removed}
            or retained.get("imports") != wanted or retained.get("lib_dynload") != wanted
            or retained.get("entries") != baseline["entries"] - (removed is not None)
            or retained.get("digest") != retained.get("expected_digest")
            or retained.get("excluded_absent") is not (None if removed is None else True)
            or not isinstance(retained.get("owners"), dict) or not all(retained["owners"].values())
            or not isinstance(retained.get("targets"), dict) or set(retained["owners"]) != set(retained["targets"])):
        raise payload.PayloadRefusal("the retained payload proof is incomplete or differs from the raw baseline")


def closure_facts(steps: dict[str, Any], run: apt.Runner, platform: str, *,
                  refusal: Callable[[str], Exception]) -> dict[str, Any]:
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS.get(platform.split("/", 1)[1])
    config, native = steps["identity"]["python"], steps["engine"]["classification"].get(platform)
    applies = entry is not None and native == "native" and config == entry.python_config
    done = run(contract_argv(platform, applies), capture_output=True, text=True, check=False)
    report = _report(done.stdout, refusal)
    baseline, retained = report["baseline"], report["retained"]
    closure = steps["closure"] = {
        "contract": {"program_sha256": hashlib.sha256(program().encode()).hexdigest(), "python_config": config,
                     "native": native, "exclusion_applies": applies, "exit": done.returncode,
                     "result": report["result"], "reasons": report["reasons"]},
        "baseline": baseline, "exclusion": report["exclusion"], "retained": retained,  # raw findings kept on a pass
        "baseline_unresolved": payload.unresolved(baseline["elves"]) if baseline else [],
        "baseline_failed": sorted(baseline["failed"]) if baseline else []}
    problem: payload.PayloadRefusal | None = None
    try:
        _check(report, done.returncode, entry if applies else None)
    except payload.PayloadRefusal as error:
        problem = error
    final = retained if problem is None else baseline or {}
    installed, owners = apt.installed_packages(run), dict[str, dict[str, str]]()
    for target, (real, digest) in sorted(final.get("targets", {}).items()):
        if not target.startswith("/usr/local/"):
            name = apt.package_of(run, real)  # the resolved file, as the owner's inventory maps it (usrmerge-safe)
            rows = [row for row in installed.values() if row["name"] == name and row["status"] == "ii"]
            if len(rows) != 1:
                raise refusal(f"dependency {target} has no single installed dpkg owner: {name or '-'}")
            owners[target] = {"real": real, "sha256": digest, "package": name, "version": rows[0]["version"],
                              "architecture": rows[0]["architecture"]}
    closure.update({"elf_count": len(final.get("elves", {})), "dependencies": owners,
                    "unresolved": closure["baseline_unresolved"] if problem else [],
                    "packages": sorted({(o["package"], o["version"], o["architecture"]) for o in owners.values()}),
                    "lib_dynload": retained["lib_dynload"] if problem is None else (
                        payload.lib_dynload_modules(final) if final else []), "imports": final.get("imports", [])})
    if problem is not None:
        raise refusal(f"unresolved or missing dynamic dependencies, or payload contract refused: {problem}")
    return closure
