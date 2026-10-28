"""ADR 0103 Betterleaks configuration and command contract (stdlib only; the scanner itself is never run here).

The repository configuration extends every Betterleaks 1.8.1 default, restates the upstream global filter verbatim
(MIT, pinned v1.8.1 ``config/config.go``) and adds one conjunction: the generic rule, the exact public metadata path,
the exact public OpenPGP fingerprint and its immediate ``GPG_`` context. Native pinned-scanner canaries, which this
owner does not replace, prove the rule behavior; these tests pin the bytes, structure, scope and command.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tomllib

from ci.pre_review_checks import checks
from ci.pre_review_records import ROOT
from repomap_test_support import d12_native_python_proof as proof

CONFIG = Path("tools/ci/betterleaks.toml")
CONFIG_SHA256 = "8bdcf25ee360db68a0646353d05ab2df34832412f78db3dc3f2257ff392f5fbb"
PROTOTYPE_SHA256 = "1b9998be9a618d11abdc4842684ed79f23a45447b00ad2aadeee71d5a9160cba"  # natively canary-tested bytes
ATTRIBUTION = (  # the only lines added to the prototype: pinned upstream MIT attribution of the copied filter
    "# Global filter copied from github.com/betterleaks/betterleaks tag v1.8.1, config/config.go.",
    "# Copyright (c) 2026 Zachary Rice. Used under the MIT License.")
UPSTREAM_GLOBAL_FILTER_SHA256 = "df4544a3eeff409d71edc95cc608bad124dc06e42c6436ddf77feda491a267d5"
FINGERPRINT = "7169605F62C751356D054A26A821E680E5FA6305"  # public OpenPGP key ID of the base image, not a credential
FINGERPRINT_SHA256 = "6c3b7674b58d9f7266cd8b823ecf469b0a03d1bf2c8c24df1d0121d8e818f1fa"
EXACT_CLASSIFICATION = (
    'finding["rule_id"] == "generic-api-key" &&\n'
    f'attributes["path"] == "{proof.ENVELOPE_PATH}" &&\n'
    f'finding["secret"] == "{FINGERPRINT}" &&\n'
    'finding["match_start_idx"] >= 4 &&\n'
    'finding["fragment_raw"][finding["match_start_idx"]-4:finding["match_start_idx"]] == "GPG_"'
)
# Betterleaks 1.8.1 generic-api-key regex, copied verbatim from the pinned upstream config/betterleaks.toml (unlike
# gitleaks, no leading identifier prefix), for a raw static check only; native canaries remain the rule authority.
GENERIC_API_KEY = re.compile(
    r'''(?i)(?:access|auth|(?-i:[Aa]pi|API)|credential|creds|key|secret|token)(?:[ \t\w.-]{0,20})[\s'"]{0,3}'''
    r'''(?:=|>|:{1,3}=|\|\||:|=>|\?=|,)[\x60'"\s=]{0,5}([\w.=-]{10,150}|[a-z0-9][a-z0-9+/]{11,}={0,3})'''
    r'''(?:\\?['"\x60]|[\s;]|\\[nr]|$)''')
SCAN_ROOTS = ("src/main", "tools", ".github", "docs/adr", "docs/contrib", "docs/ops", "docs/testing", "README.md",
              "AGENTS.md", "CLAUDE.md", "pyproject.toml")


def _config() -> dict[str, object]:
    return tomllib.loads((ROOT / CONFIG).read_text(encoding="utf-8"))


def _filter_parts() -> tuple[str, str]:
    text = _config()["filter"]
    assert isinstance(text, str)
    upstream, separator, exact = text.rpartition(") || (\n")
    assert separator and upstream.startswith("(") and exact.endswith("\n)\n"), text[:80]
    return upstream[1:], exact.removesuffix("\n)\n")


def test_config_bytes_are_the_tested_prototype_extending_every_upstream_default() -> None:
    assert hashlib.sha256((ROOT / CONFIG).read_bytes()).hexdigest() == CONFIG_SHA256
    config = _config()
    assert set(config) == {"betterleaksMinVersion", "filter", "extend"}, "no rule, allowlist, prefilter or baseline"
    assert config["betterleaksMinVersion"] == "1.8.1" and config["extend"] == {"useDefault": True}
    text = (ROOT / CONFIG).read_text(encoding="utf-8")
    assert "Betterleaks 1.8.1" in text and "(MIT)" in text, "upstream attribution of the copied filter"
    lines = text.splitlines(keepends=True)
    assert all(f"{line}\n" in lines for line in ATTRIBUTION)
    prototype = "".join(line for line in lines if line.rstrip("\n") not in ATTRIBUTION)
    assert hashlib.sha256(prototype.encode("utf-8")).hexdigest() == PROTOTYPE_SHA256, "only attribution was added"
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    for forbidden in ("[[rules]]", "disabledRules", "allowlist", "prefilter", "validat", "paths", "regexTarget"):
        assert forbidden not in body, forbidden


def test_upstream_global_filter_is_restated_verbatim_before_one_exact_disjunct() -> None:
    upstream, exact = _filter_parts()
    assert hashlib.sha256(upstream.encode("utf-8")).hexdigest() == UPSTREAM_GLOBAL_FILTER_SHA256
    assert upstream.startswith('(matchesAny(finding["secret"], [') and upstream.count("containsAny(") == 1
    assert exact == EXACT_CLASSIFICATION
    assert exact.count("&&") == 4 and "||" not in exact and "matches" not in exact, "a conjunction, no pattern"


def test_exact_scope_value_and_context_bind_only_the_unchanged_public_metadata() -> None:
    envelope = (ROOT / proof.ENVELOPE_PATH).read_bytes()
    assert hashlib.sha256(envelope).hexdigest() == proof.ENVELOPE_SHA256, "the scanned input bytes are unchanged"
    assert hashlib.sha256(FINGERPRINT.encode()).hexdigest() == FINGERPRINT_SHA256
    assert re.fullmatch(r"[0-9A-F]{40}", FINGERPRINT), "a v4 OpenPGP fingerprint shape"
    text = envelope.decode("utf-8")
    starts = [m.start() for m in re.finditer(FINGERPRINT, text)]
    assert len(starts) == 4 and all(text[i - 8:i] == "GPG_KEY=" for i in starts), "only the GPG_KEY values"
    matches = [m for m in GENERIC_API_KEY.finditer(text) if m.group(1) == FINGERPRINT]
    assert len(matches) == 4 and all(text[m.start() - 4:m.start()] == "GPG_" for m in matches)
    assert all(m.group(0).upper().startswith("KEY=") for m in matches), "the match starts at KEY, after GPG_"


def test_classification_rejects_other_values_paths_and_contexts_by_construction() -> None:
    _upstream, exact = _filter_parts()
    clauses = exact.split(" &&\n")
    assert clauses == [
        'finding["rule_id"] == "generic-api-key"', f'attributes["path"] == "{proof.ENVELOPE_PATH}"',
        f'finding["secret"] == "{FINGERPRINT}"', 'finding["match_start_idx"] >= 4',
        'finding["fragment_raw"][finding["match_start_idx"]-4:finding["match_start_idx"]] == "GPG_"']
    assert all(" == " in clause or " >= " in clause for clause in clauses), "equality or bound, never a prefix"
    assert exact.count(FINGERPRINT) == 1 and exact.count(proof.ENVELOPE_PATH) == 1
    canaries = (FINGERPRINT[:-1] + "0", FINGERPRINT.lower(), "A" * 40)
    assert all(f'finding["secret"] == "{value}"' not in exact for value in canaries)


def test_config_source_creates_no_raw_generic_match_of_its_own() -> None:
    text = (ROOT / CONFIG).read_text(encoding="utf-8")
    assert not list(GENERIC_API_KEY.finditer(text)), "the fingerprint is never in a keyword-assignment context"
    assert text.count(FINGERPRINT) == 1 and "GPG_KEY" not in text


def test_pre_review_command_passes_the_explicit_config_and_keeps_every_scan_input(tmp_path: Path) -> None:
    tool_root = tmp_path / "tool-root"
    found = [check for check in checks(tmp_path, tool_root) if check.name == "betterleaks"]
    assert len(found) == 1
    check = found[0]
    assert check.command == (
        str(tool_root / "bin/betterleaks"), "dir", *SCAN_ROOTS, f"--config={CONFIG.as_posix()}", "--no-banner",
        "--redact=100", "--report-format=json", "--report-path=-")
    assert check.cwd == ROOT and (check.cwd / CONFIG).is_file() and check.policy == "exit-zero"
    assert not check.python_owned and sum(arg.startswith("--config") for arg in check.command) == 1
    assert not any(arg.startswith(("--baseline", "--enable-rule", "--ignore", "--log-opts")) for arg in check.command)
    unbound = next(item for item in checks(tmp_path) if item.name == "betterleaks")
    assert unbound.command[0] == "betterleaks" and unbound.command[1:] == check.command[1:]
