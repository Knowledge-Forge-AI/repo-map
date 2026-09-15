#!/usr/bin/env python3
"""Validate the explicit role authority for Python test fixtures.

The authority is deliberately static.  It reads fixture and consumer source,
parses Python syntax, and inspects tokens; it never imports or executes a
fixture.  A fixture's path prefix is only the census boundary.  Its role is
determined by the reviewed manifest, its content digest, and the statically
verified consumer contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import sys
from typing import Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_fixture_static import (
    FixtureAuthorityError as FixtureAuthorityError,
    candidate_consumer_paths,
    execution_calls,
    parse_source,
    read_source,
    scan_unlisted_consumers,
    validate_consumer,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = "src/test/fixtures"
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("python_fixture_authority.json")
SCHEMA = "repomap-python-fixture-authority-v1"
RESULT_SCHEMA = "repomap-python-fixture-authority-result-v1"
ROLES = frozenset({"inert_data", "executable_first_party", "generated", "vendor"})
MODES = frozenset({
    "static_extraction",
    "direct_execution",
    "generated_input",
    "vendor_input",
})
SOURCE_SHAPES = frozenset({"valid", "malformed"})
CONSUMER_ROOTS = ("src/main/python/", "src/test/", "tools/")
MANIFEST_FIELDS = frozenset({"schema", "version", "fixture_root", "entries"})
ENTRY_FIELDS = frozenset({
    "path",
    "role",
    "content_sha256",
    "consumer",
    "consumption_mode",
    "source_shape",
    "rationale",
    "provenance",
})
HEX_DIGEST = frozenset("0123456789abcdef")
GENERIC_RATIONALES = frozenset({
    "fixture",
    "fixture data",
    "test data",
    "python fixture",
    "generated fixture",
    "vendor fixture",
})
@dataclass(frozen=True)
class FixtureRecord:
    """One reviewed fixture classification and its static consumer contract."""

    path: str
    role: str
    content_sha256: str
    consumer: tuple[str, ...]
    consumption_mode: str
    source_shape: str
    rationale: str
    provenance: Mapping[str, str] | None

    @property
    def family(self) -> str:
        """Return the literal fixture family expected in consumer source."""
        parts = PurePosixPath(self.path).parts[3:]
        if not parts:
            raise FixtureAuthorityError(f"fixture path has no family: {self.path}")
        return parts[1] if parts[0] in {"bulk", "discovery"} and len(parts) > 1 else parts[0]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe copy suitable for evidence output."""
        return {
            "path": self.path,
            "role": self.role,
            "content_sha256": self.content_sha256,
            "consumer": list(self.consumer),
            "consumption_mode": self.consumption_mode,
            "source_shape": self.source_shape,
            "rationale": self.rationale,
            "provenance": dict(self.provenance) if self.provenance is not None else None,
        }


@dataclass(frozen=True)
class FixtureAuthority:
    """Parsed manifest records, retained in deterministic path order."""

    version: int
    fixture_root: str
    records: tuple[FixtureRecord, ...]

    @property
    def by_path(self) -> dict[str, FixtureRecord]:
        return {record.path: record for record in self.records}


def _safe_relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FixtureAuthorityError(f"{label} path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise FixtureAuthorityError(f"{label} path escapes its root: {value}")
    return path.as_posix()


def _digest_is_valid(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX_DIGEST for c in value):
        raise FixtureAuthorityError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _parse_provenance(raw: object, role: str, path: str) -> Mapping[str, str] | None:
    if role not in {"generated", "vendor"}:
        if raw is not None:
            raise FixtureAuthorityError(f"provenance is inapplicable for {path}")
        return None
    if not isinstance(raw, dict) or set(raw) != {"producer", "evidence_path", "evidence_sha256"}:
        raise FixtureAuthorityError(f"{role} fixture requires producer and bound evidence: {path}")
    values = {key: raw[key] for key in raw}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise FixtureAuthorityError(f"{role} fixture provenance is incomplete: {path}")
    evidence_path = _safe_relative_path(values["evidence_path"], label="provenance evidence")
    if evidence_path.startswith(FIXTURE_ROOT + "/"):
        raise FixtureAuthorityError(f"{role} fixture provenance cannot cite fixture data: {path}")
    values["evidence_path"] = evidence_path
    values["evidence_sha256"] = _digest_is_valid(
        values["evidence_sha256"], label=f"{role} fixture evidence"
    )
    if values["producer"].strip().casefold() in {"generated", "vendor", "fixture", "source"}:
        raise FixtureAuthorityError(f"{role} fixture provenance is generic: {path}")
    return values


def _parse_entry(raw: object) -> FixtureRecord:
    if not isinstance(raw, dict) or set(raw) != ENTRY_FIELDS:
        raise FixtureAuthorityError("fixture authority entry fields are invalid")
    path = _safe_relative_path(raw.get("path"), label="fixture")
    if not path.startswith(FIXTURE_ROOT + "/") or not path.endswith(".py"):
        raise FixtureAuthorityError(f"fixture path is outside the Python fixture census: {path}")
    role = raw.get("role")
    if not isinstance(role, str) or role not in ROLES:
        raise FixtureAuthorityError(f"fixture role is invalid: {path}")
    mode = raw.get("consumption_mode")
    if not isinstance(mode, str) or mode not in MODES:
        raise FixtureAuthorityError(f"fixture consumption mode is invalid: {path}")
    expected_mode = {
        "inert_data": "static_extraction",
        "executable_first_party": "direct_execution",
        "generated": "generated_input",
        "vendor": "vendor_input",
    }[role]
    if mode != expected_mode:
        raise FixtureAuthorityError(f"fixture role and consumption mode disagree: {path}")
    shape = raw.get("source_shape")
    if not isinstance(shape, str) or shape not in SOURCE_SHAPES:
        raise FixtureAuthorityError(f"fixture source shape is invalid: {path}")
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < 24:
        raise FixtureAuthorityError(f"fixture rationale is missing or too short: {path}")
    if rationale.strip().casefold() in GENERIC_RATIONALES:
        raise FixtureAuthorityError(f"fixture rationale is generic: {path}")
    consumers = raw.get("consumer")
    if isinstance(consumers, str):
        consumers = [consumers]
    if (not isinstance(consumers, list) or not consumers
            or any(not isinstance(value, str) for value in consumers)):
        raise FixtureAuthorityError(f"fixture consumer declaration is invalid: {path}")
    parsed_consumers = tuple(_safe_relative_path(value, label="consumer") for value in consumers)
    if len(set(parsed_consumers)) != len(parsed_consumers) or parsed_consumers != tuple(sorted(parsed_consumers)):
        raise FixtureAuthorityError(f"fixture consumers are duplicated or unordered: {path}")
    if any(
        not consumer.endswith(".py") or not consumer.startswith(CONSUMER_ROOTS)
        for consumer in parsed_consumers
    ):
        raise FixtureAuthorityError(f"fixture consumer is outside maintained Python roots: {path}")
    return FixtureRecord(
        path=path,
        role=role,
        content_sha256=_digest_is_valid(raw.get("content_sha256"), label=f"fixture {path}"),
        consumer=parsed_consumers,
        consumption_mode=mode,
        source_shape=shape,
        rationale=rationale.strip(),
        provenance=_parse_provenance(raw.get("provenance"), role, path),
    )


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> FixtureAuthority:
    """Load and structurally validate the reviewable fixture authority."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureAuthorityError("fixture authority manifest is unreadable") from error
    if not isinstance(document, dict) or set(document) != MANIFEST_FIELDS:
        raise FixtureAuthorityError("fixture authority manifest fields are invalid")
    if document.get("schema") != SCHEMA or document.get("fixture_root") != FIXTURE_ROOT:
        raise FixtureAuthorityError("fixture authority manifest schema or root is invalid")
    version = document.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise FixtureAuthorityError("fixture authority version is invalid")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise FixtureAuthorityError("fixture authority entries are invalid")
    records = tuple(_parse_entry(raw) for raw in raw_entries)
    paths = tuple(record.path for record in records)
    if len(set(paths)) != len(paths):
        raise FixtureAuthorityError("fixture authority contains duplicate paths")
    if paths != tuple(sorted(paths)):
        raise FixtureAuthorityError("fixture authority entries are not deterministically ordered")
    return FixtureAuthority(version=version, fixture_root=FIXTURE_ROOT, records=records)


def _candidate_paths(repo_root: Path) -> tuple[str, ...]:
    root = (repo_root / FIXTURE_ROOT).resolve()
    if not root.is_dir():
        raise FixtureAuthorityError("Python fixture root is missing")
    paths = []
    for path in root.rglob("*.py"):
        if not path.is_file() or path.is_symlink():
            continue
        paths.append(path.relative_to(repo_root.resolve()).as_posix())
    return tuple(sorted(paths))


def validate_fixture_manifest(
    repo_root: Path = REPO_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, object]:
    """Validate census membership, content bindings, and static role evidence."""
    root = repo_root.resolve()
    authority = load_manifest(manifest_path)
    expected = _candidate_paths(root)
    declared = tuple(record.path for record in authority.records)
    if declared != expected:
        missing = sorted(set(expected) - set(declared))
        extra = sorted(set(declared) - set(expected))
        detail = f"missing={missing[:3]} extra={extra[:3]}"
        raise FixtureAuthorityError(f"fixture authority does not cover the Python fixture census: {detail}")

    consumer_evidence: dict[str, list[dict[str, object]]] = {}
    digest_map: dict[str, str] = {}
    role_counts = {role: 0 for role in sorted(ROLES)}
    shape_counts = {shape: 0 for shape in sorted(SOURCE_SHAPES)}
    for record in authority.records:
        fixture_path = root / record.path
        source, _ = read_source(
            fixture_path,
            f"fixture {record.path}",
            # AST parsing below is the declaration authority.  Tokenization
            # may also fail for an intentionally malformed sample, but that
            # fact must still be checked against the explicit source_shape.
            allow_tokenization_error=True,
        )
        digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if digest != record.content_sha256:
            raise FixtureAuthorityError(f"fixture content digest mismatch: {record.path}")
        if record.provenance is not None:
            evidence_path = root / record.provenance["evidence_path"]
            if not evidence_path.is_file() or evidence_path.is_symlink():
                raise FixtureAuthorityError(f"fixture provenance evidence is missing: {record.path}")
            evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if evidence_digest != record.provenance["evidence_sha256"]:
                raise FixtureAuthorityError(f"fixture provenance evidence drift: {record.path}")
        tree = parse_source(source, shape=record.source_shape, label=record.path)
        if record.role == "inert_data" and tree is not None:
            unsafe = execution_calls(tree)
            if unsafe:
                calls = ", ".join(unsafe)
                raise FixtureAuthorityError(f"inert fixture contains executable construct ({calls}): {record.path}")
        role_counts[record.role] += 1
        shape_counts[record.source_shape] += 1
        evidence = []
        for consumer in record.consumer:
            consumer_path = root / consumer
            if not consumer_path.is_file() or consumer_path.is_symlink():
                raise FixtureAuthorityError(f"fixture consumer is missing or unsuitable: {consumer}")
            evidence.append(
                validate_consumer(consumer_path, root, record.path, record.family, record.role)
            )
        consumer_evidence[record.path] = evidence

        digest_map[record.path] = digest

    declared_consumers = {
        consumer for record in authority.records for consumer in record.consumer
    }
    unlisted_references = scan_unlisted_consumers(
        root,
        FIXTURE_ROOT,
        tuple(record.family for record in authority.records if record.role == "inert_data"),
        declared_consumers,
        ignored_paths=(
            "tools/ci/python_fixture_authority.py",
            "tools/ci/python_fixture_static.py",
        ),
    )

    try:
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as error:
        raise FixtureAuthorityError("fixture authority manifest cannot be hashed") from error
    return {
        "schema": RESULT_SCHEMA,
        "status": "passed",
        "authority_schema": SCHEMA,
        "authority_version": authority.version,
        "manifest_sha256": manifest_digest,
        "fixture_root": FIXTURE_ROOT,
        "entry_count": len(authority.records),
        "paths": list(declared),
        "content_sha256": digest_map,
        "role_counts": role_counts,
        "source_shape_counts": shape_counts,
        "consumer_evidence": consumer_evidence,
        "candidate_consumer_count": len(candidate_consumer_paths(root, FIXTURE_ROOT)),
        "unlisted_static_references": unlisted_references,
        "entries": [record.as_dict() for record in authority.records],
    }


def classify_fixture(path: str, authority: FixtureAuthority | None = None) -> FixtureRecord:
    """Return a declared role record for one fixture path."""
    selected = authority if authority is not None else load_manifest()
    record = selected.by_path.get(path)
    if record is None:
        raise FixtureAuthorityError(f"fixture path is not declared: {path}")
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--json", action="store_true", help="emit machine-readable evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_fixture_manifest(args.repo_root, args.manifest)
    except (FixtureAuthorityError, OSError) as error:
        result = {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "error": str(error),
        }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["status"] == "passed":
        print(f"python-fixture-authority: passed ({result['entry_count']} fixtures)")
    else:
        print(f"python-fixture-authority: failed: {result['error']}", file=sys.stderr)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
