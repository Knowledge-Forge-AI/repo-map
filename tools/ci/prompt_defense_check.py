#!/usr/bin/env python3
"""Run the local prompt-defense ratchet over RepoMap's effective bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = Path(__file__).resolve().parent


def build_bundle() -> str:
    parts = []
    for raw in (CI_ROOT / "prompt_defense_targets.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        relative = raw.strip()
        if not relative or relative.startswith("#"):
            continue
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"declared instruction target is missing: {relative}")
        parts.append(f"\n--- {relative} ---\n{path.read_text(encoding='utf-8')}")
    if not parts:
        raise RuntimeError("effective instruction bundle is empty")
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=CI_ROOT / "pre_review_baseline.json")
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))["ratchets"][
        "prompt-defense-audit"
    ]
    with tempfile.TemporaryDirectory(prefix="repomap-prompt-defense-") as temp:
        bundle = Path(temp) / "effective-instructions.txt"
        bundle.write_text(build_bundle(), encoding="utf-8")
        completed = subprocess.run(
            ["prompt-defense-audit", "--file", str(bundle), "--json"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode != 0:
        raise RuntimeError("prompt-defense-audit failed to produce a result")
    result = json.loads(completed.stdout)
    summary = {
        "grade": result["grade"],
        "score": result["score"],
        "missing": len(result.get("missing", [])),
        "embedded_payloads": len(result.get("embeddedPayloads", [])),
        "unicode_issues": len(result.get("unicodeIssues", [])),
    }
    print(json.dumps(summary, sort_keys=True))
    passed = (
        summary["score"] >= baseline["minimum_score"]
        and summary["missing"] <= baseline["missing"]
        and summary["embedded_payloads"] <= baseline["embedded_payloads"]
        and summary["unicode_issues"] <= baseline["unicode_issues"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
