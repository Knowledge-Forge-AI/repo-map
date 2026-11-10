"""``plan``, ``check`` and ``show`` for the checkout-only installed-experience tool.

Exit codes: 0 accepted (or ``plan`` printed), 1 rejected or incomplete, 2 usage
or unreadable input. Output is path-free: outcomes, owners, scenario ids,
closed categories, outcomes and cleanup states only. ``check`` and ``show``
never write to the bundle.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from installed_experience_bundle import read_installed_bundle
from installed_experience_domains import HEX64, InstalledError
from installed_experience_reconcile import Verdict, check_bundle
from installed_experience_recipe import catalog, recipe_digest

EXIT_ACCEPTED = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2
ROW_KEYS = ("seq", "scenario", "env_class", "family", "outcome", "cleanup", "failure_code")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        raise InstalledError("malformed")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="installed_experience.py", add_help=True)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    commands.add_parser("plan", help="print the frozen scenario catalog and recipe digest")
    for name in ("check", "show"):
        command = commands.add_parser(name, help=f"{name} one installed-experience bundle directory")
        command.add_argument("bundle", type=Path)
        command.add_argument("--candidate-source-sha256", required=True)
        if name == "show":
            command.add_argument("--json", action="store_true")
    return parser


def verdict_line(verdict: Verdict) -> str:
    categories = ",".join(verdict.categories) or "-"
    return f"{verdict.outcome} {verdict.owner or 'unknown'} {categories}"


def table_rows(verdict: Verdict) -> list[dict[str, Any]]:
    return [{key: row[key] for key in ROW_KEYS} | {"categories": list(row["categories"])}
            for row in verdict.rows]


def _cell(value: object) -> str:
    return "-" if value is None else str(value)


def _verdict(bundle: Path, candidate: str, out: TextIO) -> Verdict | None:
    try:
        files = read_installed_bundle(bundle)
    except InstalledError as error:
        if error.category == "unreadable":
            raise
        out.write(f"rejected unknown {error.category}\n")
        return None
    return check_bundle(files, candidate_source_sha256=candidate)


def _plan(out: TextIO) -> int:
    document = {"recipe_digest": recipe_digest(), "catalog": catalog()}
    out.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    return EXIT_ACCEPTED


def _show(verdict: Verdict, as_json: bool, out: TextIO) -> int:
    rows = table_rows(verdict)
    if as_json:
        document = {"outcome": verdict.outcome, "owner": verdict.owner,
                    "categories": list(verdict.categories), "rows": rows,
                    "note": "diagnostic installed evidence; not coverage, release or native proof"}
        out.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    else:
        out.write(verdict_line(verdict) + "\n")
        out.write(" ".join(ROW_KEYS) + " categories\n")
        for row in rows:
            cells = [row[key] for key in ROW_KEYS] + [",".join(row["categories"]) or "-"]
            out.write(" ".join(_cell(cell) for cell in cells) + "\n")
    return EXIT_ACCEPTED if verdict.outcome == "accepted" else EXIT_REJECTED


def run(
    argv: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None,
) -> int:
    stdout = sys.stdout if out is None else out
    stderr = sys.stderr if err is None else err
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except InstalledError:
        stderr.write("installed-experience: usage\n")
        return EXIT_USAGE
    if args.command == "plan":
        return _plan(stdout)
    if HEX64.fullmatch(args.candidate_source_sha256) is None:
        stderr.write("installed-experience: usage\n")
        return EXIT_USAGE
    try:
        verdict = _verdict(args.bundle, args.candidate_source_sha256, stdout)
    except InstalledError:
        stderr.write("installed-experience: unreadable\n")
        return EXIT_USAGE
    if verdict is None:
        return EXIT_REJECTED
    if args.command == "check":
        stdout.write(verdict_line(verdict) + "\n")
        return EXIT_ACCEPTED if verdict.outcome == "accepted" else EXIT_REJECTED
    return _show(verdict, args.json, stdout)


__all__ = ["EXIT_ACCEPTED", "EXIT_REJECTED", "EXIT_USAGE", "run", "table_rows", "verdict_line"]
