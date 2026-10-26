"""Canonical runner dispatch into the owned integration sandbox prototype."""

from __future__ import annotations

from pathlib import Path
import sys

from ci.d12_system_grant import verify_host_system_proof_for_dispatch


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "tools/test_sandbox/Dockerfile"


def integration_sandbox_dispatch(
    args,
    raw_argv: list[str],
    *,
    repo_root: Path = REPO_ROOT,
    dockerfile: Path = DOCKERFILE,
) -> int | None:
    if args.suite not in {"int", "staging", "system"}:
        if getattr(args, "d12_system_proof_json", None) is not None:
            print(
                "ERROR: integration sandbox failed: --d12-system-proof-json is only valid with --suite system",
                file=sys.stderr,
            )
            return 2
        return None
    from test_sandbox import active_sandbox, ensure_sandbox_image, run_in_sandbox

    try:
        if active_sandbox():
            return None
        if args.suite == "system":
            verify_host_system_proof_for_dispatch(
                args, raw_argv=raw_argv, repo_root=repo_root
            )
        from repomap_test_support.unit_purity import require_live_resource_allowed

        require_live_resource_allowed("integration sandbox Docker boundary")
        image_id = ensure_sandbox_image(dockerfile=dockerfile)
        return run_in_sandbox(
            raw_argv,
            repo_root=repo_root,
            image_id=image_id,
        )
    except RuntimeError as error:
        print(f"ERROR: integration sandbox failed: {error}", file=sys.stderr)
        return 2
