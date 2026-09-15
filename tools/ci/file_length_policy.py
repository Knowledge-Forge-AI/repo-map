"""Deterministic tracked-Python file-length policy."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence


PROFILE_NAME = "file-length"
PROTOCOL_VERSION = 1
WARNING_LIMIT = 400
FAILURE_LIMIT = 1000
GIT_PATHS = ("src/main/python", "src/test", "tools")
EXPECTED_LAYOUT = (
    "pyproject.toml",
    "src/main/python",
    "src/test",
    "tools",
)
Severity = Literal["warning", "failure"]
Status = Literal["passed", "passed_with_warnings", "failed"]


class FileLengthOperationalError(RuntimeError):
    """Report an operational failure separately from a policy finding."""


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A repository-relative Python path and its physical line count."""

    path: str
    line_count: int


@dataclass(frozen=True, slots=True)
class Finding:
    """A warning or failure emitted by the file-length profile."""

    path: str
    line_count: int
    severity: Severity

    def to_jsonable(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "line_count": self.line_count,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class FileLengthResult:
    """The stable result contract for one completed repository scan."""

    status: Status
    scanned_file_count: int
    warning_count: int
    failure_count: int
    findings: tuple[Finding, ...]

    def to_jsonable(self) -> dict[str, object]:
        return {
            "version": PROTOCOL_VERSION,
            "profile": PROFILE_NAME,
            "status": self.status,
            "warning_limit": WARNING_LIMIT,
            "failure_limit": FAILURE_LIMIT,
            "scanned_file_count": self.scanned_file_count,
            "warning_count": self.warning_count,
            "failure_count": self.failure_count,
            "findings": [finding.to_jsonable() for finding in self.findings],
        }


def _run_git(repo_root: Path, arguments: Sequence[str], operation: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise FileLengthOperationalError(
            f"unable to run Git while {operation}"
        ) from error
    if completed.returncode != 0:
        raise FileLengthOperationalError(f"Git failed while {operation}")
    return completed.stdout


def validate_repo_root(repo_root: Path) -> Path:
    """Return a resolved RepoMap worktree root or raise a bounded diagnostic."""
    try:
        candidate = repo_root.expanduser()
    except (OSError, RuntimeError) as error:
        raise FileLengthOperationalError(
            "unable to resolve repository root"
        ) from error
    if not candidate.is_dir():
        raise FileLengthOperationalError("repository root is not a directory")
    try:
        candidate = candidate.resolve()
    except OSError as error:
        raise FileLengthOperationalError(
            "unable to resolve repository root"
        ) from error
    for relative_path in EXPECTED_LAYOUT:
        expected = candidate / relative_path
        if not expected.exists():
            raise FileLengthOperationalError(
                "repository root is missing the expected RepoMap layout"
            )

    top_level_bytes = _run_git(
        candidate,
        ("rev-parse", "--show-toplevel"),
        "validating the Git worktree root",
    )
    try:
        top_level = Path(top_level_bytes.decode("utf-8").strip()).resolve()
    except UnicodeError as error:
        raise FileLengthOperationalError("Git returned a non-UTF-8 worktree root") from error
    if top_level != candidate:
        raise FileLengthOperationalError(
            "repository root must be the root of a Git worktree"
        )
    return candidate


def _is_approved_python_path(path: PurePosixPath) -> bool:
    if path.is_absolute() or path.suffix != ".py" or ".." in path.parts:
        return False
    parts = path.parts
    return (
        parts[:3] == ("src", "main", "python")
        or parts[:2] == ("src", "test")
        or parts[:1] == ("tools",)
    )


def discover_tracked_python_paths(repo_root: Path) -> list[PurePosixPath]:
    """Return the sorted Git-tracked Python paths in the approved scope."""
    output = _run_git(
        repo_root,
        ("ls-files", "-z", "--", *GIT_PATHS),
        "discovering tracked Python files",
    )
    paths: list[PurePosixPath] = []
    for encoded_path in output.split(b"\0"):
        if not encoded_path:
            continue
        try:
            path = PurePosixPath(encoded_path.decode("utf-8"))
        except UnicodeError as error:
            raise FileLengthOperationalError(
                "Git returned a non-UTF-8 tracked path"
            ) from error
        if _is_approved_python_path(path):
            paths.append(path)
    return sorted(paths, key=lambda path: path.as_posix())


def resolve_tracked_path(repo_root: Path, relative_path: PurePosixPath) -> Path:
    """Resolve one tracked path without following an escaping symlink."""
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise FileLengthOperationalError("tracked path escapes the repository root")
    candidate = repo_root.joinpath(*relative_path.parts)
    if candidate.is_symlink():
        raise FileLengthOperationalError("tracked Python path is a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise FileLengthOperationalError(
            "tracked Python path is not a regular file"
        ) from error
    except ValueError as error:
        raise FileLengthOperationalError(
            "tracked path escapes the repository root"
        ) from error
    if not resolved.is_file():
        raise FileLengthOperationalError("tracked Python path is not a regular file")
    return resolved


def count_physical_lines(path: Path) -> int:
    """Count LF-delimited physical lines without native newline translation."""
    line_count = 0
    final_byte: int | None = None
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            line_count += chunk.count(b"\n")
            final_byte = chunk[-1]
    if final_byte is not None and final_byte != ord("\n"):
        line_count += 1
    return line_count


def classify_line_count(line_count: int) -> Severity | None:
    """Classify exact warning and failure boundaries."""
    if line_count > FAILURE_LIMIT:
        return "failure"
    if line_count > WARNING_LIMIT:
        return "warning"
    return None


def build_result(scanned_files: Sequence[ScannedFile]) -> FileLengthResult:
    """Build the stable result contract from completed file counts."""
    findings = []
    for scanned_file in scanned_files:
        severity = classify_line_count(scanned_file.line_count)
        if severity is not None:
            findings.append(
                Finding(scanned_file.path, scanned_file.line_count, severity)
            )
    findings.sort(key=lambda finding: finding.path)
    warning_count = sum(finding.severity == "warning" for finding in findings)
    failure_count = sum(finding.severity == "failure" for finding in findings)
    if failure_count:
        status: Status = "failed"
    elif warning_count:
        status = "passed_with_warnings"
    else:
        status = "passed"
    return FileLengthResult(
        status=status,
        scanned_file_count=len(scanned_files),
        warning_count=warning_count,
        failure_count=failure_count,
        findings=tuple(findings),
    )


def scan_repository(repo_root: Path) -> FileLengthResult:
    """Scan all eligible tracked Python files beneath a validated root."""
    scanned_files = []
    for relative_path in discover_tracked_python_paths(repo_root):
        try:
            source_path = resolve_tracked_path(repo_root, relative_path)
            line_count = count_physical_lines(source_path)
        except FileLengthOperationalError:
            raise
        except OSError as error:
            raise FileLengthOperationalError(
                "unable to read tracked Python file"
            ) from error
        scanned_files.append(ScannedFile(relative_path.as_posix(), line_count))
    return build_result(scanned_files)


def render_json(result: FileLengthResult) -> str:
    """Render one deterministic UTF-8-compatible JSON document."""
    return json.dumps(result.to_jsonable(), indent=2, sort_keys=True) + "\n"


def _escape_text_path(path: str) -> str:
    return json.dumps(path, ensure_ascii=True)[1:-1]


def render_text(result: FileLengthResult) -> str:
    """Render the concise deterministic human-readable report."""
    status_text = {
        "passed": "passed",
        "passed_with_warnings": "passed with warnings",
        "failed": "failed",
    }[result.status]
    lines = [
        f"file-length: {status_text}",
        f"limits: warning >{WARNING_LIMIT}, failure >{FAILURE_LIMIT}",
        f"scanned: {result.scanned_file_count} Python files",
        f"warnings: {result.warning_count}",
        f"failures: {result.failure_count}",
    ]
    if result.findings:
        lines.append("")
        severity_order = {"failure": 0, "warning": 1}
        ordered_findings = sorted(
            result.findings,
            key=lambda finding: (
                severity_order[finding.severity],
                -finding.line_count,
                finding.path,
            ),
        )
        lines.extend(
            f"{finding.severity.upper():<7}  {finding.line_count:>4}  "
            f"{_escape_text_path(finding.path)}"
            for finding in ordered_findings
        )
    return "\n".join(lines) + "\n"
