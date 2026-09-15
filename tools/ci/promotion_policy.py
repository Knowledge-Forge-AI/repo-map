"""Main-source policy: only same-repository ``staging`` may promote to ``main``.

This is a cheap advisory topology check, not the security boundary. It runs no
expensive work, never mutates the pull request, and never moves a ref. The
future JACA git broker enforces the same policy authoritatively by refusing to
move ``main`` for any other source.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MAIN_BRANCH = "main"
PROMOTION_SOURCE_BRANCH = "staging"


@dataclass(frozen=True, slots=True)
class PromotionSource:
    """The three facts that decide whether a promotion source is valid."""

    base_ref: str
    head_ref: str
    head_repository: str

    @classmethod
    def from_event_payload(cls, payload: Mapping[str, Any]) -> "PromotionSource":
        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, Mapping):
            raise ValueError("event payload has no pull_request object")
        base = pull_request.get("base") or {}
        head = pull_request.get("head") or {}
        head_repository = (head.get("repo") or {}).get("full_name")
        return cls(
            base_ref=str(base.get("ref", "")),
            head_ref=str(head.get("ref", "")),
            head_repository="" if head_repository is None else str(head_repository),
        )


def evaluate_promotion(source: PromotionSource, repository: str) -> tuple[str, ...]:
    """Return the policy violations for one proposed promotion, if any."""
    violations: list[str] = []
    if source.base_ref != MAIN_BRANCH:
        violations.append(
            f"policy applies only to pull requests targeting {MAIN_BRANCH!r}, "
            f"got base {source.base_ref!r}"
        )
    if source.head_repository != repository:
        violations.append(
            f"head must come from {repository!r}, got {source.head_repository!r}"
        )
    if source.head_ref != PROMOTION_SOURCE_BRANCH:
        violations.append(
            f"only {PROMOTION_SOURCE_BRANCH!r} may promote to {MAIN_BRANCH!r}, "
            f"got head {source.head_ref!r}"
        )
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    arguments = parser.parse_args(argv)

    if not arguments.repository or not arguments.event_path:
        print("main-source policy requires a repository and an event payload", file=sys.stderr)
        return 1
    payload = json.loads(Path(arguments.event_path).read_text(encoding="utf-8"))
    try:
        source = PromotionSource.from_event_payload(payload)
    except ValueError as error:
        print(f"main-source policy refused: {error}", file=sys.stderr)
        return 1
    violations = evaluate_promotion(source, arguments.repository)
    if violations:
        for violation in violations:
            print(f"main-source policy refused: {violation}", file=sys.stderr)
        return 1
    print(
        f"main-source policy accepted {source.head_repository}:{source.head_ref} "
        f"-> {source.base_ref}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
