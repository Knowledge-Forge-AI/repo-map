"""Typed records and validation for the retained-Python quality contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Mapping, Sequence, TypeAlias, TypedDict, TypeGuard


BASELINE_SCHEMA = "repomap-retained-python-ratchets-baseline-v1"


class RecordValidationError(ValueError):
    """A retained-Python record does not satisfy its closed schema."""


class OwnershipRecord(TypedDict):
    manifest_path: str
    sha256: str


class ToolRecord(TypedDict):
    mypy: str
    ruff: str
    ruff_rules: list[str]
    ruff_target_version: str


class SelectionModuleRecord(TypedDict):
    module: str
    path: str
    ownership_class: str
    tier: str


class SelectionRecord(TypedDict):
    ownership_classes: list[str]
    tiers: list[str]
    modules: list[SelectionModuleRecord]


class RuffFindingRecord(TypedDict):
    path: str
    code: str
    message: str
    fingerprint: str
    count: int


class MypyFindingRecord(TypedDict):
    module: str
    path: str
    error_code: str
    normalized_fingerprint: str
    count: int


class ImportEdgeRecord(TypedDict):
    source_module: str
    source_path: str
    target_module: str
    target_tier: str


class FileLengthRecord(TypedDict):
    path: str
    line_count: int


class RuffSection(TypedDict):
    findings: list[RuffFindingRecord]


class MypySection(TypedDict):
    findings: list[MypyFindingRecord]


class ImportSection(TypedDict):
    edges: list[ImportEdgeRecord]


class BaselineFileLengthSection(TypedDict):
    warning_limit: int
    failure_limit: int
    ceilings: list[FileLengthRecord]


class SnapshotFileLengthSection(TypedDict):
    warning_limit: int
    failure_limit: int
    ceilings: list[FileLengthRecord]
    hard_failures: list[FileLengthRecord]


class BaselineDocument(TypedDict):
    schema: str
    ownership: OwnershipRecord
    tools: ToolRecord
    selection: SelectionRecord
    ruff: RuffSection
    mypy: MypySection
    migration_direction_imports: ImportSection
    file_length: BaselineFileLengthSection


class SnapshotDocument(TypedDict):
    ownership: OwnershipRecord
    tools: ToolRecord
    selection: SelectionRecord
    ruff: RuffSection
    mypy: MypySection
    migration_direction_imports: ImportSection
    file_length: SnapshotFileLengthSection


class TypeCheckInventoryRecord(TypedDict):
    module: str
    path: str
    ownership_class: str
    architecture_box: str
    error_code: str
    normalized_fingerprint: str
    count: int


class EnvironmentAttestation(TypedDict):
    versions: dict[str, str]
    owners_attested: list[str]
    source_authority: str


ScopeSelection: TypeAlias = SelectionModuleRecord


class ScopeChange(TypedDict):
    old: ScopeSelection | None
    new: ScopeSelection | None


class ScopeTransitionRecord(TypedDict, total=False):
    old_ownership_manifest_sha256: str
    new_ownership_manifest_sha256: str
    old_selected_set_sha256: str
    new_selected_set_sha256: str
    changes: list[ScopeChange]
    phase: str
    status_path: str
    reason: str
    source_commit: str
    source_manifest_sha256: str


class ScopeRegistry(TypedDict):
    schema: str
    records: list[ScopeTransitionRecord]


SCOPE_TRANSITIONS_SCHEMA_V1 = "repomap-retained-python-scope-transitions-v1"
SCOPE_TRANSITIONS_SCHEMA_V2 = "repomap-retained-python-scope-transitions-v2"
ACCEPTED_SCOPE_TRANSITIONS_SCHEMAS = frozenset({SCOPE_TRANSITIONS_SCHEMA_V1, SCOPE_TRANSITIONS_SCHEMA_V2})

_BASELINE_FIELDS = {"schema", "ownership", "tools", "selection", "ruff", "mypy", "migration_direction_imports", "file_length"}
_SCOPE_FIELDS_V1 = {"old_ownership_manifest_sha256", "new_ownership_manifest_sha256", "old_selected_set_sha256", "new_selected_set_sha256", "changes", "phase", "status_path", "reason"}
_SCOPE_FIELDS_V2 = _SCOPE_FIELDS_V1 | {"source_commit", "source_manifest_sha256"}
_SCOPE_FIELDS = _SCOPE_FIELDS_V1
_SELECTION_FIELDS = {"module", "path", "ownership_class", "tier"}


def _closed_dict(value: object, fields: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == fields


def is_baseline_document(value: object) -> TypeGuard[BaselineDocument]:
    """Narrow a JSON value after confirming the baseline top-level shape."""
    return _closed_dict(value, _BASELINE_FIELDS)


def is_scope_registry(value: object) -> TypeGuard[ScopeRegistry]:
    """Narrow a JSON value after confirming the scope registry top-level shape."""
    return _closed_dict(value, {"schema", "records"})


def _safe_path(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise RecordValidationError(f"{label} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RecordValidationError(f"{label} is invalid")
    return value


def is_repository_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    path = PurePosixPath(value)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _scope_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RecordValidationError(f"scope transition {field} is invalid")
    return value


def _records(
    records: object,
    section: str,
    fields: set[str],
    order: tuple[str, ...],
) -> None:
    if not isinstance(records, list) or any(
        not isinstance(item, dict) or set(item) != fields for item in records
    ):
        raise RecordValidationError(f"{section} baseline records are invalid")
    identities = [tuple(item[field] for field in order) for item in records]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise RecordValidationError(f"{section} baseline has duplicate or unsorted records")
    for item in records:
        for field in {"path", "source_path"} & fields:
            _safe_path(item[field], label="baseline path")


def validate_baseline_records(
    document: object,
    *,
    schema: str,
    expected_tools: Mapping[str, object],
    retained_classes: Sequence[str],
    retained_tiers: Sequence[str],
    warning_limit: int,
    failure_limit: int,
) -> TypeGuard[BaselineDocument]:
    """Validate a baseline and narrow it to its typed record shape."""
    if not is_baseline_document(document) or document.get("schema") != schema:
        raise RecordValidationError("baseline schema is invalid")
    if not isinstance(document["ownership"], dict) or set(document["ownership"]) != {"manifest_path", "sha256"}:
        raise RecordValidationError("baseline ownership is invalid")
    _safe_path(document["ownership"]["manifest_path"], label="baseline path")
    digest = document["ownership"]["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RecordValidationError("baseline ownership digest is invalid")
    if not isinstance(document["tools"], dict) or set(document["tools"]) != set(expected_tools):
        raise RecordValidationError("baseline tools are invalid")
    if document["tools"] != expected_tools:
        raise RecordValidationError("baseline tool versions are invalid")
    selection = document["selection"]
    if not isinstance(selection, dict) or set(selection) != {"ownership_classes", "tiers", "modules"}:
        raise RecordValidationError("baseline selection fields are invalid")
    if selection.get("ownership_classes") != list(retained_classes) or selection.get("tiers") != list(retained_tiers):
        raise RecordValidationError("baseline selection policy is invalid")
    modules = selection.get("modules")
    _records(modules, "selection", _SELECTION_FIELDS, ("module",))
    if not isinstance(modules, list) or len({item["path"] for item in modules}) != len(modules):
        raise RecordValidationError("selection baseline has duplicate paths")
    if any(
        item["ownership_class"] not in retained_classes or item["tier"] not in retained_tiers
        for item in modules
    ):
        raise RecordValidationError("selection baseline classification is invalid")
    if not isinstance(document["ruff"], dict) or set(document["ruff"]) != {"findings"}:
        raise RecordValidationError("finding baseline fields are invalid")
    if not isinstance(document["mypy"], dict) or set(document["mypy"]) != {"findings"}:
        raise RecordValidationError("finding baseline fields are invalid")
    ruff = document["ruff"].get("findings")
    mypy = document["mypy"].get("findings")
    _records(ruff, "ruff", {"path", "code", "message", "fingerprint", "count"}, ("path", "code", "message", "fingerprint"))
    _records(mypy, "mypy", {"module", "path", "error_code", "normalized_fingerprint", "count"}, ("module", "path", "error_code", "normalized_fingerprint"))
    if not isinstance(ruff, list) or len({item["fingerprint"] for item in ruff}) != len(ruff):
        raise RecordValidationError("Ruff baseline has duplicate fingerprints")
    if not isinstance(ruff, list) or not isinstance(mypy, list) or any(
        not isinstance(item["count"], int) or isinstance(item["count"], bool) or item["count"] < 1
        for item in (*ruff, *mypy)
    ):
        raise RecordValidationError("baseline finding multiplicity is invalid")
    imports = document["migration_direction_imports"]
    if not isinstance(imports, dict) or set(imports) != {"edges"}:
        raise RecordValidationError("migration baseline fields are invalid")
    _records(
        imports.get("edges"),
        "migration_direction_imports",
        {"source_module", "source_path", "target_module", "target_tier"},
        ("source_module", "source_path", "target_module", "target_tier"),
    )
    file_length = document["file_length"]
    if not isinstance(file_length, dict) or set(file_length) != {"warning_limit", "failure_limit", "ceilings"} or file_length.get("warning_limit") != warning_limit or file_length.get("failure_limit") != failure_limit:
        raise RecordValidationError("baseline file-length policy is invalid")
    ceilings = file_length.get("ceilings")
    _records(ceilings, "file_length", {"path", "line_count"}, ("path",))
    if not isinstance(ceilings, list) or any(not warning_limit < item["line_count"] <= failure_limit for item in ceilings):
        raise RecordValidationError("baseline file-length ceiling is invalid")
    return True


def validate_scope_registry_records(
    document: object, *, schema: str | None = None
) -> tuple[ScopeTransitionRecord, ...]:
    """Validate scope-transition records without depending on lineage policy types."""
    if not is_scope_registry(document):
        raise RecordValidationError("scope transition registry is invalid")
    doc_schema = document.get("schema")
    if (schema is not None and doc_schema != schema) or doc_schema not in ACCEPTED_SCOPE_TRANSITIONS_SCHEMAS:
        raise RecordValidationError("scope transition registry is invalid")
    records = document["records"]
    if not isinstance(records, list):
        raise RecordValidationError("scope transition registry is invalid")
    for raw in records:
        if not isinstance(raw, dict):
            raise RecordValidationError("scope transition record is invalid")
        if doc_schema == SCOPE_TRANSITIONS_SCHEMA_V2:
            if set(raw) != _SCOPE_FIELDS_V2:
                raise RecordValidationError("scope transition record is invalid")
            commit = raw.get("source_commit")
            if not isinstance(commit, str) or len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
                raise RecordValidationError("scope transition source_commit is invalid")
            _scope_digest(raw["source_manifest_sha256"], "source_manifest_sha256")
        elif set(raw) != _SCOPE_FIELDS_V1:
            raise RecordValidationError("scope transition record is invalid")
        _scope_digest(raw["old_ownership_manifest_sha256"], "old_ownership_manifest_sha256")
        _scope_digest(raw["new_ownership_manifest_sha256"], "new_ownership_manifest_sha256")
        _scope_digest(raw["old_selected_set_sha256"], "old_selected_set_sha256")
        _scope_digest(raw["new_selected_set_sha256"], "new_selected_set_sha256")
        for field in ("phase", "reason"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise RecordValidationError(f"scope transition {field} is invalid")
        status_path = raw["status_path"]
        valid_status = (
            (status_path.startswith("docs/status/") and status_path.endswith("-exit.md"))
            or status_path.startswith(("tools/ci/", "docs/releases/"))
            or status_path == "CHANGELOG.md"
        )
        if not isinstance(status_path, str) or not is_repository_path(status_path) or not valid_status:
            raise RecordValidationError("scope transition status authority is invalid")
        changes = raw["changes"]
        if not isinstance(changes, list):
            raise RecordValidationError("scope transition changes are invalid")
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"old", "new"}:
                raise RecordValidationError("scope transition change is invalid")
            for selection in (change["old"], change["new"]):
                if selection is None:
                    continue
                if not isinstance(selection, dict) or set(selection) != _SELECTION_FIELDS:
                    raise RecordValidationError("scope transition selection is invalid")
                if any(not isinstance(v, str) or not v for v in (selection["module"], selection["path"], selection["ownership_class"], selection["tier"])):
                    raise RecordValidationError("scope transition selection is invalid")
                if not is_repository_path(selection["path"]):
                    raise RecordValidationError("scope transition selection is invalid")
            if change["old"] is None and change["new"] is None:
                raise RecordValidationError("scope transition change is empty")
    keys = [scope_record_key(record) for record in records]
    if len(keys) != len(set(keys)):
        raise RecordValidationError("scope transition records are duplicate")
    return tuple(records)


def scope_record_key(record: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(record["old_ownership_manifest_sha256"]),
        str(record["new_ownership_manifest_sha256"]),
        str(record["old_selected_set_sha256"]),
        str(record["new_selected_set_sha256"]),
    )


def baseline_document(snapshot: SnapshotDocument) -> BaselineDocument:
    document = json.loads(json.dumps(snapshot))
    document["schema"] = BASELINE_SCHEMA
    document["file_length"].pop("hard_failures", None)
    return document


def render_document(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_baseline_atomic(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = render_document(document).encode()
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as target:
        temporary = Path(target.name)
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
