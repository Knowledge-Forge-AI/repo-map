from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ci.run_pre_review import (
    Check,
    ROOT,
    checks,
    evaluate,
    execute_all,
)
from ci.pre_review_evidence import LOG_CAP_BYTES, finalize_evidence, verify_evidence


CORE = {
    "actionlint",
    "zizmor",
    "pip-audit",
    "govulncheck",
    "semgrep",
    "betterleaks",
    "malskanner",
    "prompt-defense-audit",
}


def test_pre_review_inventory_supports_unbound_tool_discovery(tmp_path: Path) -> None:
    semgrep = next(check for check in checks(tmp_path) if check.name == "semgrep")

    assert semgrep.command[0] == "semgrep"
    assert semgrep.python_entry == "console-script"


def test_ci2a_pre_review_inventory_is_closed_and_complete(tmp_path: Path) -> None:
    tool_root = tmp_path / "tool-root"
    selected = checks(tmp_path, tool_root)
    names = [check.name for check in selected]

    assert len(names) == len(set(names))
    assert CORE <= set(names)
    assert {
        "ruff",
        "pyflakes",
        "mypy",
        "retained-python-ratchets",
        "python-retention-inventory",
        "file-length",
        "python-compile",
        "scanner-suppressions",
        "liquibase",
        "hadolint",
        "generated-code-drift",
    } <= set(names)
    drift = next(check for check in selected if check.name == "generated-code-drift")
    assert Path(drift.command[-1]).is_relative_to(tmp_path)
    assert drift.command[2:4] == ("--uv", str(tool_root / "bin/uv"))
    python_checks = {check.name for check in selected if check.python_owned}
    assert python_checks == {
        "ruff",
        "pyflakes",
        "mypy",
        "retained-python-ratchets",
        "python-retention-inventory",
        "ci-topology",
        "file-length",
        "python-compile",
        "pip-audit",
        "semgrep",
        "prompt-defense-audit",
        "scanner-suppressions",
        "liquibase",
        "generated-code-drift",
    }
    interpreter_checks = {
        check.name
        for check in selected
        if check.python_owned and check.python_entry == "interpreter"
    }
    assert all(
        check.command[0] == sys.executable
        for check in selected
        if check.name in interpreter_checks
    )
    semgrep = next(check for check in selected if check.name == "semgrep")
    assert semgrep.python_owned
    assert semgrep.python_entry == "console-script"
    assert semgrep.command[0] == str(tool_root / "python/bin/semgrep")
    assert semgrep.command[1] == "scan"
    assert "-m" not in semgrep.command
    mypy = next(check for check in selected if check.name == "mypy")
    assert mypy.command == (
        sys.executable,
        "tools/ci/python_type_check.py",
        "--manifest",
        "tools/ci/python_type_ownership.json",
    )
    ratchet = next(
        check for check in selected if check.name == "retained-python-ratchets"
    )
    assert ratchet.command == (
        sys.executable,
        "tools/ci/retained_python_ratchets.py",
        "--baseline",
        "tools/ci/retained_python_ratchets.json",
        "--scope-transitions",
        "tools/ci/retained_python_scope_transitions.json",
    )
    assert ratchet.policy == "retained-python-ratchets"
    assert ratchet.python_owned
    assert not {"--generate-baseline", "--fix", "--exit-zero"} & set(
        ratchet.command
    )


def test_retained_ratchet_exit_one_is_policy_and_exit_two_is_tool_failure() -> None:
    check = Check(
        "retained-python-ratchets",
        ("python", "tools/ci/retained_python_ratchets.py"),
        policy="retained-python-ratchets",
    )

    finding = json.dumps(
        {
            "schema": "repomap-retained-python-ratchets-result-v1",
            "classification": "policy-finding",
        }
    )
    tool_failure = json.dumps(
        {
            "schema": "repomap-retained-python-ratchets-result-v1",
            "classification": "tool-failure",
        }
    )

    assert evaluate(check, 1, finding)[2] == "policy-finding"
    assert evaluate(check, 2, tool_failure)[2] == "tool-failure"

    message_collision = json.dumps(
        {
            "schema": "repomap-retained-python-ratchets-result-v1",
            "classification": "policy-finding",
            "ruff": {"comparison": {"new": [{"message": "No module named public"}]}},
        }
    )
    assert evaluate(check, 1, message_collision)[2] == "policy-finding"


def test_global_and_legacy_ratchets_remain_separate_and_unchanged(
    tmp_path: Path,
) -> None:
    selected = {check.name: check for check in checks(tmp_path)}

    assert selected["ruff"].command[1:4] == ("-m", "ruff", "check")
    assert selected["pyflakes"].command[1:] == (
        "-m",
        "ruff",
        "check",
        "--select",
        "F",
        "src/main/python/repomap_kg/runtime",
        "src/main/python/repomap_kg/graph",
        "src/main/python/repomap_kg/server",
    )
    assert selected["file-length"].command[1:] == (
        "tools/ci/check_file_lengths.py",
        "--format",
        "json",
    )
    joined = " ".join(
        argument for check in selected.values() for argument in check.command
    )
    assert "--fix" not in joined
    assert "--exit-zero" not in joined


def test_semgrep_console_script_keeps_sealed_python_attestation(tmp_path: Path) -> None:
    tool_root = tmp_path / "tool-root"
    executable = tool_root / "python/bin/semgrep"
    selected = (
        Check(
            "semgrep",
            (str(executable), "scan"),
            python_owned=True,
            python_entry="console-script",
        ),
    )

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, "{}", "")

    results = execute_all(
        selected,
        tmp_path / "evidence",
        runner=runner,
        tool_root=tool_root,
    )

    assert results[0].status == "passed"
    assert results[0].interpreter == "<tool-python>"
    log = (tmp_path / "evidence/semgrep.log").read_text(encoding="utf-8")
    assert "interpreter=<tool-python>" in log
    assert 'command=["<tool-python-bin>/semgrep", "scan"]' in log


def test_semgrep_deprecated_module_entry_is_not_an_accepted_console_owner(
    tmp_path: Path,
) -> None:
    selected = (
        Check(
            "semgrep",
            (sys.executable, "-m", "semgrep", "scan"),
            python_owned=True,
            python_entry="console-script",
        ),
    )

    results = execute_all(
        selected,
        tmp_path / "evidence",
        runner=lambda *_args, **_kwargs: pytest.fail("owner mismatch must fail first"),
        tool_root=tmp_path / "tool-root",
    )

    assert results[0].classification == "tool-failure"
    assert results[0].returncode is None


def test_semgrep_exit_one_is_finding_and_exit_two_is_tool_failure() -> None:
    check = Check("semgrep", ("semgrep", "scan"))

    assert evaluate(check, 1, "{}")[2] == "policy-finding"
    assert evaluate(check, 2, "{}")[2] == "tool-failure"


def test_generated_drift_exit_one_is_drift_and_exit_two_is_tool_failure() -> None:
    check = Check("generated-code-drift", ("python", "check_generated_drift.py"))

    assert evaluate(check, 1, "{}")[2] == "check-failure"
    assert evaluate(check, 2, "{}")[2] == "tool-failure"


def test_ci2a_pre_review_executes_every_check_before_combined_failure(
    tmp_path: Path,
) -> None:
    invoked = []

    def runner(command, **_kwargs):
        invoked.append(command[0])
        return subprocess.CompletedProcess(command, 9 if command[0] == "first" else 0, "", "")

    selected = (
        Check("first", ("first",)),
        Check("second", ("second",)),
        Check("third", ("third",)),
    )
    results = execute_all(selected, tmp_path, runner=runner)

    assert invoked == ["first", "second", "third"]
    assert [result.status for result in results] == ["failed", "passed", "passed"]


def test_python_checks_record_one_interpreter_and_module_absence_is_operational(
    tmp_path: Path,
) -> None:
    observed_env = {}

    def runner(command, **kwargs):
        observed_env.update(kwargs["env"])
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "/sealed/python: No module named ruff\n",
        )

    selected = (Check("ruff", (sys.executable, "-m", "ruff"), python_owned=True),)
    results = execute_all(selected, tmp_path / "evidence", runner=runner)

    assert results[0].classification == "tool-failure"
    assert results[0].interpreter == "<tool-python>"
    assert observed_env["MYPYPATH"] == str(ROOT / "src/main/python")
    assert "tool/bootstrap failure" in results[0].detail
    assert "interpreter=<tool-python>" in (
        tmp_path / "evidence/ruff.log"
    ).read_text(encoding="utf-8")


def test_evidence_manifest_enforces_the_closed_hashed_set(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    selected = (Check("one", ("one",)), Check("two", ("two",)))
    observed_env = []

    def runner(command, **kwargs):
        observed_env.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    results = execute_all(selected, evidence, runner=runner)
    finalize_evidence(evidence, selected, results)

    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["artifacts"]} == {
        "one.log",
        "two.log",
        "results.json",
    }
    assert all(item["size_bytes"] > 0 and len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert set(path.name for path in evidence.iterdir()) == {
        "one.log",
        "two.log",
        "results.json",
        "manifest.json",
    }
    assert not tuple(evidence.rglob("*.pyc"))
    assert not tuple(evidence.rglob("__pycache__"))
    assert all(env["PYTHONDONTWRITEBYTECODE"] == "1" for env in observed_env)
    assert all(
        not Path(env["PYTHONPYCACHEPREFIX"]).is_relative_to(evidence)
        for env in observed_env
    )
    verify_evidence(evidence, selected)

    (evidence / "unexpected.txt").write_text("not declared", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected evidence path"):
        verify_evidence(evidence, selected)


def test_evidence_manifest_rejects_tampering_and_oversized_logs(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    selected = (Check("one", ("one",)),)

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, "x" * (LOG_CAP_BYTES * 2), "")

    results = execute_all(selected, evidence, runner=runner)
    finalize_evidence(evidence, selected, results)
    assert (evidence / "one.log").stat().st_size <= LOG_CAP_BYTES
    (evidence / "one.log").write_text("changed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="(?:size|digest) mismatch"):
        verify_evidence(evidence, selected)


def test_ci2a_tool_manifest_records_every_adoption_field() -> None:
    manifest = json.loads(
        Path("tools/ci/pre_review_tools.json").read_text(encoding="utf-8")
    )
    required = {
        "product",
        "repository",
        "license",
        "version",
        "immutable_pin",
        "integrity",
        "linux_architecture_support",
        "network_behavior",
        "exit_semantics",
        "machine_readable_output",
        "current_baseline",
        "suppression_mechanism",
        "blocking_mapping",
        "sanitized_artifact_policy",
    }
    expected = CORE | {"golangci-lint", "hadolint", "liquibase", "uv"}

    assert expected <= set(manifest["tools"])
    for name in expected:
        assert required <= set(manifest["tools"][name]), name


def test_retention_inventory_executes_profiles_in_owned_aggregate(tmp_path: Path) -> None:
    check = next(item for item in checks(tmp_path) if item.name == "python-retention-inventory")
    assert check.python_owned
    assert check.command == (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json")
    assert evaluate(check, 1, '{"status":"failed"}')[0] == "failed"
    forged = json.dumps({"status": "passed", "enforcement_complete": True, "cohort_regressions": ["c1"]})
    status, _, classification = evaluate(check, 0, forged)
    assert status == "failed" and classification == "ratchet-regression"
