#!/usr/bin/env python3
"""Public export policy: enforces release qualification and publication boundaries.

Enforces five core release conditions:
1. Withheld paths (docs/status/** and docs/superpowers/**) must remain absent.
2. Version consistency across package manifests and Python package metadata.
3. Promotion policy: only same-repository ``staging`` may target ``main``.
4. Candidate identity binding: merge commit, tree, and parent references match expectations.
5. Retention independence: retention authorities do not depend on withheld status docs on disk.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

DEFAULT_TARGET_VERSION = "0.0.1"
WITHHELD_DIRECTORIES = ("docs/status", "docs/superpowers")


def check_withheld_paths(repo_root: Path) -> list[str]:
    """Verify that withheld directories and files are absent from the working tree."""
    violations: list[str] = []
    for withheld in WITHHELD_DIRECTORIES:
        target = repo_root / withheld
        if target.exists():
            violations.append(f"withheld path exists on disk: {withheld}")

    try:
        result = subprocess.run(
            ["git", "ls-files", *WITHHELD_DIRECTORIES],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            tracked = result.stdout.strip().splitlines()
            violations.append(
                f"withheld files tracked in git ({len(tracked)}): {tracked[:3]}"
            )
    except (FileNotFoundError, OSError):
        pass

    return violations


def check_version_consistency(
    repo_root: Path,
    expected_version: str = DEFAULT_TARGET_VERSION,
) -> list[str]:
    """Verify version consistency between pyproject.toml and repomap_kg.__version__."""
    violations: list[str] = []

    pyproject_path = repo_root / "pyproject.toml"
    pyproject_version: str | None = None
    if not pyproject_path.is_file():
        violations.append("pyproject.toml is missing")
    else:
        text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
        if not match:
            violations.append("could not parse version from pyproject.toml")
        else:
            pyproject_version = match.group(1)

    init_path = repo_root / "src/main/python/repomap_kg/__init__.py"
    init_version: str | None = None
    if not init_path.is_file():
        violations.append("src/main/python/repomap_kg/__init__.py is missing")
    else:
        text = init_path.read_text(encoding="utf-8")
        match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
        if not match:
            violations.append("could not parse __version__ from repomap_kg/__init__.py")
        else:
            init_version = match.group(1)

    if pyproject_version and pyproject_version != expected_version:
        violations.append(
            f"pyproject.toml version {pyproject_version!r} does not match "
            f"expected target version {expected_version!r}"
        )

    if init_version and init_version != expected_version:
        violations.append(
            f"repomap_kg.__version__ {init_version!r} does not match "
            f"expected target version {expected_version!r}"
        )

    if (
        pyproject_version
        and init_version
        and pyproject_version != init_version
    ):
        violations.append(
            f"version mismatch: pyproject.toml has {pyproject_version!r} "
            f"while repomap_kg.__version__ has {init_version!r}"
        )

    return violations


def check_promotion_policy(
    payload: Mapping[str, Any],
    repository: str,
) -> list[str]:
    """Verify that a pull request promotion conforms to same-repo staging -> main policy."""
    violations: list[str] = []
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, Mapping):
        violations.append("event payload has no pull_request object")
        return violations

    base = pull_request.get("base") or {}
    head = pull_request.get("head") or {}
    base_ref = str(base.get("ref", ""))
    head_ref = str(head.get("ref", ""))
    head_repo = (head.get("repo") or {}).get("full_name")
    head_repository = "" if head_repo is None else str(head_repo)

    if base_ref != "main":
        violations.append(
            f"policy applies only to pull requests targeting 'main', got base {base_ref!r}"
        )
    if repository and head_repository != repository:
        violations.append(
            f"head must come from {repository!r}, got {head_repository!r}"
        )
    if head_ref != "staging":
        violations.append(
            f"only 'staging' may promote to 'main', got head {head_ref!r}"
        )

    return violations


def check_candidate_identity(
    repo_root: Path,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> list[str]:
    """Verify git candidate identity and merge topology if git is available."""
    violations: list[str] = []
    if not (expected_commit or expected_tree or base_sha or head_sha):
        return violations

    def _git(*args: str) -> str | None:
        try:
            res = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            return res.stdout.strip() if res.returncode == 0 else None
        except (FileNotFoundError, OSError):
            return None

    head = _git("rev-parse", "HEAD")
    if head is None:
        violations.append("failed to resolve git HEAD")
        return violations

    if expected_commit and head != expected_commit:
        violations.append(
            f"candidate HEAD {head!r} does not match expected commit {expected_commit!r}"
        )

    if expected_tree:
        tree = _git("rev-parse", "HEAD^{tree}")
        if tree != expected_tree:
            violations.append(
                f"candidate tree {tree!r} does not match expected tree {expected_tree!r}"
            )

    if base_sha:
        parent1 = _git("rev-parse", "HEAD^1")
        if parent1 != base_sha:
            violations.append(
                f"candidate base parent HEAD^1 {parent1!r} does not match expected base {base_sha!r}"
            )

    if head_sha:
        parent2 = _git("rev-parse", "HEAD^2")
        if parent2 != head_sha:
            violations.append(
                f"candidate head parent HEAD^2 {parent2!r} does not match expected head {head_sha!r}"
            )

    return violations


def check_retention_independence(repo_root: Path) -> list[str]:
    """Verify that public retention authority operates independently of withheld trees."""
    violations: list[str] = []

    tools_ci = repo_root / "tools/ci"
    if tools_ci.is_dir():
        hist_manifests_path = tools_ci / "historical_ownership_manifests.json"
        if not hist_manifests_path.is_file():
            violations.append(
                "historical ownership manifests file is missing: tools/ci/historical_ownership_manifests.json"
            )

    inventory_path = repo_root / "tools/ci/python_retention_inventory.json"
    ratchet_path = repo_root / "tools/ci/retained_python_ratchets.json"
    if inventory_path.is_file() and ratchet_path.is_file():
        try:
            tools_dir = repo_root / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from ci.python_retention_authorities import bind_inputs
            bindings = bind_inputs(repo_root, inventory_path, ratchet_path)
            for path_key in bindings:
                for withheld in WITHHELD_DIRECTORIES:
                    if path_key.startswith(withheld):
                        violations.append(
                            f"public retention authority binds withheld path: {path_key}"
                        )
        except Exception as error:
            violations.append(f"failed to verify retention authority bindings: {error}")

    return violations


def evaluate_public_export(
    repo_root: Path,
    *,
    payload: Mapping[str, Any] | None = None,
    repository: str = "",
    expected_version: str = DEFAULT_TARGET_VERSION,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> list[str]:
    """Evaluate all applicable public export policy contracts."""
    violations: list[str] = []
    violations.extend(check_withheld_paths(repo_root))
    violations.extend(check_version_consistency(repo_root, expected_version))
    violations.extend(check_retention_independence(repo_root))

    if payload is not None:
        violations.extend(check_promotion_policy(payload, repository))

    violations.extend(
        check_candidate_identity(
            repo_root,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
            base_sha=base_sha,
            head_sha=head_sha,
        )
    )
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root to inspect",
    )
    parser.add_argument(
        "--expected-version",
        default=DEFAULT_TARGET_VERSION,
        help="expected semver version (default: 0.0.1)",
    )
    parser.add_argument(
        "--event-path",
        default=os.environ.get("GITHUB_EVENT_PATH", ""),
        help="path to GitHub event payload JSON",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="expected repository name (e.g. Knowledge-Forge-AI/repo-map)",
    )
    parser.add_argument("--expected-commit", default=os.environ.get("CANDIDATE_COMMIT"))
    parser.add_argument("--expected-tree", default=os.environ.get("CANDIDATE_TREE"))
    parser.add_argument("--base-sha", default=os.environ.get("BASE_SHA"))
    parser.add_argument("--head-sha", default=os.environ.get("HEAD_SHA"))

    args = parser.parse_args(argv)

    payload: Mapping[str, Any] | None = None
    if args.event_path and Path(args.event_path).is_file():
        try:
            payload = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            print(f"Failed to read event payload: {err}", file=sys.stderr)
            return 1

    violations = evaluate_public_export(
        args.repo_root,
        payload=payload,
        repository=args.repository,
        expected_version=args.expected_version,
        expected_commit=args.expected_commit,
        expected_tree=args.expected_tree,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )

    for violation in violations:
        print(f"Public export policy violation: {violation}", file=sys.stderr)

    if violations:
        return 1

    print("Public export policy contracts hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
