#!/usr/bin/env python3
"""Materialize the closed pre-review toolchain into one run-owned root."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.bootstrap_tool import host_platform, install_tool, load_manifest, verified_payload


CI_ROOT = Path(__file__).resolve().parent
NATIVE_TOOLS = ("actionlint", "zizmor", "betterleaks", "hadolint", "uv")


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=env)


def verify_version(command: list[str], expected: str) -> None:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    if expected not in completed.stdout + completed.stderr:
        raise RuntimeError(f"tool version attestation failed for {command[0]}")


def verify_python_distribution(
    python: Path,
    module_name: str,
    distribution_name: str,
    expected_version: str,
    owner_root: Path,
) -> None:
    script = "\n".join(
        (
            "import importlib",
            "import importlib.metadata",
            "import json",
            "from pathlib import Path",
            "import sys",
            "module = importlib.import_module(sys.argv[1])",
            "origin = Path(module.__file__).resolve()",
            "owner = Path(sys.argv[4]).resolve()",
            "print(json.dumps({'version': importlib.metadata.version(sys.argv[2]), "
            "'owned': origin.is_relative_to(owner)}, sort_keys=True))",
        )
    )
    completed = subprocess.run(
        [
            str(python),
            "-c",
            script,
            module_name,
            distribution_name,
            expected_version,
            str(owner_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if payload != {"owned": True, "version": expected_version}:
        raise RuntimeError(
            f"sealed Python dependency attestation failed for {distribution_name}"
        )


def extract_distribution(payload: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("distribution archive escapes its tool root")
        archive.extractall(destination, filter="data")


def install_liquibase(tool_root: Path) -> Path:
    manifest = load_manifest()
    asset = manifest["tools"]["liquibase"]["assets"][host_platform()]
    destination = tool_root / "liquibase"
    extract_distribution(verified_payload(asset), destination)
    executable = destination / "liquibase"
    executable.chmod(executable.stat().st_mode | 0o100)
    return destination


def bootstrap(tool_root: Path) -> tuple[Path, ...]:
    tool_root.mkdir(parents=True, exist_ok=True)
    bin_dir = tool_root / "bin"
    for name in NATIVE_TOOLS:
        install_tool(name, bin_dir)

    python_root = tool_root / "python"
    run([sys.executable, "-m", "venv", str(python_root)])
    run(
        [
            str(python_root / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--no-deps",
            "--requirement",
            str(CI_ROOT / "pre_review_python.lock"),
        ]
    )
    run(
        [
            str(python_root / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--no-deps",
            "--requirement",
            str(CI_ROOT / "project_dependencies.lock"),
        ]
    )

    go_env = dict(os.environ)
    go_env["GOBIN"] = str(bin_dir)
    run(
        [
            "go",
            "install",
            "golang.org/x/vuln/cmd/govulncheck@v1.1.4",
        ],
        env=go_env,
    )

    node_root = tool_root / "node"
    node_root.mkdir()
    shutil.copy2(CI_ROOT / "pre_review_node" / "package.json", node_root)
    shutil.copy2(CI_ROOT / "pre_review_node" / "package-lock.json", node_root)
    run(
        [
            "npm",
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--prefix",
            str(node_root),
        ]
    )

    liquibase_root = install_liquibase(tool_root)
    verify_version([str(bin_dir / "actionlint"), "-version"], "1.7.12")
    verify_version([str(bin_dir / "zizmor"), "--version"], "1.29.0")
    verify_version([str(bin_dir / "betterleaks"), "version"], "1.8.1")
    verify_version([str(bin_dir / "hadolint"), "--version"], "2.15.1")
    verify_version([str(bin_dir / "uv"), "--version"], "0.9.30")
    verify_version([str(bin_dir / "govulncheck"), "-version"], "1.1.4")
    verify_version([str(python_root / "bin" / "ruff"), "--version"], "0.16.2")
    verify_version([str(python_root / "bin" / "mypy"), "--version"], "2.1.0")
    verify_version([str(python_root / "bin" / "pip-audit"), "--version"], "2.10.1")
    verify_version([str(python_root / "bin" / "semgrep"), "--version"], "1.174.0")
    for module, distribution, version in (
        ("psycopg", "psycopg", "3.2.12"),
        ("typing_extensions", "typing-extensions", "4.16.0"),
    ):
        verify_python_distribution(
            python_root / "bin" / "python",
            module,
            distribution,
            version,
            python_root,
        )
    verify_version(
        [str(node_root / "node_modules" / ".bin" / "malskanner"), "--version"],
        "0.1.1",
    )
    verify_version(
        [
            str(node_root / "node_modules" / ".bin" / "prompt-defense-audit"),
            "--version",
        ],
        "1.8.1",
    )
    verify_version([str(liquibase_root / "liquibase"), "--version"], "5.0.1")
    return (
        bin_dir,
        python_root / "bin",
        node_root / "node_modules" / ".bin",
        liquibase_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-root", required=True, type=Path)
    args = parser.parse_args(argv)
    paths = bootstrap(args.tool_root)
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with Path(github_path).open("a", encoding="utf-8") as path_file:
            for path in paths:
                path_file.write(f"{path}\n")
    for path in paths:
        print(f"pre-review tool path: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
