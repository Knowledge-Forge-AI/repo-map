"""Observed bounded CLI rendering under a low child decimal-conversion limit."""

from __future__ import annotations

import sys
from pathlib import Path

from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_view._context_projection import project_compact_context
from repomap_test_support.resource_report_cli_files import private_directory, run_cloe


ROOT = Path(__file__).resolve().parents[6]


def _huge_report() -> tuple[str, bytes]:
    # Keep the decimal text independent of int-to-str conversion limits.  The
    # projection consumes an existing caller value; it does not invent a
    # counter from storage or run a context operation.
    decimal = "1" + "0" * 4799 + "7"
    count = 10**4800 + 7
    packet = {
        "status": "complete",
        "scope": {"backend": "sqlite"},
        "work_ledger": {"actual_bytes": count},
    }
    return decimal, encode_report(project_compact_context(packet))


def test_observed_human_rendering_preserves_huge_count_under_low_child_limit(
    tmp_path: Path,
) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "huge.json"
    decimal, data = _huge_report()
    assert len(data) <= 8193
    path.write_bytes(data)
    path.chmod(0o600)
    before = sys.get_int_max_str_digits()
    env = {"PYTHONINTMAXSTRDIGITS": "640"}
    shown_json = run_cloe(
        "ops", "resource-report", "show", "--input", str(path), "--json",
        cwd=ROOT, extra_env=env,
    )
    shown_text = run_cloe(
        "ops", "resource-report", "show", "--input", str(path), cwd=ROOT,
        extra_env=env,
    )
    assert shown_json.returncode == shown_text.returncode == 0
    assert shown_json.stderr == shown_text.stderr == ""
    assert shown_json.stdout.encode("utf-8") == data
    actual_line = next(line for line in shown_text.stdout.splitlines() if "actual_bytes:" in line)
    assert actual_line == f"  actual_bytes: {decimal} bytes (measured, ledger_counter)"
    assert len(shown_text.stdout.encode("utf-8")) < len(data) + 1024
    assert "validation: format and domain only" in shown_text.stdout
    assert str(tmp_path) not in shown_text.stdout
    assert sys.get_int_max_str_digits() == before
