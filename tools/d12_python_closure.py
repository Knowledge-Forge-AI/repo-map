"""ADR 0089 D4 E-f, extracted from the preflight (runner and refusal injected): the closure container runs the
recipe's exact payload contract file; its exclusion applies only natively on the frozen Python config."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import native_apt_prerequisites as apt
from common_lore_index.runtime import python_payload as payload

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


def validate_hosted_closure(closure: object, python_config: str) -> list[str]:
    if not isinstance(closure, Mapping):
        return ["positive exploration steps.closure invalid"]
    elf, ret = closure.get("elf_count"), closure.get("retained")
    if (closure.get("unresolved") != [] or type(elf) is not int or elf <= 0
            or not isinstance(ret, Mapping) or ret.get("preserved") is not True):
        return ["positive exploration steps.closure invalid"]
    if ("contract" not in closure and "baseline" not in closure and closure.get("exclusion") is None
            and not closure.get("baseline_unresolved") and closure.get("baseline_failed") == []
            and ret.get("excluded_absent") is None and ret.get("unresolved") in (None, [])):
        return []
    try:
        contract, base = closure["contract"], closure["baseline"]
        if (not isinstance(contract, Mapping) or not isinstance(base, Mapping) or set(base) != BASELINE
                or not _hex(base["digest"]) or type(base["entries"]) is not int
                or not isinstance(base["machine"], str) or not isinstance(base["failed"], dict)
                or not isinstance(base["imports"], list) or not all(isinstance(m, str) for m in base["imports"])
                or not isinstance(base["elves"], dict)
                or not all(isinstance(k, str) and isinstance(e, Mapping) and _hex(e["sha256"])
                           and type(e["size"]) is int and isinstance(e["ldd"], str)
                           and isinstance(e["elf"], list) for k, e in base["elves"].items())
                or not isinstance(base["targets"], dict)
                or not all(isinstance(t, (list, tuple)) and len(t) == 2 and isinstance(t[0], str)
                           and (t[1] is None or _hex(t[1])) for t in base["targets"].values())
                or not isinstance(base["dynload"], list)
                or not all(isinstance(d, (list, tuple)) and len(d) == 2 and isinstance(d[0], str)
                           and isinstance(d[1], str) for d in base["dynload"])):
            return ["positive exploration steps.closure invalid: malformed contract or baseline"]
        applies = contract.get("exclusion_applies")
        prog_sha = hashlib.sha256(program().encode()).hexdigest()
        if (not isinstance(applies, bool) or contract.get("native") != "native"
                or contract.get("python_config") != python_config or contract.get("program_sha256") != prog_sha
                or type(contract.get("exit")) is not int or contract.get("exit") != 0
                or contract.get("reasons") != []):
            return ["positive exploration steps.closure invalid: contract metadata mismatch"]
        raw_lost = payload.unresolved(base["elves"])
        claimed_trim = (applies or contract.get("result") == "trimmed" or closure.get("exclusion") is not None
                        or closure.get("baseline_failed") != [] or closure.get("baseline_unresolved") != []
                        or ret.get("excluded_absent") is not None or bool(base["failed"]))
        if claimed_trim:
            entry = payload.PYTHON_PAYLOAD_EXCLUSIONS.get("amd64")
            if (not applies or contract.get("result") != "trimmed" or entry is None
                    or entry.python_config != python_config):
                return ["positive exploration steps.closure invalid: invalid trim contract or config"]
            payload.validate_exclusion(entry, "amd64")
            exp_lost = [f"{entry.path}: {lib} => not found" for lib in entry.missing]
            if (closure.get("baseline_failed") != [entry.module]
                    or closure.get("baseline_unresolved") != raw_lost or sorted(raw_lost) != exp_lost
                    or ret.get("excluded_absent") is not True):
                return ["positive exploration steps.closure invalid: baseline trim findings mismatch"]
        else:
            entry = None
            if contract.get("result") != "clean" or raw_lost != []:
                return ["positive exploration steps.closure invalid: clean contract mismatch"]
        _check({"schema": payload.SCHEMA, "architecture": "amd64", "result": contract["result"],
                "reasons": contract["reasons"], "baseline": base, "exclusion": closure.get("exclusion"),
                "retained": ret}, 0, entry)
        if (ret.get("elf_count") != len(ret["elves"]) or elf != len(ret["elves"])
                or closure.get("imports") != ret.get("imports")
                or closure.get("lib_dynload") != ret.get("lib_dynload")):
            return ["positive exploration steps.closure invalid: summary mismatch"]
    except (payload.PayloadRefusal, KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"positive exploration steps.closure invalid: {error}"]
    return []
