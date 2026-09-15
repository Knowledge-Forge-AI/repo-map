#!/usr/bin/env python3
"""Regenerate RepoMap-owned locks and fail on tracked byte drift."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = Path(__file__).resolve().parent
PYTHON_LOCKS = (
    ("pre_review_python.in", "pre_review_python.lock"),
    ("project_dependencies.in", "project_dependencies.lock"),
)
POLICY_PATH = CI_ROOT / "generated_lock_policy.json"
PYPI_INDEX = "https://pypi.org/simple"
SUBPROCESS_ENV_ALLOWLIST = (
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "all_proxy",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


class ToolFailure(RuntimeError):
    """A generator could not complete its repository-owned operation."""


@dataclass(frozen=True)
class LockPolicy:
    default_index: str
    exclude_newer: str
    authority_sha256: str


def lock_policy(
    default_index: object,
    exclude_newer: object,
    authority_sha256: object,
) -> LockPolicy:
    if default_index != PYPI_INDEX or not isinstance(exclude_newer, str):
        raise ToolFailure("generated lock policy is invalid")
    if (
        not isinstance(authority_sha256, str)
        or len(authority_sha256) != 64
        or any(character not in "0123456789abcdef" for character in authority_sha256)
    ):
        raise ToolFailure("generated lock authority digest is invalid")
    try:
        cutoff = datetime.fromisoformat(exclude_newer.replace("Z", "+00:00"))
    except ValueError as error:
        raise ToolFailure("generated lock cutoff is invalid") from error
    if not exclude_newer.endswith("Z") or cutoff.tzinfo != timezone.utc:
        raise ToolFailure("generated lock cutoff is invalid")
    return LockPolicy(default_index, exclude_newer, authority_sha256)


def load_lock_policy(path: Path = POLICY_PATH) -> LockPolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolFailure("generated lock policy is unavailable") from error
    if not isinstance(payload, dict) or set(payload) != {
        "authority_sha256",
        "default_index",
        "exclude_newer",
        "version",
    }:
        raise ToolFailure("generated lock policy is invalid")
    if payload["version"] != 1:
        raise ToolFailure("generated lock policy version is unsupported")
    return lock_policy(
        payload["default_index"],
        payload["exclude_newer"],
        payload["authority_sha256"],
    )


def authority_digest(input_root: Path, *, lock_root: Path | None = None) -> str:
    locks = input_root if lock_root is None else lock_root
    digest = hashlib.sha256()
    for source, lock in PYTHON_LOCKS:
        for name, root in ((source, input_root), (lock, locks)):
            for payload in (name.encode(), (root / name).read_bytes()):
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
    return digest.hexdigest()


def policy_bytes(policy: LockPolicy) -> bytes:
    return (
        json.dumps(
            {
                "authority_sha256": policy.authority_sha256,
                "default_index": policy.default_index,
                "exclude_newer": policy.exclude_newer,
                "version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def subprocess_environment(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    clean = {
        key: environ[key]
        for key in SUBPROCESS_ENV_ALLOWLIST
        if environ.get(key)
    }
    clean["PATH"] = environ.get("PATH", os.defpath)
    return clean


def expected_uv_version(path: Path = CI_ROOT / "pre_review_tools.json") -> str:
    try:
        version = json.loads(path.read_text(encoding="utf-8"))["tools"]["uv"][
            "version"
        ]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ToolFailure("uv version authority is unavailable") from error
    if not isinstance(version, str) or not version:
        raise ToolFailure("uv version authority is invalid")
    return version


def verify_uv_version(uv: str, env: dict[str, str]) -> None:
    try:
        completed = subprocess.run(
            [uv, "--version"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ToolFailure(f"{Path(uv).name} unavailable") from error
    expected = ["uv", expected_uv_version(CI_ROOT / "pre_review_tools.json")]
    if completed.returncode != 0 or completed.stdout.split()[:2] != expected:
        raise ToolFailure("uv version attestation failed")


def update_command(policy: LockPolicy) -> str:
    return (
        "python3 tools/ci/update_generated_locks.py "
        f"--exclude-newer {policy.exclude_newer}"
    )


def compile_command(
    uv: str,
    source: str,
    lock: str,
    policy: LockPolicy,
    *,
    upgrade: bool = False,
) -> list[str]:
    command = [
        uv,
        "--no-cache",
        "--no-config",
        "pip",
        "compile",
        "--universal",
        "--python-version",
        "3.13",
        "--generate-hashes",
        "--default-index",
        policy.default_index,
        "--exclude-newer",
        policy.exclude_newer,
        "--custom-compile-command",
        update_command(policy),
    ]
    if upgrade:
        command.append("--upgrade")
    return [
        *command,
        f"tools/ci/{source}",
        "--output-file",
        f"tools/ci/{lock}",
    ]


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            stdout=subprocess.DEVNULL,
        )
    except OSError as error:
        raise ToolFailure(f"{Path(command[0]).name} unavailable") from error
    if completed.returncode != 0:
        raise ToolFailure(f"{Path(command[0]).name} exited {completed.returncode}")


def verify_python_locks(
    temp: Path,
    temp_ci: Path,
    *,
    uv: str,
    policy: LockPolicy,
    env: dict[str, str],
) -> dict[str, bool]:
    results = {}
    for source, lock in PYTHON_LOCKS:
        shutil.copy2(CI_ROOT / source, temp_ci / source)
        shutil.copy2(CI_ROOT / lock, temp_ci / lock)
        generated = temp_ci / lock
        run(compile_command(uv, source, lock, policy), cwd=temp, env=env)
        results[lock] = generated.read_bytes() == (CI_ROOT / lock).read_bytes()
    return results


def verify_node_lock(temp_ci: Path, *, env: dict[str, str]) -> bool:
    node_root = temp_ci / "pre_review_node"
    node_root.mkdir()
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(CI_ROOT / "pre_review_node" / name, node_root / name)
    run(
        [
            "npm",
            "install",
            "--package-lock-only",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ],
        cwd=node_root,
        env=env,
    )
    return (node_root / "package-lock.json").read_bytes() == (
        CI_ROOT / "pre_review_node" / "package-lock.json"
    ).read_bytes()


def verify_no_tracked_product_generation() -> bool:
    completed = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "^// Code generated .* DO NOT EDIT\\.$",
            "--",
            "src/main",
        ],
        cwd=ROOT,
        env=subprocess_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise ToolFailure(f"git exited {completed.returncode}")
    return completed.returncode == 1 and not completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args(argv)
    results: dict[str, bool] = {}
    failure: ToolFailure | OSError | None = None
    try:
        policy = load_lock_policy(CI_ROOT / POLICY_PATH.name)
        env = subprocess_environment()
        verify_uv_version(args.uv, env)
        with tempfile.TemporaryDirectory(prefix="repomap-generated-drift-") as raw_temp:
            temp = Path(raw_temp)
            temp_ci = temp / "tools" / "ci"
            temp_ci.mkdir(parents=True)
            if authority_digest(CI_ROOT) != policy.authority_sha256:
                results.update({lock: False for _source, lock in PYTHON_LOCKS})
            else:
                generated = verify_python_locks(
                    temp,
                    temp_ci,
                    uv=args.uv,
                    policy=policy,
                    env=env,
                )
                results.update(generated)
                if not all(generated.values()):
                    raise ToolFailure(
                        "frozen index view no longer reproduces repository locks"
                    )
            results["pre_review_node/package-lock.json"] = verify_node_lock(
                temp_ci, env=env
            )
        results["tracked-product-generated-output"] = verify_no_tracked_product_generation()
    except (OSError, ToolFailure) as error:
        failure = error

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / "generated-code-drift.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, sort_keys=True))
    if failure is not None:
        detail = str(failure) if isinstance(failure, ToolFailure) else type(failure).__name__
        print(f"tool/configuration failure: {detail}", file=sys.stderr)
        return 2
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
