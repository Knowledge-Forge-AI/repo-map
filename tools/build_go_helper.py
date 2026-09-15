#!/usr/bin/env python3
"""Build and validate the RepoMap-owned Go parser helper from source."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
GO_MODULE_ROOT = REPO_ROOT / "src" / "main" / "go"
PACKAGE_ROOT = SOURCE_ROOT / "repomap_kg"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from repomap_kg.extractors.languages.go_helper import (  # noqa: E402
    HELPER_NAME,
    platform_tag,
)


def build_go_helper(
    *,
    repo_root: Path = REPO_ROOT,
    package_root: Path = PACKAGE_ROOT,
    target_platform: str | None = None,
    instrumented: bool = False,
) -> Path:
    if instrumented and package_root.resolve() == PACKAGE_ROOT.resolve():
        raise ValueError(
            "instrumented Go helper build must not use default in-tree package_root"
        )
    module_root = repo_root / "src" / "main" / "go"
    binary_name = f"{HELPER_NAME}.cover" if instrumented else HELPER_NAME
    destination = (
        package_root / "_bin" / (target_platform or platform_tag()) / binary_name
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{binary_name}.",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    build_cmd = ["go", "build"]
    if instrumented:
        build_cmd.extend(["-cover", "-coverpkg=./..."])
    build_cmd.extend([
        "-trimpath",
        "-o",
        str(temporary),
        "./cmd/repomap-go-extract",
    ])
    try:
        subprocess.run(
            tuple(build_cmd),
            cwd=module_root,
            check=True,
        )
        temporary.chmod(0o755)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def run_validation_step(
    step: str,
    command: tuple[str, ...],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run one named validation step, naming the command that actually failed.

    Only the step name, executable name, and exit status are reported, so a
    failure never widens into environment or private-path exposure.
    """
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=capture_output,
            text=capture_output,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            f"Go validation step '{step}' could not start: "
            f"executable {command[0]!r} was not found"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Go validation step '{step}' failed with exit status "
            f"{error.returncode}"
        ) from error


def validate_go_sources(*, repo_root: Path = REPO_ROOT) -> None:
    module_root = repo_root / "src" / "main" / "go"
    with tempfile.TemporaryDirectory(prefix="repomap-go-coverage-") as tmpdir:
        coverage_path = Path(tmpdir) / "coverage.out"
        run_validation_step(
            "go test coverage",
            ("go", "test", f"-coverprofile={coverage_path}", "./..."),
            cwd=module_root,
        )
        coverage = run_validation_step(
            "go tool cover",
            ("go", "tool", "cover", "-func", str(coverage_path)),
            cwd=module_root,
            capture_output=True,
        )
        total_line = coverage.stdout.rstrip().splitlines()[-1]
        total_percent = float(total_line.rsplit(None, 1)[-1].removesuffix("%"))
        if total_percent < 85.0:
            raise RuntimeError(
                f"Go statement coverage {total_percent:.1f}% is below 85.0%"
            )
    for step, command in (
        ("go vet", ("go", "vet", "./...")),
        ("golangci-lint run", ("golangci-lint", "run")),
        ("go race test", ("go", "test", "-race", "./...")),
    ):
        run_validation_step(step, command, cwd=module_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate:
            validate_go_sources()
        helper = build_go_helper()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"ERROR: Go helper build failed: {error}", file=sys.stderr)
        return 1
    print(helper)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
