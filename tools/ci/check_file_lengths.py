#!/usr/bin/env python3
"""Run RepoMap's repository-owned file-length profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.file_length_policy import (
    FileLengthOperationalError,
    render_json,
    render_text,
    scan_repository,
    validate_repo_root,
)


def default_repo_root() -> Path:
    """Derive the repository root from this entrypoint's own path."""
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check tracked RepoMap Python files for excessive length."
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=default_repo_root(),
        help="explicit repository root for controlled invocation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = validate_repo_root(args.repo_root)
        result = scan_repository(repo_root)
        rendered = render_json(result) if args.format == "json" else render_text(result)
        sys.stdout.write(rendered)
    except FileLengthOperationalError as error:
        print(f"file-length: error: {error}", file=sys.stderr)
        return 2
    except (OSError, TypeError, UnicodeError, ValueError):
        print("file-length: error: unable to complete profile", file=sys.stderr)
        return 2
    return 1 if result.failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
