#!/usr/bin/env python3
"""Explicitly upgrade RepoMap's generated Python locks under a new cutoff."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.check_generated_drift import (
    CI_ROOT,
    POLICY_PATH,
    PYPI_INDEX,
    PYTHON_LOCKS,
    ToolFailure,
    authority_digest,
    compile_command,
    lock_policy,
    policy_bytes,
    run,
    subprocess_environment,
    verify_uv_version,
)


def regenerate(uv: str, exclude_newer: str, *, preserve_existing: bool = False) -> None:
    policy = lock_policy(PYPI_INDEX, exclude_newer, authority_digest(CI_ROOT))
    env = subprocess_environment()
    verify_uv_version(uv, env)
    with tempfile.TemporaryDirectory(prefix="repomap-lock-upgrade-") as raw_temp:
        temp = Path(raw_temp)
        temp_ci = temp / "tools" / "ci"
        temp_ci.mkdir(parents=True)
        for source, lock in PYTHON_LOCKS:
            shutil.copy2(CI_ROOT / source, temp_ci / source)
            shutil.copy2(CI_ROOT / lock, temp_ci / lock)
            run(
                compile_command(uv, source, lock, policy, upgrade=not preserve_existing),
                cwd=temp,
                env=env,
            )
        for _source, lock in PYTHON_LOCKS:
            shutil.copy2(temp_ci / lock, CI_ROOT / lock)
        updated = lock_policy(
            PYPI_INDEX,
            exclude_newer,
            authority_digest(CI_ROOT, lock_root=temp_ci),
        )
        POLICY_PATH.write_bytes(policy_bytes(updated))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exclude-newer", required=True)
    parser.add_argument("--uv", default="uv")
    parser.add_argument(
        "--preserve-existing", action="store_true",
        help="retain existing resolved versions while adding declared prerequisites",
    )
    args = parser.parse_args(argv)
    try:
        regenerate(args.uv, args.exclude_newer, preserve_existing=args.preserve_existing)
    except (OSError, ToolFailure) as error:
        detail = str(error) if isinstance(error, ToolFailure) else type(error).__name__
        print(f"tool/configuration failure: {detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
