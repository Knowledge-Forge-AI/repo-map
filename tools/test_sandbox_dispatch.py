"""Canonical runner dispatch into the owned integration sandbox prototype."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "tools/test_sandbox/Dockerfile"


def integration_sandbox_dispatch(args, raw_argv: list[str]) -> int | None:
    if args.suite not in {"int", "staging", "system"}:
        return None
    from test_sandbox import active_sandbox, ensure_sandbox_image, run_in_sandbox

    try:
        if active_sandbox():
            return None
        from repomap_test_support.unit_purity import require_live_resource_allowed

        require_live_resource_allowed("integration sandbox Docker boundary")
        image_id = ensure_sandbox_image(dockerfile=DOCKERFILE)
        return run_in_sandbox(
            raw_argv,
            repo_root=REPO_ROOT,
            image_id=image_id,
        )
    except RuntimeError as error:
        print(f"ERROR: integration sandbox failed: {error}", file=sys.stderr)
        return 2
