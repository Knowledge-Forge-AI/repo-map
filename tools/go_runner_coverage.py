"""Go integration coverage measurement and policy thresholds for RepoMap."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from collections.abc import Callable
from typing import Protocol

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from test_report import GoCoverageSummary


class BuildHelperFn(Protocol):
    """Callable protocol matching build_go_helper for instrumented builds."""

    def __call__(
        self,
        *,
        package_root: Path = ...,
        instrumented: bool = ...,
    ) -> Path: ...


DEFAULT_GO_INT_STATEMENT_FLOOR: float = 80.0

_PRIOR_GOCOVERDIR: str | None = None
_GOCOVERDIR_SET: bool = False


def restore_go_environment() -> None:
    """Restore environment changes made by prepare_go_environment for suite isolation."""
    global _PRIOR_GOCOVERDIR, _GOCOVERDIR_SET
    if _GOCOVERDIR_SET:
        if _PRIOR_GOCOVERDIR is not None:
            os.environ["GOCOVERDIR"] = _PRIOR_GOCOVERDIR
        else:
            os.environ.pop("GOCOVERDIR", None)
        _PRIOR_GOCOVERDIR = None
        _GOCOVERDIR_SET = False


def parse_textfmt_profile(text: str) -> tuple[int, int]:
    """Parse a go tool covdata textfmt output and return (covered_statements, total_statements).

    The textfmt format consists of:
      mode: <set|count|atomic>
      <file>:<start_line>.<start_col>,<end_line>.<end_col> <num_statements> <count>
    We aggregate covered and total NumStmt directly across all package blocks,
    strictly validating mode headers, nonnegative integers, and reconciling duplicates.
    """
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError("empty textfmt profile data")
    header = lines[0].strip()
    if not header.startswith("mode:") or len(header.split()) != 2:
        raise ValueError("missing or invalid textfmt mode header")
    mode = header.split()[1]
    if mode not in {"set", "count", "atomic"}:
        raise ValueError(f"unsupported textfmt mode: {mode}")

    blocks: dict[str, tuple[int, int]] = {}
    for line_num, line in enumerate(lines[1:], start=2):
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(None, 2)
        if len(parts) != 3:
            raise ValueError(f"malformed profile line {line_num}: {line}")
        block_id, num_stmts_str, count_str = parts
        if ":" not in block_id or "," not in block_id:
            raise ValueError(f"malformed block identifier at line {line_num}: {block_id}")
        try:
            num_stmts = int(num_stmts_str)
            count = int(count_str)
        except ValueError:
            raise ValueError(f"non-integer statement or count at line {line_num}: {line}")
        if num_stmts < 0 or count < 0:
            raise ValueError(f"negative statement count at line {line_num}: {line}")

        if block_id in blocks:
            existing_stmts, existing_count = blocks[block_id]
            if existing_stmts != num_stmts:
                raise ValueError(
                    f"conflicting statement count for block {block_id}: {existing_stmts} vs {num_stmts}"
                )
            blocks[block_id] = (num_stmts, max(existing_count, count))
        else:
            blocks[block_id] = (num_stmts, count)

    total_statements = sum(s for s, _ in blocks.values())
    covered_statements = sum(s for s, c in blocks.values() if c > 0)
    return covered_statements, total_statements


def collect_go_integration_coverage(
    gocoverdir: Path,
    *,
    policy_floor: float = DEFAULT_GO_INT_STATEMENT_FLOOR,
    suite_name: str = "int",
) -> GoCoverageSummary:
    """Collect Go statement coverage from a run-owned GOCOVERDIR using go tool covdata.

    Returns an explicit failing summary with classified diagnostics if GOCOVERDIR
    is absent, empty, corrupt, or fails the policy floor.
    """
    gocover_path = Path(gocoverdir).resolve()
    if not gocover_path.is_dir():
        print(
            f"[go-coverage] missing setup: coverage directory does not exist: {gocover_path}",
            file=sys.stderr,
        )
        return GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=policy_floor,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="missing_setup",
        )

    cov_files = [
        f for f in gocover_path.iterdir()
        if f.name.startswith("covcounters.") or f.name.startswith("covmeta.")
    ]
    if not cov_files:
        print(
            f"[go-coverage] no data: no covcounters.* or covmeta.* files in {gocover_path}",
            file=sys.stderr,
        )
        return GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=policy_floor,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="no_data",
        )

    with tempfile.TemporaryDirectory(prefix="repomap-gocov-") as tmpdir:
        textfmt_out = Path(tmpdir) / "gocov.out"
        try:
            subprocess.run(
                [
                    "go",
                    "tool",
                    "covdata",
                    "textfmt",
                    f"-i={str(gocover_path)}",
                    f"-o={str(textfmt_out)}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            if not textfmt_out.is_file():
                raise RuntimeError("covdata textfmt produced no output file")
            content = textfmt_out.read_text(encoding="utf-8")
        except subprocess.TimeoutExpired:
            print("[go-coverage] collector error: covdata textfmt timed out", file=sys.stderr)
            return GoCoverageSummary(
                suite_name=suite_name,
                hard_threshold=policy_floor,
                total_statements=0,
                covered_statements=0,
                statement_percent=0.0,
                branch_status="N/A",
                diagnostic_category="collector_error",
            )
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.strip() if exc.stderr else str(exc)
            print(f"[go-coverage] collector error: covdata textfmt failed: {err}", file=sys.stderr)
            return GoCoverageSummary(
                suite_name=suite_name,
                hard_threshold=policy_floor,
                total_statements=0,
                covered_statements=0,
                statement_percent=0.0,
                branch_status="N/A",
                diagnostic_category="collector_error",
            )
        except (OSError, RuntimeError) as exc:
            print(f"[go-coverage] collector error: {exc}", file=sys.stderr)
            return GoCoverageSummary(
                suite_name=suite_name,
                hard_threshold=policy_floor,
                total_statements=0,
                covered_statements=0,
                statement_percent=0.0,
                branch_status="N/A",
                diagnostic_category="collector_error",
            )

    try:
        covered, total = parse_textfmt_profile(content)
    except ValueError as exc:
        print(f"[go-coverage] invalid data: {exc}", file=sys.stderr)
        return GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=policy_floor,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="invalid_data",
        )

    if total == 0:
        print("[go-coverage] no data: total statements in profile is zero", file=sys.stderr)
        return GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=policy_floor,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="no_data",
        )

    pct = (covered / total * 100.0) if total > 0 else 0.0
    passed = pct >= policy_floor
    diag = "passed" if passed else "below_floor"
    if not passed:
        print(
            f"[go-coverage] below floor: {covered}/{total} ({pct:.1f}%) < {policy_floor:.1f}%",
            file=sys.stderr,
        )
    return GoCoverageSummary(
        suite_name=suite_name,
        hard_threshold=policy_floor,
        total_statements=total,
        covered_statements=covered,
        statement_percent=pct,
        branch_status="N/A",
        diagnostic_category=diag,
    )


def report_go_coverage(go_summary: GoCoverageSummary) -> bool:
    """Print Go coverage evaluation and return boolean pass/fail status."""
    print("\nGo Integration Coverage Summary:")
    print(f"  Suite: {go_summary.suite_name}")
    print(
        f"  Statements: {go_summary.covered_statements}/{go_summary.total_statements} "
        f"({go_summary.statement_percent:.1f}%), required {go_summary.hard_threshold:.1f}%"
    )
    print("  Branches: N/A (Go excluded from branch arithmetic)")
    passed = go_summary.passed
    if go_summary.diagnostic_category and go_summary.diagnostic_category != "passed":
        print(f"  Diagnostic: {go_summary.diagnostic_category}")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


def prepare_go_environment(
    suite: str,
    go_tmp_root: Path,
    validate_sources_fn: Callable[[], None],
    build_helper_fn: BuildHelperFn,
) -> Path:
    """Prepare the Go environment and instrumented helper for the target suite."""
    global _PRIOR_GOCOVERDIR, _GOCOVERDIR_SET
    pkg = go_tmp_root / "helper"
    instrumented = suite in {"int", "staging"}
    if suite == "unit":
        validate_sources_fn()
    elif instrumented:
        covdir = go_tmp_root / "gocoverdir"
        covdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(covdir, 0o700)
        except OSError as err:
            raise RuntimeError(
                f"Failed to enforce 0700 permissions on gocoverdir {covdir}: {err}"
            ) from err
        st = covdir.stat()
        if (st.st_mode & 0o777) != 0o700:
            raise RuntimeError(
                f"Failed to enforce 0700 permissions on gocoverdir {covdir}: mode is {oct(st.st_mode & 0o777)}"
            )
        _PRIOR_GOCOVERDIR = os.environ.get("GOCOVERDIR")
        _GOCOVERDIR_SET = True
        os.environ["GOCOVERDIR"] = str(covdir)
    return build_helper_fn(package_root=pkg, instrumented=instrumented)


def evaluate_go_integration_gate(
    suite_name: str,
    no_coverage: bool,
    *,
    expected_gocoverdir: Path | None = None,
) -> tuple[GoCoverageSummary | None, bool]:
    """Collect and evaluate Go integration coverage for int/staging suites.

    Returns (summary, pass_status). If suite is not eligible or no_coverage is True,
    returns (None, True). For eligible suites, requires valid measurement from the
    run-owned expected directory.
    """
    if suite_name not in {"int", "staging"} or no_coverage:
        return None, True

    expected_dir = expected_gocoverdir
    if expected_dir is None:
        try:
            from repomap_test_support.test_scratch import establish_run

            expected_dir = establish_run().go_tmp / "gocoverdir"
        except (ImportError, AttributeError, RuntimeError, OSError):
            expected_dir = None

    if expected_dir is None:
        print(
            "[go-coverage] missing setup: could not determine run-owned GOCOVERDIR",
            file=sys.stderr,
        )
        summary = GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=DEFAULT_GO_INT_STATEMENT_FLOOR,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="missing_setup",
        )
        report_go_coverage(summary)
        restore_go_environment()
        return summary, False

    gocov_env = os.environ.get("GOCOVERDIR")
    if not gocov_env or Path(gocov_env).resolve() != expected_dir.resolve():
        print(
            f"[go-coverage] missing setup: ambient GOCOVERDIR ({gocov_env}) does not match "
            f"run-owned authority ({expected_dir})",
            file=sys.stderr,
        )
        summary = GoCoverageSummary(
            suite_name=suite_name,
            hard_threshold=DEFAULT_GO_INT_STATEMENT_FLOOR,
            total_statements=0,
            covered_statements=0,
            statement_percent=0.0,
            branch_status="N/A",
            diagnostic_category="missing_setup",
        )
        report_go_coverage(summary)
        restore_go_environment()
        return summary, False

    summary = collect_go_integration_coverage(expected_dir, suite_name=suite_name)
    ok = report_go_coverage(summary)
    restore_go_environment()
    return summary, ok
