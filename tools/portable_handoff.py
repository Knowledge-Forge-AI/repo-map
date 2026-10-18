"""Optional v1 selected-source records. See docs/ops/portable-handoff.md.

Export/load/render are pure. Only recheck reads explicitly selected local files.
No graph dependency, implicit root, action execution or assertion verification.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

VERSION = 1
MAX_PAYLOAD_BYTES = 65_536
MAX_ITEMS = 32
MAX_TEXT_CHARS = 4_096
MAX_SOURCE_BYTES = 65_536
MAX_SOURCE_LINES = 80
Record = dict[str, Any]


class HandoffError(ValueError):
    """Local format/budget error; caller may reduce the record or use prose."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HandoffError(message)


def _fields(value: Any, required: str, optional: str = "") -> None:
    _require(type(value) is dict, "expected an object")
    needed, allowed = set(required.split()), set((required + " " + optional).split())
    _require(needed <= value.keys() <= allowed, "missing or unknown fields")


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> None:
    _require(type(value) is str and 0 < len(value) <= limit, "invalid or over-limit text")
    _require(not any(ord(c) < 32 and c not in "\n\t" for c in value), "control character in text")


def _items(value: Any) -> None:
    _require(type(value) is list and len(value) <= MAX_ITEMS, "invalid or over-limit list")


def _range(value: Any) -> None:
    _require(value is None or (type(value) is list and len(value) == 2
             and all(type(n) is int for n in value) and 1 <= value[0] <= value[1]), "invalid range")


def _relative(value: Any) -> None:
    _text(value)
    _require(not value.startswith(("/", "~")) and ":" not in value and "\\" not in value
             and all(p not in {"", ".", ".."} for p in value.split("/"))
             and not any(ord(c) < 32 or ord(c) == 127 for c in value), "unsafe relative path")


def _reference(ref: Record) -> None:
    _fields(ref, "id repository_identity root source_relative_path range origin selection",
            "provenance recorded_content assertions")
    for name in ("id", "repository_identity"):
        _text(ref[name], 128)
    _fields(ref["root"], "key origin")
    _text(ref["root"]["key"], 128)
    _require(ref["root"]["origin"] in ("caller_mapping", "stored_binding"), "invalid root origin")
    _relative(ref["source_relative_path"])
    _range(ref["range"])
    _require(ref["origin"] in ("native", "locator", "historical", "unknown"), "invalid source origin")
    _require(ref["selection"] in ("direct", "ambiguous", "historical", "unknown"), "invalid selection")
    if "provenance" in ref:
        facts = ref["provenance"]
        _fields(facts, "", "canonical_key graph_id binding_id revision run_id publication_relation "
                "freshness ambiguity has_more evidence_role location_scope")
        for key, value in facts.items():
            if key == "has_more":
                _require(type(value) is bool, "has_more must be Boolean")
            elif key == "run_id" and type(value) is int:
                _require(value >= 0, "invalid run ID")
            elif value is not None:
                _text(value)
    _items(ref.get("assertions", []))
    for assertion in ref.get("assertions", []):
        _text(assertion)
    if "recorded_content" in ref:
        content = ref["recorded_content"]
        _fields(content, "domain range sha256 origin")
        _range(content["range"])
        _require(content["domain"] in ("file", "range") and
                 ((content["domain"] == "file") == (content["range"] is None)), "digest domain/range mismatch")
        _require(content["origin"] in ("local_read", "external"), "invalid digest origin")
        digest = content["sha256"]
        _require(type(digest) is str and len(digest) == 64
                 and all(c in "0123456789abcdef" for c in digest), "invalid SHA-256")


def _validate(record: Record) -> None:
    _require(type(record) is dict, "expected an object")
    _require(type(record.get("version")) is int and record["version"] == VERSION, "unsupported handoff version")
    _fields(record, "version task references findings questions next_checks negative_searches")
    _text(record["task"])
    for name in ("references", "findings", "questions", "next_checks", "negative_searches"):
        _items(record[name])
    ids: set[str] = set()
    for ref in record["references"]:
        _reference(ref)
        _require(ref["id"] not in ids, "duplicate evidence ID")
        ids.add(ref["id"])
    finding_ids: set[str] = set()
    for finding in record["findings"]:
        _fields(finding, "id kind text evidence_ids")
        _text(finding["id"], 128)
        _require(finding["id"] not in finding_ids, "duplicate finding ID")
        finding_ids.add(finding["id"])
        _require(finding["kind"] in ("finding", "inference"), "invalid finding kind")
        _text(finding["text"])
        _items(finding["evidence_ids"])
        for evidence_id in finding["evidence_ids"]:
            _text(evidence_id, 128)
            _require(evidence_id in ids, "dangling evidence ID")
    for name in ("questions", "next_checks"):
        for value in record[name]:
            _text(value)
    for search in record["negative_searches"]:
        _fields(search, "surface scope query outcome complete has_more")
        for name in ("surface", "scope", "query", "outcome"):
            _text(search[name])
        for name in ("complete", "has_more"):
            _require(type(search[name]) is bool, "invalid search completeness")


def export(record: Record) -> str:
    """Deterministic Unicode JSON; reject excess data rather than truncate it."""
    try:
        _validate(record)
        value = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        _require(len(value.encode("utf-8")) <= MAX_PAYLOAD_BYTES, "payload budget exceeded; reduce selected content")
        return value
    except (TypeError, RecursionError, UnicodeError) as error:
        raise HandoffError("malformed handoff data") from error


def _object(pairs: list[tuple[str, Any]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(payload: str | bytes) -> Record:
    """Parse only; never resolve roots, read source, call tools or execute text."""
    try:
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        _require(type(raw) is bytes and len(raw) <= MAX_PAYLOAD_BYTES, "payload budget exceeded; reduce selected content")
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        export(record)
        return record
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        if isinstance(error, HandoffError):
            raise
        raise HandoffError("malformed handoff JSON") from error


def _markdown(value: str) -> str:
    escaped = []
    for line in value.split("\n"):
        shown = "".join({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\t": "&#9;"}.get(c,
                        "\\" + c if c in "\\`*_[]()#!|~+-=" else c) for c in line)
        head, dot, tail = shown.partition(".")
        if head.strip().isdigit() and dot and tail.startswith(" "):
            shown = head + "\\." + tail
        escaped.append(shown)
    return "\n".join(escaped)


def _render_fields(item: Record, indent: int = 0) -> list[str]:
    rows = []
    for field, value in item.items():
        label = " " * indent + "- **" + field.replace("_", " ").title() + ":**"
        if isinstance(value, dict):
            rows.append(label)
            rows.extend(_render_fields(value, indent + 2))
        else:
            shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines = _markdown(shown).split("\n")
            rows.append(label + " " + lines[0])
            rows.extend(" " * (indent + 2) + line for line in lines[1:])
    return rows


def render(record: Record) -> str:
    """Readable Markdown of every field in original list order, with inert data."""
    normalized = load(export(record))
    rows = ["# Portable handoff v1", "", _markdown(normalized["task"]), ""]
    for name in ("references", "findings", "questions", "next_checks", "negative_searches"):
        rows.extend(["## " + name.replace("_", " ").title(), ""])
        for index, item in enumerate(normalized[name], 1):
            if isinstance(item, dict):
                rows.extend([f"### {index}", ""])
                rows.extend(_render_fields(item))
                rows.append("")
            else:
                rows.append("- " + _markdown(item).replace("\n", "\n  "))
        rows.append("")
    return "\n".join(rows)


def _content(data: bytes, lines: list[str], span: list[int] | None) -> Record:
    selected = data if span is None else "".join(lines[span[0] - 1:span[1]]).encode("utf-8")
    return {"domain": "file" if span is None else "range", "range": span,
            "sha256": hashlib.sha256(selected).hexdigest(), "origin": "local_read"}


def _eligible(ref: Record) -> bool:
    facts = ref.get("provenance", {})
    current = {"has_more": False, "publication_relation": "accepted_run", "location_scope": "accepted_run",
               "ambiguity": "single_stored_location", "evidence_role": "direct"}
    return (ref["selection"] == "direct" and ref["origin"] not in ("historical", "unknown")
            and (ref["origin"] != "locator" or current.keys() <= facts.keys())
            and all(facts.get(key, value) == value for key, value in current.items()))


def _read(ref: Record, root: Path) -> tuple[bytes, list[str]]:
    resolved_root = root.resolve(strict=True)
    target = (resolved_root / ref["source_relative_path"]).resolve(strict=True)
    if not resolved_root.is_dir() or not target.is_relative_to(resolved_root):
        raise ValueError("unsafe workspace mapping")
    if not target.is_file():
        raise ValueError("not a regular file")
    with target.open("rb") as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise OverflowError("file byte limit")
    return data, data.decode("utf-8").splitlines(keepends=True)


def _check_one(ref: Record, roots: Mapping[tuple[str, str, str], Path],
               source_check: Callable[[Record, str], bool] | None) -> Record:
    result: Record = {"id": ref["id"], "outcome": "not_checked", "next_action": "native_search_or_review"}
    if not _eligible(ref):
        return {**result, "reason": "uncertain_reference"}
    root = roots.get((ref["repository_identity"], ref["root"]["origin"], ref["root"]["key"]))
    if root is None:
        return {**result, "outcome": "unmapped"}
    if not isinstance(root, Path) or not root.is_absolute():
        return {**result, "reason": "invalid_mapping"}
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError:
        return {**result, "outcome": "unmapped", "reason": "missing_root"}
    except (OSError, ValueError):
        return {**result, "reason": "invalid_mapping"}
    span = ref["range"]
    recorded = ref.get("recorded_content")
    digest_span = recorded["range"] if recorded else span
    if any(s is not None and s[1] - s[0] >= MAX_SOURCE_LINES for s in (span, digest_span)):
        return {**result, "outcome": "out_of_bound", "reason": "line_limit"}
    try:
        data, lines = _read(ref, root)
    except FileNotFoundError:
        return {**result, "outcome": "missing"}
    except OverflowError:
        return {**result, "outcome": "out_of_bound", "reason": "file_byte_limit"}
    except (OSError, ValueError):
        return {**result, "reason": "unavailable_or_unsafe_source"}
    if recorded and digest_span is not None and digest_span[1] > len(lines):
        return {**result, "outcome": "changed", "reason": "recorded_range_missing"}
    if any(s is not None and s[1] > len(lines) for s in (span, digest_span)):
        return {**result, "outcome": "out_of_bound", "reason": "range_beyond_file"}
    inspected = span if span is not None else ([1, min(len(lines), MAX_SOURCE_LINES)] if lines else None)
    text = "".join(lines[inspected[0] - 1:inspected[1]]) if inspected else ""
    observed = _content(data, lines, digest_span)
    result.update(outcome=("matching" if observed["sha256"] == recorded["sha256"] else "changed")
                  if recorded else "observed", content=observed, inspected_range=inspected)
    if source_check is not None:
        try:
            passed = bool(source_check(ref, text))
            result["predicate"] = "passed" if passed else "failed"
            if passed:
                result["source_check"] = True
        except Exception:  # Caller callback boundary; preserve other independent results.
            result["predicate"] = "error"
    return result


def recheck(record: Record, selected_ids: Sequence[str], roots: Mapping[tuple[str, str, str], Path],
            source_check: Callable[[Record, str], bool] | None = None) -> list[Record]:
    """Read only selected current direct sources under caller-owned absolute roots.

    Results follow reference order; original records never change. Digest equality
    and predicate results are independent observations, never semantic proofs.
    """
    clean = load(export(record))
    _require(not isinstance(selected_ids, (str, bytes)) and len(selected_ids) <= MAX_ITEMS,
             "invalid selected IDs")
    _require(all(type(key) is str for key in selected_ids), "invalid selected ID")
    selected = set(selected_ids)
    _require(selected <= {ref["id"] for ref in clean["references"]}, "unknown selected ID")
    return [_check_one(ref, roots, source_check) for ref in clean["references"] if ref["id"] in selected]
