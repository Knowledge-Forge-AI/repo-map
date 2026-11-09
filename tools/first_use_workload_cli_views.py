"""``plan``, ``check`` and ``show`` for the checkout-only first-use workload tool.

Exit codes: 0 accepted (or ``plan`` printed), 1 rejected or incomplete,
2 usage or unreadable input. Output is path-free: it names outcomes, scenarios,
closed categories, steps, results and counters only. ``check`` and ``show``
never write to the bundle.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from first_use_workload_bundle import read_bundle
from first_use_workload_census import REPO_ROOT, load_census
from first_use_workload_domains import HEX40, WorkloadError
from first_use_workload_reconcile import Verdict, check_bundle
from first_use_workload_source_identity import (
    Lister, SourceIdentityError, current_intent, git_listed,
)

EXIT_ACCEPTED = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2
SPAN_LABELS = ("prepare_ns", "call_ns", "observe_ns", "cleanup_ns")
CPU_LABELS = {
    "parent_process_ns": "test_process_threads",
    "waited_descendants_ns": "reaped_descendants",
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        raise WorkloadError("malformed")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="first_use_workload.py", add_help=True)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    plan = commands.add_parser("plan", help="print the canonical intent of this checkout")
    plan.add_argument("--source-parent", default=None)
    check = commands.add_parser("check", help="re-validate one bundle directory")
    check.add_argument("--bundle", required=True, type=Path)
    show = commands.add_parser("show", help="print a bounded per-step table; never sums")
    show.add_argument("--bundle", required=True, type=Path)
    show.add_argument("--json", action="store_true")
    return parser


def verdict_line(verdict: Verdict) -> str:
    categories = ",".join(verdict.categories) or "-"
    return f"{verdict.outcome} {verdict.scenario or 'unknown'} {categories}"


def _files(bundle: Path, out: TextIO) -> dict[str, bytes] | None:
    """Read the bundle; a refused (but present) bundle is a rejected verdict line."""
    try:
        return read_bundle(bundle)
    except WorkloadError as error:
        if error.category == "unreadable":
            raise
        out.write(f"rejected unknown {error.category}\n")
        return None


def _check(bundle: Path, repo_root: Path, lister: Lister, out: TextIO) -> int:
    intent = current_intent(repo_root, lister=lister)
    census = load_census(repo_root)
    files = _files(bundle, out)
    if files is None:
        return EXIT_REJECTED
    verdict = check_bundle(intent, files, census)
    out.write(verdict_line(verdict) + "\n")
    return EXIT_ACCEPTED if verdict.outcome == "accepted" else EXIT_REJECTED


def table_rows(verdict: Verdict) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in verdict.observations:
        rows.append({
            "step": item["step"], "sub": item["sub"], "action": item["action"],
            "backend": item["backend"], "result": item["result"], "refusal": item["refusal"],
            "reason": item["reason"],
            "spans": {key: item["spans"][key] for key in SPAN_LABELS},
            "cpu": {CPU_LABELS[key]: item["cpu"][key] for key in CPU_LABELS},
        })
    return rows


def _cell(value: object) -> str:
    return "-" if value is None else str(value)


def _show(bundle: Path, repo_root: Path, lister: Lister, as_json: bool, out: TextIO) -> int:
    intent = current_intent(repo_root, lister=lister)
    census = load_census(repo_root)
    files = _files(bundle, out)
    if files is None:
        return EXIT_REJECTED
    verdict = check_bundle(intent, files, census)
    rows = table_rows(verdict)
    if as_json:
        document = {
            "outcome": verdict.outcome, "scenario": verdict.scenario,
            "categories": list(verdict.categories), "rows": rows,
            "note": "per-step observations; never summed across steps or backends",
        }
        out.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
        return EXIT_ACCEPTED if verdict.outcome == "accepted" else EXIT_REJECTED
    out.write(verdict_line(verdict) + "\n")
    out.write("step sub action backend result refusal reason " + " ".join(SPAN_LABELS)
              + " " + " ".join(CPU_LABELS.values()) + "\n")
    for row in rows:
        cells = [row["step"], row["sub"], row["action"], row["backend"], row["result"],
                 row["refusal"], row["reason"], *row["spans"].values(), *row["cpu"].values()]
        out.write(" ".join(_cell(cell) for cell in cells) + "\n")
    out.write("note: observations are per step; nothing is summed\n")
    return EXIT_ACCEPTED if verdict.outcome == "accepted" else EXIT_REJECTED


def run(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    lister: Lister = git_listed,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    stdout = sys.stdout if out is None else out
    stderr = sys.stderr if err is None else err
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except WorkloadError:
        stderr.write("first-use-workload: usage\n")
        return EXIT_USAGE
    if args.command == "plan" and args.source_parent is not None:
        if HEX40.fullmatch(args.source_parent) is None:
            stderr.write("first-use-workload: usage\n")
            return EXIT_USAGE
    try:
        if args.command == "plan":
            data = current_intent(repo_root, declared_source_parent=args.source_parent, lister=lister)
            stdout.write(data.decode("utf-8"))
            return EXIT_ACCEPTED
        if args.command == "check":
            return _check(args.bundle, repo_root, lister, stdout)
        return _show(args.bundle, repo_root, lister, args.json, stdout)
    except WorkloadError as error:
        if error.category == "unreadable":
            stderr.write("first-use-workload: unreadable\n")
            return EXIT_USAGE
        stdout.write(f"rejected unknown {error.category}\n")
        return EXIT_REJECTED
    except SourceIdentityError:
        stderr.write("first-use-workload: unreadable\n")
        return EXIT_USAGE


__all__ = ["EXIT_ACCEPTED", "EXIT_REJECTED", "EXIT_USAGE", "run", "table_rows", "verdict_line"]
