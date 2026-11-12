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
    from test_sandbox import active_sandbox, cached_sandbox_image, ensure_sandbox_image, run_in_sandbox
    from test_sandbox_ownership import prepare_ownership_reporter

    ownership_reporter = None
    try:
        if active_sandbox():
            return None
        ownership_reporter = prepare_ownership_reporter(raw_argv, repo_root)
        if args.suite == "system":
            verify_host_system_proof_for_dispatch(
                args, raw_argv=raw_argv, repo_root=repo_root
            )
        from repomap_test_support.unit_purity import require_live_resource_allowed

        require_live_resource_allowed("integration sandbox Docker boundary")
        image_id = (ensure_sandbox_image(dockerfile=dockerfile) if ownership_reporter is None
                    else cached_sandbox_image(dockerfile=dockerfile,
                        expected_image_id=ownership_reporter.expected_sdk_image_id))
        if ownership_reporter is None:
            return run_in_sandbox(raw_argv, repo_root=repo_root, image_id=image_id)
        return run_in_sandbox(
            raw_argv,
            repo_root=repo_root,
            image_id=image_id,
            ownership_reporter=ownership_reporter,
        )
    except RuntimeError as error:
        print(f"ERROR: integration sandbox failed: {error}", file=sys.stderr)
        return 2
    finally:
        if ownership_reporter is not None:
            ownership_reporter.close()
