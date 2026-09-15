"""Pinned mypy execution, canonical module identity, and target attestation."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Any, Sequence

from ci.retained_python_ratchets import EXPECTED_MYPY_CONFIG


class QualityProfileError(RuntimeError):
    """A tool, path, or output violated the quality profile contract."""


MYPY_ERROR = re.compile(
    r"^(?P<path>.+?)(?::(?P<line>\d+))?(?::(?P<col>\d+))?: error: "
    r"(?P<message>.*?)(?:\s\s\[(?P<code>[^]]+)])?$"
)


def _prepare_mypy_env(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    roots = (repo_root / "src/main/python", repo_root / "tools",
             repo_root / "src/test/support/python")
    existing = [str(p.resolve()) for p in roots if p.is_dir()]
    env["MYPYPATH"] = os.pathsep.join(existing)
    return env


def _canonical_import_identity(path_str: str, repo_root: Path) -> str:
    full_path = (repo_root / path_str).resolve()
    roots = (repo_root / "src/main/python", repo_root / "tools", repo_root / "src/test/support/python")
    base = next((r.resolve() for r in roots if r.is_dir() and full_path.is_relative_to(r.resolve())), repo_root.resolve())
    # System tooling is imported as tools.system by its runner and consumers.
    if path_str.startswith("tools/system/"):
        base = repo_root.resolve()
    rel = full_path.relative_to(base)
    parts = list(rel.parts)
    # Mypy starts a new import base after a directory that is not an identifier.
    invalid = [index for index, component in enumerate(parts[:-1]) if not component.isidentifier()]
    if invalid:
        parts = parts[invalid[-1] + 1:]
    if not parts:
        return ""
    stem = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    parts = parts[:-1] if stem == "__init__" else parts[:-1] + [stem]
    return ".".join(parts)


def _attest_sources(output: str, batch: Sequence[str], repo_root: Path) -> None:
    expected = {_canonical_import_identity(path, repo_root): (repo_root / path).resolve()
                for path in batch}
    observed: dict[str, Path] = {}
    for line in output.splitlines():
        match = re.match(r"^LOG:\s+Parsing (.+) \((.+)\)$", line)
        if match and match[2] in expected:
            path = Path(match[1])
            observed[match[2]] = (path if path.is_absolute() else repo_root / path).resolve()
    if observed != expected:
        raise QualityProfileError("mypy failed exact requested-path and module-identity attestation")


def _check_mypy(paths: Sequence[str], repo_root: Path) -> tuple[str, list[dict[str, Any]]]:
    py_exe = sys.executable
    env = _prepare_mypy_env(repo_root)
    root_resolved = repo_root.resolve()
    pyproject = repo_root / "pyproject.toml"
    base_cmd = [
        py_exe, "-m", "mypy", "--scripts-are-modules", "--explicit-package-bases",
        "--follow-imports=normal", "--no-error-summary", "--cache-dir=/dev/null", "--verbose",
    ]
    if pyproject.is_file():
        configured = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["mypy"]
        if configured != EXPECTED_MYPY_CONFIG:
            raise QualityProfileError("mypy configuration changed")
        base_cmd.extend(("--config-file", str(pyproject), "--check-untyped-defs"))
    else:
        base_cmd.extend((
            "--python-version=3.12", "--check-untyped-defs", "--no-implicit-optional",
            "--warn-redundant-casts", "--warn-unused-ignores", "--warn-unreachable",
            "--strict-equality", "--show-error-codes",
        ))

    findings: list[dict[str, Any]] = []
    batches: list[list[str]] = []
    identities: list[set[str]] = []
    system_paths = [path for path in paths if path.startswith("tools/system/")]
    for path in paths:
        if path in system_paths:
            continue
        module_id = _canonical_import_identity(path, repo_root)
        slot = next((i for i, names in enumerate(identities) if module_id not in names), len(batches))
        if slot == len(batches):
            batches.append([])
            identities.append(set())
        batches[slot].append(path)
        identities[slot].add(module_id)
    if system_paths:
        batches.append(system_paths)

    for batch in batches:
        rel_path = batch[0]
        targets = ([part for path in batch
                    for part in ("-m", _canonical_import_identity(path, repo_root))]
                   if batch is system_paths else [str(repo_root / path) for path in batch])
        proc = subprocess.run(
            [*base_cmd, *targets],
            cwd=repo_root, env=env, capture_output=True, text=True, check=False, timeout=120,
        )
        if proc.returncode not in (0, 1):
            raise QualityProfileError(f"mypy tool failure on {rel_path}: exit={proc.returncode}")
        output = proc.stdout + proc.stderr
        file_findings: list[dict[str, Any]] = []
        for line in output.splitlines():
            match = MYPY_ERROR.match(line)
            if match is None:
                if line.strip() and not (
                    line.startswith(("LOG:", "TRACE:")) or ": note:" in line
                ):
                    raise QualityProfileError("mypy failed without parseable findings: unrecognized output")
                continue
            raw_path = Path(match.group("path"))
            full_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
            try:
                err_rel = full_path.resolve().relative_to(root_resolved).as_posix()
            except ValueError as error:
                raise QualityProfileError("mypy error path outside repository root") from error
            lexical = raw_path if raw_path.is_absolute() else root_resolved / raw_path
            try:
                lexical_rel = lexical.relative_to(root_resolved).as_posix()
            except ValueError as error:
                raise QualityProfileError("mypy finding path alias cannot change ownership") from error
            if ".." in raw_path.parts or lexical_rel != err_rel:
                raise QualityProfileError("mypy finding path alias cannot change ownership")
            line_str = match.group("line")
            finding: dict[str, Any] = {
                "path": err_rel, "line": int(line_str) if line_str else 1,
                "code": match.group("code") or "", "message": match.group("message").strip(),
            }
            if err_rel not in paths:
                finding["dependency"] = True
            file_findings.append(finding)
        if proc.returncode == 1 and not file_findings:
            raise QualityProfileError(f"mypy failed on {rel_path} without parseable findings")
        _attest_sources(output, batch, repo_root)
        findings.extend(file_findings)

    seen_keys: set[tuple[str, int, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for f in findings:
        k = (str(f["path"]), int(f["line"]), str(f["code"]), str(f["message"]))
        if k not in seen_keys:
            seen_keys.add(k)
            deduped.append(f)
    return ("failed" if deduped else "passed"), deduped
