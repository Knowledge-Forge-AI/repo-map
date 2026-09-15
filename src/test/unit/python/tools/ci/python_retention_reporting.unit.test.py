"""Inventory reporting retains findings and bounded readable summaries."""
from __future__ import annotations

import json

from ci import python_retention_inventory as inventory


def test_compact_profile_preserves_all_findings_and_nonidentical_aliases() -> None:
    findings = [{"path": "tools/example.py", "message": "large finding " * 30_000}]
    checked = {"status": "failed", "findings": findings, "completed": True}
    result = {"status": "failed", "checks": {"mypy": checked}, "mypy": checked,
              "ruff": {"status": "not-run"}, "unknown_paths": ["tools/other.py"]}
    compact = inventory.compact_profile_result(result)
    assert compact["checks"]["mypy"] == checked
    assert "mypy" not in compact
    assert compact["ruff"] == result["ruff"]
    assert compact["unknown_paths"] == result["unknown_paths"]
    assert json.loads(json.dumps(compact))["checks"]["mypy"]["findings"] == findings
    assert len(json.dumps(compact)) < len(json.dumps(result)) / 1.5


def test_format_compact_summary_passed() -> None:
    result = {
        "status": "passed",
        "counts": {"total_files": 10},
        "eligible": {"product": ["src/main/python/a.py"], "tools": ["tools/b.py"]},
        "assigned": {"product": ["src/main/python/a.py"], "tools": ["tools/b.py"]},
        "enforced": {"product": ["src/main/python/a.py"], "tools": ["tools/b.py"]},
        "eligible_minus_enforced": {"product": [], "tools": []},
        "check_results": {
            "product": {"status": "passed", "returncode": 0},
            "tools": {"status": "passed"},
        },
    }
    summary = inventory.format_compact_summary(result, multiline=False)
    assert "status=passed" in summary
    assert "census=10" in summary
    assert "residual=0" in summary
    assert "product=passed" in summary
    assert "tools=passed" in summary


def test_format_compact_summary_failed_with_per_root_breakdown() -> None:
    residual_tools = [f"tools/t{i}.py" for i in range(10)]
    result = {
        "status": "failed",
        "counts": {"total_files": 100},
        "eligible": {
            "product": ["src/main/python/p.py"],
            "tools": residual_tools,
            "test_support": ["src/test/support/s.py"],
            "conftest": ["src/test/conftest.py"],
        },
        "assigned": {
            "product": ["src/main/python/p.py"],
            "tools": residual_tools,
            "test_support": ["src/test/support/s.py"],
            "conftest": ["src/test/conftest.py"],
        },
        "enforced": {
            "product": [],
            "tools": [],
            "test_support": [],
            "conftest": ["src/test/conftest.py"],
        },
        "eligible_minus_enforced": {
            "product": ["src/main/python/p.py"],
            "tools": residual_tools,
            "test_support": ["src/test/support/s.py"],
            "conftest": [],
        },
        "check_results": {
            "product": {"status": "failed", "returncode": 2},  # exit 2 -> tool-failure
            "tools": {"status": "failed", "classification": "tool-failure"},
            "test_support": {"status": "failed"},  # finding
            "conftest": {"status": "passed"},
        },
    }
    summary_single = inventory.format_compact_summary(result, max_examples=3, multiline=False)
    assert "status=failed" in summary_single
    assert "census=100" in summary_single
    assert "residual=12" in summary_single
    assert "product=tool-failure (1 residual)" in summary_single
    assert "tools=tool-failure (10 residual)" in summary_single
    assert "test_support=finding (1 residual)" in summary_single
    assert "conftest=passed" in summary_single
    # Bounded examples: tools has 10 items, but only 3 are shown
    assert "tools=['tools/t0.py', 'tools/t1.py', 'tools/t2.py']" in summary_single
    assert "tools/t3.py" not in summary_single

    summary_multi = inventory.format_compact_summary(result, max_examples=3, multiline=True)
    assert "status: failed" in summary_multi
    assert "residual: 12" in summary_multi
    assert "  product: tool-failure (1 residual)" in summary_multi
    assert "  tools: tool-failure (10 residual)" in summary_multi
    assert "  test_support: finding (1 residual)" in summary_multi
    assert "  conftest: passed" in summary_multi
    assert "bounded residual examples:" in summary_multi


def test_format_compact_summary_cohort_regression_bounded_and_size() -> None:
    regs = [f"reg-{i}" for i in range(5)]
    result = {
        "status": "failed",
        "classification": "ratchet-regression",
        "cohort_schema": "repomap-python-retention-cohorts-v1",
        "counts": {"total_files": 50},
        "eligible": {"tools": ["tools/a.py", "tools/b.py"]},
        "assigned": {"tools": ["tools/a.py", "tools/b.py"]},
        "enforced": {"tools": []},
        "eligible_minus_enforced": {"tools": ["tools/a.py", "tools/b.py"]},
        "cohorts": [f"c-{i}" for i in range(5)],
        "cohort_regressions": regs,
        "duration_seconds": 2.5,
        "check_results": {"tools": {"status": "failed"}},
        "raw_payload_blob": "x" * 20_000,
    }
    single = inventory.format_compact_summary(result, max_examples=3, multiline=False)
    assert "classification=ratchet-regression" in single
    assert "cohorts=5" in single
    assert "regressions=5 ['reg-0', 'reg-1', 'reg-2']" in single
    assert "reg-3" not in single
    assert "timing=2.50s" in single
    assert "closure=0/6" in single
    assert len(single) < 500
    assert "raw_payload_blob" not in single

    multi = inventory.format_compact_summary(result, max_examples=3, multiline=True)
    assert "status: failed" in multi
    assert "classification: ratchet-regression" in multi
    assert "cohorts: 5 total, regressions=5, timing=2.50s, closure=0/6" in multi
    assert "bounded regressions: ['reg-0', 'reg-1', 'reg-2']" in multi
    assert len(multi) < 800


def test_pre_review_evaluation_pending_residual_vs_admitted_regression() -> None:
    from ci.pre_review_evaluation import evaluate
    from ci.pre_review_records import Check
    check = Check("python-retention-inventory", ("python", "inventory.py"))

    pending_payload = json.dumps({
        "status": "failed",
        "counts": {"total_files": 10},
        "eligible": {"tools": ["tools/a.py"]},
        "assigned": {"tools": []},
        "eligible_minus_enforced": {"tools": ["tools/a.py"]},
    })
    st_p, _, cls_p = evaluate(check, 1, pending_payload)
    assert st_p == "failed"
    assert cls_p == "policy-finding"

    admitted_payload = json.dumps({
        "status": "failed",
        "counts": {"total_files": 10},
        "cohort_regressions": ["cohort-tools"],
        "classification": "ratchet-regression",
    })
    st_a, _, cls_a = evaluate(check, 1, admitted_payload)
    assert st_a == "failed"
    assert cls_a == "ratchet-regression"


def test_pre_review_evaluation_false_success_cannot_waive_regressions() -> None:
    from ci.pre_review_evaluation import evaluate
    from ci.pre_review_records import Check
    check = Check("python-retention-inventory", ("python", "inventory.py"))

    forged_cohort = json.dumps({
        "status": "passed",
        "enforcement_complete": True,
        "cohort_regressions": ["c1"],
        "counts": {"total_files": 10},
    })
    st, _, cls = evaluate(check, 0, forged_cohort)
    assert st == "failed"
    assert cls == "ratchet-regression"

    forged_cls = json.dumps({
        "status": "passed",
        "enforcement_complete": True,
        "classification": "ratchet-regression",
        "counts": {"total_files": 10},
    })
    st2, _, cls2 = evaluate(check, 0, forged_cls)
    assert st2 == "failed"
    assert cls2 == "ratchet-regression"

    forged_residual = json.dumps({
        "status": "passed",
        "enforcement_complete": True,
        "eligible_minus_enforced": {"tools": ["tools/a.py"]},
        "counts": {"total_files": 10},
    })
    st3, _, cls3 = evaluate(check, 0, forged_residual)
    assert st3 == "failed"
    assert cls3 == "policy-finding"


def test_pre_review_evaluation_malformed_signal_fails_as_tool_failure() -> None:
    from ci.pre_review_evaluation import evaluate
    from ci.pre_review_records import Check
    check = Check("python-retention-inventory", ("python", "inventory.py"))

    assert evaluate(check, 1, '{"status": "failed", "cohort_regressions": 123}')[2] == "tool-failure"
    assert evaluate(check, 1, '{"status": "failed", "cohort_results": "not-dict"}')[2] == "tool-failure"
    assert evaluate(check, 1, '{"status": "failed", "cohorts": 456}')[2] == "tool-failure"
    assert evaluate(check, 1, '{"status": "failed", "cohort_schema": 789}')[2] == "tool-failure"
    assert evaluate(check, 1, "{invalid-json")[2] == "tool-failure"


def test_render_inventory_text_compact_and_legacy_compatible() -> None:
    legacy = {
        "status": "passed",
        "counts": {"total_files": 5},
        "enforcement_complete": True,
    }
    rendered_legacy = inventory.render_inventory_text(legacy)
    assert rendered_legacy == "python-retention-inventory: passed\ncensus files: 5\nenforcement complete: True"

    cohort = {
        "status": "failed",
        "counts": {"total_files": 5},
        "enforcement_complete": False,
        "classification": "ratchet-regression",
        "cohort_regressions": ["c1"],
    }
    rendered_cohort = inventory.render_inventory_text(cohort)
    assert "classification: ratchet-regression" in rendered_cohort
    assert "cohort regressions: 1" in rendered_cohort
