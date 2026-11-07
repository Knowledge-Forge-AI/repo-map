"""Closed ADR0123 namespace projection for retained-Python ownership and baselines.

The only root mapping is ``repomap_kg`` to ``common_lore_index`` and the matching
``src/main/python/`` product prefix. Every projection here is pure: it reads no
files, runs no tools and never regenerates analyzer output. Debt is carried by
exact identifier mapping; a changed mypy fingerprint needs an explicit preimage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Mapping, Sequence, TypeVar

from ci.python_type_ownership import (
    CLASS_TIERS,
    RESOLUTION,
    SCHEMA as OWNERSHIP_SCHEMA,
    OwnershipRule,
)
from ci.retained_python_contract import (
    LineagePolicyError,
    RatchetContractError,
    validate_baseline,
)
from ci.retained_python_records import (
    BaselineDocument,
    FileLengthRecord,
    ImportEdgeRecord,
    MypyFindingRecord,
    RuffFindingRecord,
    SelectionModuleRecord,
    is_baseline_document,
)


OLD_ROOT = "repomap_kg"
NEW_ROOT = "common_lore_index"
SOURCE_PREFIX = "src/main/python/"
OLD_PREFIX = f"{SOURCE_PREFIX}{OLD_ROOT}/"
NEW_PREFIX = f"{SOURCE_PREFIX}{NEW_ROOT}/"
TRANSLATION_FIELDS = frozenset(
    {"error_code", "before_fingerprint", "after_fingerprint", "before_message", "after_message"}
)

_COMPONENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PATH_PART = re.compile(r"[^/\\\x00-\x1f\x7f]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TEXT_ROOT = re.compile(
    rf"(?:(?<={re.escape(SOURCE_PREFIX)})|(?<![\w./\\-])){re.escape(OLD_ROOT)}(?![\w-])"
)
_PREFIX_FIELD = re.compile(
    rf'("module_prefix"[ \t\r\n]*:[ \t\r\n]*")({re.escape(OLD_ROOT)}(?:\.[A-Za-z_][A-Za-z0-9_]*)*)(")'
)
_OWNERSHIP_FIELDS = frozenset(OwnershipRule.__dataclass_fields__)
_Record = TypeVar("_Record", bound=Mapping[str, object])


class NamespaceProjectionError(LineagePolicyError):
    """A namespace projection input or result left the closed ADR0123 mapping."""


def _module_under(value: object, root: str) -> str:
    if not isinstance(value, str):
        raise NamespaceProjectionError("namespace module is not a string")
    parts = value.split(".")
    if parts[0] != root or any(_COMPONENT.fullmatch(part) is None for part in parts):
        raise NamespaceProjectionError("namespace module is outside the exact namespace root")
    return value


def rewrite_module(value: str) -> str:
    """Map an exact predecessor module identifier to its successor root."""
    return NEW_ROOT + _module_under(value, OLD_ROOT)[len(OLD_ROOT):]


def rewrite_product_path(value: str) -> str:
    """Map an exact predecessor product file path to its successor prefix."""
    if not isinstance(value, str) or not value.startswith(OLD_PREFIX):
        raise NamespaceProjectionError("product path is outside the exact predecessor prefix")
    suffix = value[len(OLD_PREFIX):]
    if any(part in {".", ".."} or _PATH_PART.fullmatch(part) is None for part in suffix.split("/")):
        raise NamespaceProjectionError("product path is malformed")
    return NEW_PREFIX + suffix


def rewrite_namespace_text(value: str) -> str:
    """Rewrite exact root spellings in free text; look-alikes are left untouched."""
    if not isinstance(value, str):
        raise NamespaceProjectionError("namespace text is not a string")
    if NEW_ROOT in value:
        raise NamespaceProjectionError("namespace text already contains the successor root")
    return _TEXT_ROOT.sub(NEW_ROOT, value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document = dict(pairs)
    if len(document) != len(pairs):
        raise NamespaceProjectionError("ownership manifest has duplicate JSON keys")
    return document


def _ownership_entries(raw: object, root: str) -> tuple[dict[str, object], list[dict[str, str]]]:
    if not isinstance(raw, bytes):
        raise NamespaceProjectionError("ownership manifest is not bytes")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NamespaceProjectionError("ownership manifest is unreadable") from error
    if not isinstance(document, dict) or set(document) != {"schema", "resolution", "entries"}:
        raise NamespaceProjectionError("ownership manifest fields are invalid")
    if document["schema"] != OWNERSHIP_SCHEMA or document["resolution"] != RESOLUTION:
        raise NamespaceProjectionError("ownership manifest schema is invalid")
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise NamespaceProjectionError("ownership manifest entries are invalid")
    entries: list[dict[str, str]] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != _OWNERSHIP_FIELDS:
            raise NamespaceProjectionError("ownership entry fields are invalid")
        entry = {key: value for key, value in raw_entry.items() if isinstance(value, str) and value}
        if set(entry) != _OWNERSHIP_FIELDS:
            raise NamespaceProjectionError("ownership entry values are invalid")
        ownership_class = entry["ownership_class"]
        if ownership_class not in CLASS_TIERS or entry["enforcement_tier"] not in CLASS_TIERS[ownership_class]:
            raise NamespaceProjectionError("ownership class and tier are invalid")
        if entry["match"] not in {"exact", "subtree"}:
            raise NamespaceProjectionError("ownership match is invalid")
        _module_under(entry["module_prefix"], root)
        entries.append(entry)
    prefixes = [entry["module_prefix"] for entry in entries]
    if len(prefixes) != len(set(prefixes)):
        raise NamespaceProjectionError("ownership manifest has duplicate module prefixes")
    if prefixes != sorted(prefixes):
        raise NamespaceProjectionError("ownership entries are not deterministically ordered")
    return document, entries


def project_ownership_manifest(raw: bytes) -> bytes:
    """Rewrite only module_prefix JSON values, preserving every other byte."""
    document, entries = _ownership_entries(raw, OLD_ROOT)
    text = raw.decode("utf-8")
    spelled = [match.group(2) for match in _PREFIX_FIELD.finditer(text)]
    if spelled != [entry["module_prefix"] for entry in entries]:
        raise NamespaceProjectionError("ownership module_prefix spellings are not exact JSON fields")
    projected = _PREFIX_FIELD.sub(
        lambda match: match.group(1) + rewrite_module(match.group(2)) + match.group(3), text
    ).encode("utf-8")
    expected = dict(document, entries=[
        dict(entry, module_prefix=rewrite_module(entry["module_prefix"])) for entry in entries
    ])
    successor, _ = _ownership_entries(projected, NEW_ROOT)
    if successor != expected:
        raise NamespaceProjectionError("ownership projection changed more than module prefixes")
    return projected


def _valid(document: object, label: str) -> BaselineDocument:
    try:
        validate_baseline(document)
    except (RatchetContractError, TypeError) as error:
        detail = str(error) if isinstance(error, RatchetContractError) else "record types are invalid"
        raise NamespaceProjectionError(f"{label} baseline is invalid: {detail}") from error
    if not is_baseline_document(document):
        raise NamespaceProjectionError(f"{label} baseline is invalid")
    return document


def _text(record: Mapping[str, object], field: str) -> str:
    value = record[field]
    if not isinstance(value, str):
        raise NamespaceProjectionError("baseline record field is not a string")
    return value


def _ruff_fingerprint(path: str, code: str, message: str) -> str:
    return hashlib.sha256(f"{path}\0{code}\0{message}".encode()).hexdigest()


def _mypy_fingerprint(code: str, message: str) -> str:
    return hashlib.sha256(f"{code}\0{message}".encode()).hexdigest()


def _mypy_normalized(message: str) -> str:
    return " ".join(re.sub(r"\b\d+\b", "<n>", message).split())


def _translations(raw: object) -> dict[tuple[str, str], str]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise NamespaceProjectionError("mypy translations are not a row sequence")
    table: dict[tuple[str, str], str] = {}
    for row in raw:
        if not isinstance(row, dict) or set(row) != TRANSLATION_FIELDS:
            raise NamespaceProjectionError("mypy translation row fields are invalid")
        if any(not isinstance(row[field], str) or not row[field] for field in TRANSLATION_FIELDS):
            raise NamespaceProjectionError("mypy translation row values are invalid")
        code, before, after = row["error_code"], row["before_message"], row["after_message"]
        if _mypy_normalized(before) != before or _mypy_normalized(after) != after:
            raise NamespaceProjectionError("mypy translation message is not normalized")
        if (
            _mypy_fingerprint(code, before) != row["before_fingerprint"]
            or _mypy_fingerprint(code, after) != row["after_fingerprint"]
        ):
            raise NamespaceProjectionError("mypy translation hash proof is forged")
        if rewrite_namespace_text(before) != after:
            raise NamespaceProjectionError("mypy translation is not an exact namespace rewrite")
        if before == after or row["before_fingerprint"] == row["after_fingerprint"]:
            raise NamespaceProjectionError("mypy translation is an identity row")
        key = (code, row["before_fingerprint"])
        if key in table:
            raise NamespaceProjectionError("mypy translation rows are duplicate")
        table[key] = row["after_fingerprint"]
    return table


def _ordered(records: Sequence[_Record], fields: tuple[str, ...], label: str) -> list[_Record]:
    keyed = {tuple(_text(item, field) for field in fields): item for item in records}
    if len(keyed) != len(records):
        raise NamespaceProjectionError(f"namespace projection collides {label} records")
    return [keyed[key] for key in sorted(keyed)]


def _ruff(record: RuffFindingRecord) -> RuffFindingRecord:
    path, code, message = _text(record, "path"), _text(record, "code"), _text(record, "message")
    if " ".join(message.split()) != message or _ruff_fingerprint(path, code, message) != record["fingerprint"]:
        raise NamespaceProjectionError("Ruff predecessor fingerprint does not match its stored message")
    new_path, new_message = rewrite_product_path(path), rewrite_namespace_text(message)
    return {
        "path": new_path,
        "code": code,
        "message": new_message,
        "fingerprint": _ruff_fingerprint(new_path, code, new_message),
        "count": record["count"],
    }


def project_baseline(
    before: object,
    *,
    ownership_sha256: str,
    mypy_translations: object = (),
) -> BaselineDocument:
    """Return the exact successor baseline implied by the predecessor and namespace map."""
    document = _valid(before, "predecessor")
    if not isinstance(ownership_sha256, str) or _DIGEST.fullmatch(ownership_sha256) is None:
        raise NamespaceProjectionError("successor ownership digest is invalid")
    table = _translations(mypy_translations)
    projected = copy.deepcopy(document)
    projected["ownership"]["sha256"] = ownership_sha256
    modules: list[SelectionModuleRecord] = [
        {
            "module": rewrite_module(item["module"]),
            "path": rewrite_product_path(item["path"]),
            "ownership_class": item["ownership_class"],
            "tier": item["tier"],
        }
        for item in document["selection"]["modules"]
    ]
    projected["selection"]["modules"] = _ordered(modules, ("module",), "selection")
    ruff = [_ruff(item) for item in document["ruff"]["findings"]]
    projected["ruff"]["findings"] = _ordered(ruff, ("path", "code", "message", "fingerprint"), "Ruff")
    used: set[tuple[str, str]] = set()
    mypy: list[MypyFindingRecord] = []
    for item in document["mypy"]["findings"]:
        key = (_text(item, "error_code"), _text(item, "normalized_fingerprint"))
        if key in table:
            used.add(key)
        mypy.append({
            "module": rewrite_module(item["module"]),
            "path": rewrite_product_path(item["path"]),
            "error_code": key[0],
            "normalized_fingerprint": table.get(key, key[1]),
            "count": item["count"],
        })
    if used != set(table):
        raise NamespaceProjectionError("mypy translation rows are unused")
    projected["mypy"]["findings"] = _ordered(
        mypy, ("module", "path", "error_code", "normalized_fingerprint"), "mypy"
    )
    edges: list[ImportEdgeRecord] = [
        {
            "source_module": rewrite_module(item["source_module"]),
            "source_path": rewrite_product_path(item["source_path"]),
            "target_module": rewrite_module(item["target_module"]),
            "target_tier": item["target_tier"],
        }
        for item in document["migration_direction_imports"]["edges"]
    ]
    projected["migration_direction_imports"]["edges"] = _ordered(
        edges, ("source_module", "source_path", "target_module", "target_tier"), "import-edge"
    )
    ceilings: list[FileLengthRecord] = [
        {"path": rewrite_product_path(item["path"]), "line_count": item["line_count"]}
        for item in document["file_length"]["ceilings"]
    ]
    projected["file_length"]["ceilings"] = _ordered(ceilings, ("path",), "file-length")
    return _valid(projected, "projected")


def _total(records: Sequence[Mapping[str, object]], field: str) -> int:
    total = 0
    for item in records:
        value = item.get(field, 1)
        total += value if isinstance(value, int) else 0
    return total


def _verdict(expected: Sequence[Mapping[str, object]], actual: Sequence[Mapping[str, object]], field: str) -> str:
    if _total(actual, field) < _total(expected, field) or len(actual) < len(expected):
        return "erases"
    if _total(actual, field) > _total(expected, field) or len(actual) > len(expected):
        return "adds"
    return "changes"


def _compare(expected: BaselineDocument, actual: BaselineDocument) -> None:
    if actual["schema"] != expected["schema"] or actual["tools"] != expected["tools"]:
        raise NamespaceProjectionError("successor schema or tool record differs from the exact projection")
    if actual["ownership"] != expected["ownership"]:
        raise NamespaceProjectionError("successor ownership record differs from the exact projection")
    if (
        actual["selection"]["ownership_classes"] != expected["selection"]["ownership_classes"]
        or actual["selection"]["tiers"] != expected["selection"]["tiers"]
    ):
        raise NamespaceProjectionError("successor selection policy differs from the exact projection")
    if actual["selection"]["modules"] != expected["selection"]["modules"]:
        verdict = _verdict(expected["selection"]["modules"], actual["selection"]["modules"], "count")
        raise NamespaceProjectionError(f"successor {verdict} selected modules against the exact projection")
    counted: tuple[tuple[str, Sequence[Mapping[str, object]], Sequence[Mapping[str, object]], str], ...] = (
        ("Ruff", expected["ruff"]["findings"], actual["ruff"]["findings"], "count"),
        ("mypy", expected["mypy"]["findings"], actual["mypy"]["findings"], "count"),
        ("import-edge", expected["migration_direction_imports"]["edges"],
         actual["migration_direction_imports"]["edges"], "count"),
        ("file-length", expected["file_length"]["ceilings"], actual["file_length"]["ceilings"], "line_count"),
    )
    for label, wanted, found, field in counted:
        if found != wanted:
            verdict = _verdict(wanted, found, field)
            raise NamespaceProjectionError(f"successor {verdict} {label} debt against the exact projection")
    if actual != expected:
        raise NamespaceProjectionError("successor baseline differs from the exact projection")


def audit_namespace_documents(
    before: object,
    after: object,
    *,
    ownership_before: bytes,
    ownership_after: bytes,
    mypy_translations: object = (),
) -> None:
    """Accept only the exact namespace projection of a predecessor baseline and manifest."""
    prior, current = _valid(before, "predecessor"), _valid(after, "successor")
    if not isinstance(ownership_before, bytes) or not isinstance(ownership_after, bytes):
        raise NamespaceProjectionError("ownership manifests are not bytes")
    if prior["ownership"]["sha256"] != hashlib.sha256(ownership_before).hexdigest():
        raise NamespaceProjectionError("predecessor ownership digest does not bind its manifest")
    if current["ownership"]["sha256"] != hashlib.sha256(ownership_after).hexdigest():
        raise NamespaceProjectionError("successor ownership digest does not bind its manifest")
    if project_ownership_manifest(ownership_before) != ownership_after:
        raise NamespaceProjectionError("successor ownership manifest is not the exact projection")
    expected = project_baseline(
        prior,
        ownership_sha256=current["ownership"]["sha256"],
        mypy_translations=mypy_translations,
    )
    _compare(expected, current)


__all__ = [
    "NEW_PREFIX",
    "NEW_ROOT",
    "NamespaceProjectionError",
    "OLD_PREFIX",
    "OLD_ROOT",
    "SOURCE_PREFIX",
    "TRANSLATION_FIELDS",
    "audit_namespace_documents",
    "project_baseline",
    "project_ownership_manifest",
    "rewrite_module",
    "rewrite_namespace_text",
    "rewrite_product_path",
]
