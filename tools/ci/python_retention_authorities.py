"""Cross-authority retention consistency and immutable governing-input bindings."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

from ci.python_type_ownership import (
    OwnershipManifest, OwnershipRule, load_manifest, module_name_for_path, resolve_rule,
)


TRANSITIONS = "tools/ci/python_retention_transitions.json"
SCHEMA = "repomap-python-retention-transitions-v1"
RETAINED = frozenset({"python_retained", "cross_language_contract"})
CHECKERS = (
    "python_retention_inventory.py", "python_retention_authorities.py",
    "python_retention_history.py", "python_retention_reporting.py",
    "python_fixture_authority.py", "python_quality_profiles.py", "python_quality_mypy.py",
    "python_type_check.py", "python_type_ownership.py", "retained_python_ratchets.py",
    "retained_python_ratchet_lineage.py", "retained_python_comparison.py",
    "retained_python_records.py", "file_length_policy.py", "check_file_lengths.py",
)


class RetentionAuthorityError(ValueError):
    """Required retention authorities disagree or cannot be attested."""


def read_document(path: Path) -> dict:
    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise RetentionAuthorityError(f"required authority unreadable: {path.name}") from error
    if not isinstance(document, dict):
        raise RetentionAuthorityError(f"required authority malformed: {path.name}")
    return document


def validate_consistency(repo_root: Path, files: Sequence[dict], selected: Sequence[dict]) -> None:
    """A migration forecast preserves maintenance obligations until explicit admission."""
    manifest = load_manifest(repo_root / "tools/ci/python_type_ownership.json")
    ledger = read_document(repo_root / TRANSITIONS)
    if ledger.get("schema") != SCHEMA or not isinstance(ledger.get("records"), list):
        raise RetentionAuthorityError("invalid retention transition authority")
    records = ledger["records"]
    by_path: dict[str, list[dict]] = {}
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("path"), str)
                or record.get("disposition") not in {"pending_admission", "retained_python"}
                or not isinstance(record.get("reason"), str) or not record["reason"].strip()
                or not isinstance(record.get("superseded_rule"), dict)):
            raise RetentionAuthorityError("malformed retention transition record")
        by_path.setdefault(record["path"], []).append(record)
    validate_recovered_rules(repo_root, records)
    selection = {item["path"]: item for item in selected}
    for entry in files:
        if entry["root"] != "product" or not entry["maintained_executable"] or entry["confidence"] < 0.8:
            continue
        path = entry["path"]
        module = module_name_for_path(repo_root / path, repo_root / "src/main/python")
        rule = resolve_rule(module, manifest)
        if rule is None:
            raise RetentionAuthorityError(f"missing product ownership: {path}")
        retained = rule.ownership_class in RETAINED
        enrolled = path in selection
        if retained != enrolled or (entry["status"] == "retained_ratchet") != enrolled:
            raise RetentionAuthorityError(f"contradictory retained ownership/selection: {path}")
        if entry.get("governing_profile") != "retained_python_ratchets":
            raise RetentionAuthorityError(f"eligible product lacks governing profile: {path}")
        if enrolled:
            item = selection[path]
            if (item["module"] != module or item["ownership_class"] != rule.ownership_class
                    or item["tier"] != rule.enforcement_tier):
                raise RetentionAuthorityError(f"selection disagrees with effective ownership: {path}")
        else:
            history = by_path.get(path, [])
            if (not history or history[-1]["disposition"] != "pending_admission"
                    or history[-1]["superseded_rule"] != asdict(rule)):
                raise RetentionAuthorityError(f"migration forecast lacks compatible maintenance transition: {path}")


def validate_recovered_rules(repo_root: Path, records: Sequence[dict]) -> None:
    """Specific superseded rationale is verified against immutable source bytes."""
    versions: dict[str, tuple[str, OwnershipManifest]] = {}
    for record in records:
        if record["disposition"] != "retained_python":
            continue
        revision = record.get("source_commit")
        if (not isinstance(revision, str) or len(revision) not in (40, 64)
                or any(c not in "0123456789abcdef" for c in revision)):
            raise RetentionAuthorityError("retained transition lacks immutable prior authority")
        if revision not in versions:
            run = subprocess.run(
                ["git", "show", f"{revision}:tools/ci/python_type_ownership.json"],
                cwd=repo_root, capture_output=True, check=False, timeout=30,
            )
            try:
                if run.returncode:
                    raise ValueError("missing prior manifest")
                document = json.loads(run.stdout)
                prior = OwnershipManifest(tuple(OwnershipRule(**item) for item in document["entries"]))
            except (ValueError, KeyError, TypeError) as error:
                raise RetentionAuthorityError("superseded ownership authority unavailable") from error
            versions[revision] = hashlib.sha256(run.stdout).hexdigest(), prior
        digest, prior = versions[revision]
        module = module_name_for_path(repo_root / record["path"], repo_root / "src/main/python")
        old_rule = resolve_rule(module, prior)
        if (digest != record.get("source_manifest_sha256") or old_rule is None
                or asdict(old_rule) != record["superseded_rule"]):
            raise RetentionAuthorityError("superseded ownership rationale does not match historical authority")


def validate_transition_history(repo_root: Path, revisions: Sequence[str]) -> None:
    """Previously published rationale remains an exact append-only prefix."""
    current = read_document(repo_root / TRANSITIONS)["records"]
    for revision in revisions:
        listed = subprocess.run(["git", "ls-tree", revision, "--", TRANSITIONS],
                                cwd=repo_root, capture_output=True, check=False, timeout=30)
        if listed.returncode:
            raise RetentionAuthorityError("transition history cannot be established")
        if not listed.stdout:
            continue
        prior = subprocess.run(["git", "show", f"{revision}:{TRANSITIONS}"],
                               cwd=repo_root, capture_output=True, check=False, timeout=30)
        try:
            old = json.loads(prior.stdout)["records"]
            if prior.returncode or not isinstance(old, list):
                raise ValueError("invalid prior transitions")
        except (ValueError, KeyError, TypeError) as error:
            raise RetentionAuthorityError("prior transition authority malformed") from error
        if current[:len(old)] != old:
            raise RetentionAuthorityError("retention transition rationale is not append-only")


def validate_ownership_transitions(repo_root: Path, files: Sequence[dict], revisions: Sequence[str]) -> None:
    """A newly retained forecast needs its exact prior rule in transition evidence."""
    authority_path = "tools/ci/python_type_ownership.json"
    current = load_manifest(repo_root / authority_path)
    records = read_document(repo_root / TRANSITIONS)["records"]
    for revision in revisions:
        listed = subprocess.run(["git", "ls-tree", revision, "--", authority_path],
                                cwd=repo_root, capture_output=True, check=False, timeout=30)
        if listed.returncode:
            raise RetentionAuthorityError("prior ownership lineage unavailable")
        if not listed.stdout:
            continue
        run = subprocess.run(["git", "show", f"{revision}:{authority_path}"],
                             cwd=repo_root, capture_output=True, check=False, timeout=30)
        try:
            document = json.loads(run.stdout)
            if (run.returncode or document["schema"] != "repomap-python-type-ownership-v1"
                    or document["resolution"] != "longest-component-prefix-wins"):
                raise ValueError("invalid ownership lineage")
            prior = OwnershipManifest(tuple(OwnershipRule(**item) for item in document["entries"]))
        except (ValueError, KeyError, TypeError) as error:
            raise RetentionAuthorityError("prior ownership authority malformed") from error
        for entry in files:
            if entry["root"] != "product" or entry["status"] != "retained_ratchet":
                continue
            module = module_name_for_path(repo_root / entry["path"], repo_root / "src/main/python")
            before, after = resolve_rule(module, prior), resolve_rule(module, current)
            if before is None or before.ownership_class in RETAINED:
                continue
            if after is None or not any(
                record["path"] == entry["path"] and record["disposition"] == "retained_python"
                and record["superseded_rule"] == asdict(before)
                and record.get("current_rule") == asdict(after)
                for record in records
            ):
                raise RetentionAuthorityError(f"retained admission lost specific superseded rationale: {entry['path']}")


def bind_inputs(repo_root: Path, inventory_path: Path, ratchet_path: Path) -> dict[str, dict]:
    """Bind configuration, executable checker authority and referenced transition evidence."""
    required = {
        inventory_path, ratchet_path, repo_root / "pyproject.toml",
        repo_root / "tools/ci/python_type_ownership.json",
        repo_root / "tools/ci/python_fixture_authority.json",
        repo_root / TRANSITIONS,
        repo_root / "tools/ci/retained_python_scope_transitions.json",
    }
    required.update((repo_root / "tools/ci").glob("python_*.py"))
    required.update((repo_root / "tools/ci").glob("retained_python_*.py"))
    required.update(repo_root / "tools/ci" / name for name in CHECKERS)
    fixture_document = read_document(repo_root / "tools/ci/python_fixture_authority.json")
    fixture_entries = fixture_document.get("entries")
    if not isinstance(fixture_entries, list):
        raise RetentionAuthorityError("malformed fixture authority bindings")
    for entry in fixture_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise RetentionAuthorityError("malformed fixture entry binding")
        required.add(repo_root / entry["path"])
        consumers = entry.get("consumer")
        if not isinstance(consumers, list) or any(not isinstance(p, str) for p in consumers):
            raise RetentionAuthorityError("malformed fixture consumer binding")
        required.update(repo_root / consumer for consumer in consumers)
        provenance = entry.get("provenance")
        if provenance is not None:
            if not isinstance(provenance, dict) or not isinstance(provenance.get("evidence_path"), str):
                raise RetentionAuthorityError("malformed fixture provenance binding")
            required.add(repo_root / provenance["evidence_path"])
    registry = read_document(repo_root / "tools/ci/retained_python_scope_transitions.json")
    records = registry.get("records")
    if not isinstance(records, list):
        raise RetentionAuthorityError("malformed scope transition authority")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("status_path"), str):
            raise RetentionAuthorityError("malformed scope transition evidence reference")
        required.add(repo_root / record["status_path"])
    bindings = {}
    for path in sorted(required):
        try:
            relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
            lexical = path.absolute().relative_to(repo_root.absolute()).as_posix()
            if relative != lexical or path.is_symlink() or not path.is_file():
                raise ValueError("missing or aliased authority")
            content = path.read_bytes()
        except (ValueError, OSError) as error:
            raise RetentionAuthorityError(f"required governing input unavailable: {path.name}") from error
        bindings[relative] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    return bindings


def verify_bindings(repo_root: Path, bindings: Mapping[str, dict], inventory_path: Path,
                    ratchet_path: Path) -> None:
    if bind_inputs(repo_root, inventory_path, ratchet_path) != bindings:
        raise RetentionAuthorityError("governing inputs changed during enforcement")
