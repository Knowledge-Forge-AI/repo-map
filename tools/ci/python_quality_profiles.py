#!/usr/bin/env python3
"""Run clean non-product Python quality profile checks."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_quality_mypy import (
    QualityProfileError as QualityProfileError, _canonical_import_identity, _check_mypy,
)

from ci.python_quality_ownership import derive_profile_path_facts as derive_profile_path_facts

SCHEMA = "repomap-python-quality-profiles-result-v1"
MAX_PHYSICAL_LINES = 400
RUFF_RULES = ("F",)
RUFF_TARGET_VERSION = "py312"
EXPECTED_TOOLS = {"mypy": "2.1.0", "ruff": "0.16.2"}
def count_physical_lines(path: Path) -> int:
    """Count LF-delimited physical lines without native newline translation."""
    line_count = 0
    final_byte: int | None = None
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            line_count += chunk.count(b"\n")
            final_byte = chunk[-1]
    return line_count + 1 if final_byte not in (None, ord("\n")) else line_count


def _resolve_path(path_str: str, repo_root: Path) -> tuple[Path, str]:
    if not isinstance(path_str, str) or not path_str.strip():
        raise QualityProfileError(f"invalid path: {path_str!r}")
    posix_path = PurePosixPath(path_str)
    root_resolved = repo_root.resolve()
    if posix_path.is_absolute():
        resolved = Path(path_str).resolve()
    else:
        if ".." in posix_path.parts:
            raise QualityProfileError(f"path escapes repository root: {path_str}")
        resolved = (repo_root / posix_path).resolve()
    try:
        relative = resolved.relative_to(root_resolved).as_posix()
    except ValueError as error:
        raise QualityProfileError(f"path escapes repository root: {path_str}") from error
    lexical = Path(path_str) if posix_path.is_absolute() else root_resolved / path_str
    try:
        lexical_relative = lexical.relative_to(root_resolved).as_posix()
    except ValueError as error:
        raise QualityProfileError(f"path alias cannot change checked identity: {path_str}") from error
    if lexical_relative != relative:
        raise QualityProfileError(f"path alias cannot change checked identity: {path_str}")
    if not resolved.is_file():
        raise QualityProfileError(f"path is not an existing file: {path_str}")
    return resolved, relative


def _check_file_lengths(
    paths: Sequence[tuple[Path, str]],
) -> tuple[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    for full_path, rel_path in paths:
        count = count_physical_lines(full_path)
        if count > MAX_PHYSICAL_LINES:
            findings.append({
                "path": rel_path,
                "line_count": count,
                "limit": MAX_PHYSICAL_LINES,
                "message": f"file length {count} exceeds zero-debt limit {MAX_PHYSICAL_LINES}",
            })
    return ("failed" if findings else "passed"), findings


def _check_ruff(paths: Sequence[str], repo_root: Path) -> tuple[str, list[dict[str, Any]]]:
    py_exe = sys.executable
    show_proc = subprocess.run(
        [py_exe, "-m", "ruff", "check", "--isolated", "--show-files", "--no-cache", *paths],
        cwd=repo_root, capture_output=True, text=True, check=False, timeout=120,
    )
    if show_proc.returncode != 0:
        raise QualityProfileError(f"Ruff file attestation failure: exit={show_proc.returncode}")
    root_resolved = repo_root.resolve()
    observed = set()
    for line in show_proc.stdout.splitlines():
        candidate = Path(line)
        resolved = candidate if candidate.is_absolute() else repo_root / candidate
        try:
            observed.add(resolved.resolve().relative_to(root_resolved).as_posix())
        except ValueError as error:
            raise QualityProfileError("Ruff attested outside repository root") from error
    if observed != set(paths):
        raise QualityProfileError("Ruff failed exact requested-path attestation")

    check_proc = subprocess.run(
        [
            py_exe, "-m", "ruff", "check", "--isolated", "--target-version",
            RUFF_TARGET_VERSION, "--select", ",".join(RUFF_RULES), "--ignore-noqa", "--output-format",
            "json", "--no-cache", *paths,
        ],
        cwd=repo_root, capture_output=True, text=True, check=False, timeout=120,
    )
    if check_proc.returncode not in (0, 1):
        raise QualityProfileError(f"Ruff tool failure: exit={check_proc.returncode}")
    try:
        raw_findings = json.loads(check_proc.stdout)
    except json.JSONDecodeError as error:
        raise QualityProfileError("Ruff emitted malformed JSON output") from error
    if not isinstance(raw_findings, list):
        raise QualityProfileError("Ruff output is not a finding list")

    findings: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            raise QualityProfileError("Ruff finding entry is not a dictionary")
        code = str(item.get("code", ""))
        if not code.startswith("F"):
            raise QualityProfileError(f"Ruff reported non-F violation: {code}")
        raw_file = Path(str(item.get("filename", "")))
        full_file = raw_file if raw_file.is_absolute() else repo_root / raw_file
        try:
            rel = full_file.resolve().relative_to(root_resolved).as_posix()
        except ValueError as error:
            raise QualityProfileError("Ruff reported finding outside repository root") from error
        if rel not in paths:
            raise QualityProfileError("Ruff finding outside selected paths")
        findings.append({
            "path": rel, "code": code,
            "message": str(item.get("message", "")), "location": item.get("location"),
        })
    if check_proc.returncode == 1 and not findings:
        raise QualityProfileError("Ruff exited with error but reported no findings")
    return ("failed" if findings else "passed"), findings


def _outcome_dict(status: str, findings: list[dict[str, Any]], **extra: object) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status, "count": len(findings), "findings": findings, "completed": True,
    }
    result.update(extra)
    return result



def check_paths(
    paths: tuple[str, ...], repo_root: Path, *, raise_on_error: bool = True,
) -> dict[str, Any]:
    """Check non-product Python quality profiles without grandfathering."""
    start_time = time.monotonic()
    if not paths:
        clean = _outcome_dict("passed", [])
        clean_fl = _outcome_dict("passed", [], limit=MAX_PHYSICAL_LINES)
        duration = round(time.monotonic() - start_time, 4)
        return {
            "schema": SCHEMA, "status": "passed", "paths": [], "analyzed_paths": [],
            "duration_seconds": duration, "ruff": clean, "mypy": clean, "file_length": clean_fl,
            "checks": {"ruff": clean, "mypy": clean, "file_length": clean_fl},
        }

    fl_d: dict[str, Any] | None = None
    ruff_d: dict[str, Any] | None = None
    mypy_d: dict[str, Any] | None = None
    tool_error: Exception | None = None
    failure_category = "input"

    try:
        resolved_pairs = [_resolve_path(p, repo_root) for p in paths]
        failure_category = "prerequisite"
        for tool, expected in EXPECTED_TOOLS.items():
            actual = importlib.metadata.version(tool)
            if actual != expected:
                raise QualityProfileError(f"unexpected {tool} version: {actual!r} != {expected!r}")
        failure_category = "execution"
        unique_rel_paths = tuple(dict.fromkeys(rel for _, rel in resolved_pairs))
        deduped_pairs = []
        seen: set[str] = set()
        for full, rel in resolved_pairs:
            if rel in unique_rel_paths and rel not in seen:
                seen.add(rel)
                deduped_pairs.append((full, rel))

        try:
            fl_status, fl_findings = _check_file_lengths(deduped_pairs)
            fl_d = _outcome_dict(fl_status, fl_findings, limit=MAX_PHYSICAL_LINES)
        except Exception as error:
            tool_error = error
            fl_d = _outcome_dict("failed", [], limit=MAX_PHYSICAL_LINES, error=str(error), completed=False)

        if tool_error is None:
            try:
                ruff_status, ruff_findings = _check_ruff(unique_rel_paths, repo_root)
                ruff_d = _outcome_dict(ruff_status, ruff_findings)
            except Exception as error:
                tool_error = error
                ruff_d = _outcome_dict("failed", [], error=str(error), completed=False)

        if tool_error is None:
            try:
                mypy_status, mypy_findings = _check_mypy(unique_rel_paths, repo_root)
                mypy_d = _outcome_dict(mypy_status, mypy_findings)
            except Exception as error:
                tool_error = error
                mypy_d = _outcome_dict("failed", [], error=str(error), completed=False)

    except (QualityProfileError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError, KeyError, ValueError) as error:
        tool_error = error

    duration = round(time.monotonic() - start_time, 4)
    if tool_error is not None:
        if raise_on_error:
            raise tool_error
        fail = _outcome_dict("failed", [], completed=False)
        fail_fl = _outcome_dict("failed", [], limit=MAX_PHYSICAL_LINES, completed=False)
        checks_map = {
            "ruff": ruff_d if ruff_d is not None else fail,
            "mypy": mypy_d if mypy_d is not None else fail,
            "file_length": fl_d if fl_d is not None else fail_fl,
        }
        return {
            "schema": SCHEMA, "status": "failed", "paths": list(paths), "analyzed_paths": [],
            "classification": "tool-failure", "tool_failure": type(tool_error).__name__,
            "failure_category": failure_category, "unknown_paths": list(paths),
            "completed_checks": [name for name, check in checks_map.items() if check["completed"]],
            "message": str(tool_error), "duration_seconds": duration,
            "ruff": checks_map["ruff"], "mypy": checks_map["mypy"], "file_length": checks_map["file_length"],
            "checks": checks_map,
        }

    assert fl_d is not None and ruff_d is not None and mypy_d is not None
    overall = "passed" if (fl_d["status"] == "passed" and ruff_d["status"] == "passed" and mypy_d["status"] == "passed") else "failed"
    checks_map = {"ruff": ruff_d, "mypy": mypy_d, "file_length": fl_d}
    return {
        "schema": SCHEMA, "status": overall,
        "paths": list(unique_rel_paths), "analyzed_paths": list(unique_rel_paths),
        "requested_identities": {path: _canonical_import_identity(path, repo_root) for path in unique_rel_paths},
        "unknown_paths": [], "completed_checks": list(checks_map),
        "duration_seconds": duration, "ruff": ruff_d, "mypy": mypy_d, "file_length": fl_d,
        "checks": checks_map,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run clean non-product Python quality checks.")
    parser.add_argument("paths", nargs="*", help="paths to check")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def render_text(result: Mapping[str, object]) -> str:
    analyzed = result.get("analyzed_paths")
    count = len(analyzed) if isinstance(analyzed, list) else 0
    lines = [f"python-quality-profiles: {result.get('status')}", f"analyzed paths: {count}"]
    for check in ("file_length", "ruff", "mypy"):
        sub = result.get(check)
        if isinstance(sub, dict):
            lines.append(f"  {check}: {sub.get('status')} (findings: {sub.get('count', 0)})")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = args.repo_root.resolve()
        result = check_paths(tuple(args.paths), repo_root)
        print(json.dumps(result, indent=2, sort_keys=True) if args.format == "json" else render_text(result))
        return 0 if result["status"] == "passed" else 1
    except (QualityProfileError, Exception) as error:
        failure = {
            "schema": SCHEMA, "status": "failed", "classification": "tool-failure",
            "tool_failure": type(error).__name__, "message": str(error),
        }
        if args.format == "json":
            print(json.dumps(failure, indent=2, sort_keys=True))
        else:
            print(f"python-quality-profiles: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
