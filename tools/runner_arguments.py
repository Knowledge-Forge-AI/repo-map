"""Argument parsing and pytest-selection rules for the RepoMap runner."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


def add_runner_arguments(
    parser: argparse.ArgumentParser,
    *,
    hygiene_profiles: Sequence[str],
    default_report_root: Path,
    parse_jobs: Callable[[str], str],
) -> None:
    """Populate the public runner parser without changing option ordering."""
    parser.add_argument(
        "--suite",
        choices=("unit", "int", "smoke", "staging", "system"),
        required=True,
        help="test suite to run",
    )
    parser.add_argument(
        "--hygiene-profile",
        choices=tuple(hygiene_profiles),
        default=None,
        help="closed ADR 0048 host and per-run quota profile",
    )
    parser.add_argument("--hygiene-hard-watermark-bytes", type=int, default=None)
    parser.add_argument("--hygiene-hard-watermark-inodes", type=int, default=None)
    parser.add_argument("--hygiene-soft-watermark-bytes", type=int, default=None)
    parser.add_argument("--hygiene-soft-watermark-inodes", type=int, default=None)
    parser.add_argument("--hygiene-min-free-disk-bytes", type=int, default=None)
    parser.add_argument("--hygiene-min-free-disk-percent", type=int, default=None)
    parser.add_argument("--hygiene-profile-free-disk-reserve-bytes", type=int, default=None)
    parser.add_argument("--declared-complete-gates", type=int, default=0)
    parser.add_argument("--campaign-plan-id", default=None)
    parser.add_argument("--operator-attest-exclusive", action="store_true")
    parser.add_argument("--operator-attest-pressure-degradation", action="store_true")
    parser.add_argument(
        "--threshold",
        default=None,
        type=float,
        help="override the hard line and branch coverage threshold for this run",
    )
    parser.add_argument(
        "--report", action="store_true", help="write a static HTML test report"
    )
    parser.add_argument(
        "--report-dir", default=default_report_root, type=Path, help="directory for HTML reports"
    )
    parser.add_argument(
        "--pg-container-port",
        default=55433,
        type=int,
        help="localhost port for the temporary Postgres container",
    )
    parser.add_argument(
        "--pg-container-runtime",
        choices=("docker", "podman"),
        default="docker",
        help="container runtime for temporary Postgres",
    )
    parser.add_argument(
        "--smoke-timeout",
        default=900,
        type=int,
        help="total monotonic wall-clock watchdog budget for smoke (default 900 seconds)",
    )
    parser.add_argument(
        "--smoke-image-reference",
        default=None,
        help="optional exact local image-ID override",
    )
    parser.add_argument(
        "--system-timeout",
        default=3600,
        type=int,
        help="total monotonic wall-clock budget for system (maximum 3600 seconds)",
    )
    parser.add_argument(
        "--gate-request-json",
        default=None,
        type=Path,
        help="path to input gate request JSON defining candidate identities and authorization",
    )
    parser.add_argument(
        "--candidate-sha",
        default="",
        help="exact candidate commit SHA being tested",
    )
    parser.add_argument(
        "--candidate-tree",
        default="",
        help="exact candidate tree SHA being tested",
    )
    parser.add_argument(
        "--candidate-base-parent",
        default="",
        help="exact approved base parent commit SHA",
    )
    parser.add_argument(
        "--candidate-head-parent",
        default="",
        help="exact approved head parent commit SHA",
    )
    parser.add_argument(
        "--approval-id",
        default="",
        help="approved human promotion ticket or approval identifier",
    )
    parser.add_argument(
        "--pr-number",
        default="",
        help="pull request number associated with candidate",
    )
    parser.add_argument(
        "--repository",
        default="",
        help="repository name associated with candidate",
    )
    parser.add_argument(
        "--jobs",
        default="1",
        type=parse_jobs,
        help="pytest-xdist worker count: 1, auto, or an integer >= 2",
    )
    parser.add_argument(
        "--no-coverage",
        action="store_true",
        help="skip the coverage gate; required for --jobs auto/N",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help=(
            "assert the mandatory integration/staging sandbox boundary "
            "(retained for compatibility; sandboxing is automatic)"
        ),
    )


def split_forwarded_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    separator_index = argv.index("--")
    return argv[:separator_index], argv[separator_index + 1 :]


def parse_jobs(value: str) -> str:
    try:
        return normalize_jobs(value)
    except RuntimeError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def normalize_jobs(value: str) -> str:
    text = str(value).strip().lower()
    if text == "auto":
        return "auto"
    try:
        count = int(text)
    except ValueError as error:
        raise RuntimeError("--jobs must be 1, auto, or an integer >= 2") from error
    if count < 1:
        raise RuntimeError("--jobs must be 1, auto, or an integer >= 2")
    return str(count)


def validate_runner_options(
    args,
    suites: tuple[str, ...],
    *,
    parallel_jobs_enabled_fn=None,
) -> None:
    if parallel_jobs_enabled_fn is None:
        parallel_jobs_enabled_fn = parallel_jobs_enabled
    if suites == ("smoke",):
        if args.report:
            raise RuntimeError("--report is only supported for pytest-backed suites")
        if parallel_jobs_enabled_fn(args.jobs):
            raise RuntimeError("--jobs is only supported for pytest-backed suites")
        return
    if suites == ("system",):
        if parallel_jobs_enabled_fn(args.jobs):
            raise RuntimeError("--jobs is only supported for pytest-backed suites")
        return
    if args.no_coverage and args.report:
        raise RuntimeError("--report requires coverage; omit --no-coverage")
    if parallel_jobs_enabled_fn(args.jobs) and not args.no_coverage:
        raise RuntimeError(
            "--jobs auto/N requires --no-coverage because pytest-xdist coverage "
            "aggregation is not enabled"
        )
    if parallel_jobs_enabled_fn(args.jobs) and "int" in suites:
        raise RuntimeError(
            "parallel integration/staging suites are not supported yet; the "
            "MCP-RUNTIME3 Postgres harness and integration database state remain "
            "serial-only in TEST-INFRA3"
        )


def validate_sandbox_admission_options(
    args,
    *,
    validate_runner_options_fn=validate_runner_options,
) -> None:
    if args.suite not in {"int", "staging", "system"}:
        return
    if args.pg_container_runtime != "docker":
        raise RuntimeError(
            "integration sandbox execution requires --pg-container-runtime docker"
        )
    if args.suite in {"int", "staging"}:
        validate_runner_options_fn(args, ("int",))
    elif args.suite == "system":
        validate_runner_options_fn(args, ("system",))


def parallel_jobs_enabled(jobs: str) -> bool:
    return normalize_jobs(jobs) != "1"


def build_pytest_args(
    suites: tuple[str, ...],
    forwarded_pytest_args: list[str],
    *,
    test_roots: Mapping[str, Path],
    repo_root: Path,
    jobs: str = "1",
    basetemp: Path | None = None,
) -> list[str]:
    if any(
        argument == "-m"
        or argument.startswith("-m")
        or argument == "--markexpr"
        or argument.startswith("--markexpr=")
        for argument in forwarded_pytest_args
    ):
        raise RuntimeError(
            "canonical marker selection is closed; forwarded -m/--markexpr is refused"
        )
    selections = forwarded_selection_args(forwarded_pytest_args)
    if selections:
        validate_forwarded_selections(suites, selections, test_roots, repo_root)
        pytest_args = list(forwarded_pytest_args)
    else:
        pytest_args = [
            *(str(test_roots[suite]) for suite in suites),
            *forwarded_pytest_args,
        ]
    if basetemp is not None and not explicit_basetemp(forwarded_pytest_args):
        pytest_args = [
            "--basetemp",
            str(basetemp),
            "-o",
            f"cache_dir={basetemp / 'cache'}",
            *pytest_args,
        ]
    if parallel_jobs_enabled(jobs):
        return ["-n", normalize_jobs(jobs), *pytest_args]
    return pytest_args


def explicit_basetemp(forwarded_pytest_args: list[str]) -> bool:
    return any(
        arg == "--basetemp" or arg.startswith("--basetemp=")
        for arg in forwarded_pytest_args
    )


def forwarded_selection_args(forwarded_pytest_args: list[str]) -> tuple[str, ...]:
    selections: list[str] = []
    for arg in forwarded_pytest_args:
        if arg.startswith("-"):
            continue
        candidate = arg.split("::", 1)[0]
        candidate_path = Path(candidate)
        if (
            candidate in {".", ".."}
            or candidate_path.exists()
            or candidate.endswith(".py")
            or candidate.startswith("src/")
            or "/" in candidate
            or "\\" in candidate
        ):
            selections.append(arg)
    return tuple(selections)


def validate_forwarded_selections(
    suites: tuple[str, ...],
    selections: tuple[str, ...],
    test_roots: Mapping[str, Path],
    repo_root: Path,
) -> None:
    allowed_roots = tuple(test_roots[suite].resolve() for suite in suites)
    for selection in selections:
        path_text = selection.split("::", 1)[0]
        selection_path = Path(path_text)
        if not selection_path.is_absolute():
            selection_path = repo_root / selection_path
        resolved = selection_path.resolve()
        if not any(is_relative_to(resolved, root) for root in allowed_roots):
            roots = ", ".join(str(root.relative_to(repo_root)) for root in allowed_roots)
            raise RuntimeError(
                f"forwarded pytest selection {path_text!r} is outside selected "
                f"suite root(s): {roots}"
            )


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
