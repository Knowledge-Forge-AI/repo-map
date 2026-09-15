"""Check definitions and execution attestation for pre-review suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.pre_review_records import ROOT, Check


def checks(scratch_dir: Path, tool_root: Path | None = None) -> tuple[Check, ...]:
    """Assemble the configured inventory of pre-review checks."""
    python = sys.executable
    native = tool_root / "bin" if tool_root is not None else None
    python_bin = tool_root / "python" / "bin" if tool_root is not None else None
    node = (
        tool_root / "node" / "node_modules" / ".bin"
        if tool_root is not None else None
    )

    def executable(name: str, owner: Path | None = native) -> str:
        return str(owner / name) if owner is not None else name

    workflows = tuple(str(path) for path in sorted((ROOT / ".github/workflows").glob("*.yml")))
    dockerfiles = tuple(
        str(ROOT / path)
        for path in subprocess.run(
            ["git", "ls-files", "*Dockerfile", "Dockerfile*"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if path
    )
    ruff_roots = (
        "src/main/python",
        "src/test/conftest.py",
        "src/test/support/python",
        "src/test/unit/python",
        "src/test/int/python",
        "tools",
    )
    return (
        Check("ruff", (python, "-m", "ruff", "check", *ruff_roots), python_owned=True),
        Check(
            "pyflakes",
            (
                python,
                "-m",
                "ruff",
                "check",
                "--select",
                "F",
                "src/main/python/repomap_kg/runtime",
                "src/main/python/repomap_kg/graph",
                "src/main/python/repomap_kg/server",
            ),
            python_owned=True,
        ),
        Check(
            "mypy",
            (
                python,
                "tools/ci/python_type_check.py",
                "--manifest",
                "tools/ci/python_type_ownership.json",
            ),
            python_owned=True,
        ),
        Check(
            "retained-python-ratchets",
            (
                python,
                "tools/ci/retained_python_ratchets.py",
                "--baseline",
                "tools/ci/retained_python_ratchets.json",
                "--scope-transitions",
                "tools/ci/retained_python_scope_transitions.json",
            ),
            policy="retained-python-ratchets",
            python_owned=True,
        ),
        Check(
            "python-retention-inventory",
            (python, "tools/ci/python_retention_inventory.py", "--check", "--json"),
            python_owned=True,
        ),
        Check("ci-topology", (python, "tools/ci/ci_topology.py"), python_owned=True),
        Check(
            "file-length",
            (python, "tools/ci/check_file_lengths.py", "--format", "json"),
            policy="file-length",
            python_owned=True,
        ),
        Check(
            "python-compile",
            (
                python, "-m", "compileall", "-q", "src/main/python",
                "src/test/support/python", "src/test/unit/python",
                "src/test/int/python", "tools",
            ),
            python_owned=True,
        ),
        Check("actionlint", (executable("actionlint"), "-format", "{{json .}}", *workflows)),
        Check("zizmor", (executable("zizmor"), "--offline", "--format", "json", ".github/workflows"), policy="zizmor"),
        Check(
            "pip-audit",
            (
                python,
                "-m",
                "pip_audit",
                "--disable-pip",
                "--no-deps",
                "--requirement",
                "tools/ci/project_dependencies.lock",
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ),
            policy="pip-audit",
            python_owned=True,
        ),
        Check("govulncheck", (executable("govulncheck"), "-json", "./..."), cwd=ROOT / "src/main/go"),
        Check(
            "semgrep",
            (
                executable("semgrep", python_bin),
                "scan",
                "--config",
                "tools/ci/semgrep.yml",
                "--json",
                "--error",
                "--metrics",
                "off",
                "src/main/python",
                "tools",
            ),
            python_owned=True,
            python_entry="console-script",
        ),
        Check(
            "betterleaks",
            (
                executable("betterleaks"),
                "dir",
                "src/main",
                "tools",
                ".github",
                "docs/adr",
                "docs/contrib",
                "docs/ops",
                "docs/testing",
                "README.md",
                "AGENTS.md",
                "CLAUDE.md",
                "pyproject.toml",
                "--no-banner",
                "--redact=100",
                "--report-format=json",
                "--report-path=-",
            ),
        ),
        Check("malskanner", (executable("malskanner", node), ".", "--json"), policy="malskanner"),
        Check("prompt-defense-audit", (python, "tools/ci/prompt_defense_check.py"), python_owned=True),
        Check("scanner-suppressions", (python, "tools/ci/scanner_suppressions.py"), policy="suppressions", python_owned=True),
        Check("liquibase", (python, "tools/ci/liquibase_check.py"), python_owned=True),
        Check("hadolint", (executable("hadolint"), "--format", "json", *dockerfiles), policy="hadolint"),
        Check(
            "generated-code-drift",
            (
                python,
                "tools/ci/check_generated_drift.py",
                "--uv",
                executable("uv"),
                "--evidence-dir",
                str(scratch_dir / "generated-code-drift"),
            ),
            python_owned=True,
        ),
    )


def _interpreter(check: Check) -> str | None:
    return "<tool-python>" if check.python_owned else None


def _attest_check_owner(check: Check, tool_root: Path | None) -> None:
    if not check.python_owned:
        return
    actual = Path(check.command[0]).resolve()
    if check.python_entry == "interpreter":
        if actual != Path(sys.executable).resolve():
            raise RuntimeError("Python check does not use the aggregate interpreter")
        return
    if check.python_entry == "console-script":
        if tool_root is None:
            raise RuntimeError("Python console check has no sealed tool root")
        expected_parent = (tool_root / "python" / "bin").resolve()
        if actual.parent != expected_parent:
            raise RuntimeError("Python console check is outside the sealed environment")
        return
    raise RuntimeError("Python check has an invalid entrypoint classification")


def _command_attestation(check: Check, tool_root: Path | None) -> str:
    command = list(check.command)
    if tool_root is not None:
        python_bin = str((tool_root / "python" / "bin").resolve())
        executable = str(Path(command[0]).resolve())
        if executable.startswith(python_bin + os.sep):
            command[0] = "<tool-python-bin>/" + Path(command[0]).name
    return json.dumps(command)


def _attest_python_owner(tool_root: Path) -> None:
    expected = (tool_root / "python" / "bin" / "python").resolve()
    if Path(sys.executable).resolve() != expected:
        raise RuntimeError("aggregate interpreter is not the sealed tool Python")
