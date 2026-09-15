from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]

EXPECTED_DEPENDABOT_POLICY = """\
version: 2

updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "gomod"
    directory: "/src/main/go"
    schedule:
      interval: "weekly"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
"""


def test_security0_dependabot_policy_is_minimal_and_exact() -> None:
    policy_path = REPO_ROOT / ".github" / "dependabot.yml"

    assert policy_path.read_text(encoding="utf-8") == EXPECTED_DEPENDABOT_POLICY
    assert sorted(
        path.relative_to(REPO_ROOT)
        for path in REPO_ROOT.glob("**/dependabot.y*ml")
    ) == [Path(".github/dependabot.yml")]
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "src/main/go/go.mod").is_file()
    assert any((REPO_ROOT / ".github/workflows").glob("*.yml"))

    policy = EXPECTED_DEPENDABOT_POLICY.lower()
    for prohibited in (
        "ignore:",
        "groups:",
        "registries:",
        "assignees:",
        "reviewers:",
        "password:",
        "token:",
        "secret:",
        "${{",
    ):
        assert prohibited not in policy
    assert re.search(r"\b\d+\.\d+(?:\.\d+)?\b", policy) is None


def test_security0_root_security_policy_is_conservative() -> None:
    policy = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    lowered = policy.lower()
    normalized = " ".join(lowered.split())

    assert policy.startswith("# Security Policy\n")
    for heading in (
        "## Supported Versions",
        "## Reporting A Vulnerability",
        "## What Reporters Can Expect",
        "## Scope",
        "## Disclosure And Good-Faith Boundaries",
    ):
        assert heading in policy
    assert "`main` (unreleased)" in policy
    assert "only supported development line" in normalized
    assert "do not open a public report" in normalized
    assert "issues, discussions, pull requests, or social media" in normalized
    assert "when this repository is public" in normalized
    assert "security" in lowered and "report a vulnerability" in lowered
    assert "pre-established private maintainer channel" in normalized
    assert "ordinary bugs without a plausible security impact" in normalized
    assert "normal issue process" in normalized

    assert re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", policy, re.IGNORECASE) is None
    assert re.search(r"\b(?:within|no later than)\s+\d+", lowered) is None
    for prohibited in (
        "bug bounty",
        "compensation",
        "safe harbor",
        "safe-harbor",
        "business days",
        "response sla",
        "remediation sla",
        "example.com",
        "example.org",
        "to" + "do",
        "t" + "bd",
    ):
        assert prohibited not in lowered
    assert "private vulnerability reporting is currently enabled" not in lowered


def test_security0_documentation_scope_includes_security_policy() -> None:
    reference_policy = (
        REPO_ROOT / "docs/contrib/documentation-reference-policy.md"
    ).read_text(encoding="utf-8")

    scope = reference_policy.split("## Repository Trust Model", 1)[0]
    assert "- `SECURITY.md`;" in scope
    assert "If a new root document such as\n`SECURITY.md` is added later" not in scope
