"""Parent-derived names, lines, pointers and Rust raw observations (spec 6.5, 9, 11.2).

Every name, line, pointer, attribute class and text value is computed here
from the parent's own retained input bytes and decoded integer frames. The
helper never supplies text. Nothing is resolved, evaluated or expanded: cfg
alternatives stay separate, macros stay opaque and ``mod x;`` stays external.
"""

from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from common_lore_index import __version__
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.component_lock import DIALECT, LOCK_ID, SELECTION_RULE
from common_lore_index.extractors.rust_pilot.helper_protocol import (
    FLAG_HAS_ERROR,
    FLAG_NO_BODY,
    FLAG_SIGNATURE,
    ITEM_KINDS,
    UNSUPPORTED_CONSTRUCTS,
    MAX_SCOPE_DEPTH,
    DecodedParse,
    ItemFrame,
    Span,
)
from common_lore_index.observations.raw import RawObservation

EXTRACTOR = "rust-pilot-tree-sitter"
MAX_NAME_BYTES = 256
MAX_VISIBILITY_BYTES = 32
MAX_TYPE_TEXT_BYTES = 256
MAX_POINTER_BYTES = 4096
MAX_SEMANTIC_BYTES = 16 * 1_048_576
ROOT_POINTER = "/"
NAMESPACES = {"mod": "rust.module", "fn": "rust.function", "struct": "rust.type", "enum": "rust.type",
              "union": "rust.type", "type": "rust.type", "trait": "rust.trait", "impl": "rust.impl",
              "macro": "rust.macro"}
_ATTRIBUTE_PATH = re.compile(rb"#\[\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*::\s*[A-Za-z_][A-Za-z0-9_]*)*)")


class ObservationBound(ContractError):
    """The retained semantic expansion exceeded a fixed parent-side output cap."""


@dataclass(frozen=True)
class FileObservations:
    """Parent-derived parse result for one attempted file."""

    outcome: str
    completeness: str
    achieved: tuple[str, ...]
    item_list: str
    usable_items: int
    observations: tuple[RawObservation, ...]


class LineIndex:
    """LF offsets built once; CRLF counts as one line break."""

    def __init__(self, data: bytes) -> None:
        self.breaks = [index for index, byte in enumerate(data) if byte == 0x0A]
        self.count = len(self.breaks) + (1 if data and not data.endswith(b"\n") else 0)

    def line(self, offset: int) -> int:
        return 1 + bisect.bisect_left(self.breaks, offset)

    def lines(self, start: int, end: int) -> tuple[int, int]:
        return self.line(start), self.line(max(start, end - 1))


def decode_name(data: bytes, span: Span | None) -> tuple[str, bool] | None:
    """Return (name, raw_identifier) or None when the name must be rejected."""

    if span is None or span[1] - span[0] > MAX_NAME_BYTES or span[1] == span[0]:
        return None
    try:
        name = data[span[0]:span[1]].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if name.isidentifier():
        return name, False
    if name.startswith("r#") and name[2:].isidentifier():
        return name, True
    return None


def bounded_text(data: bytes, span: Span | None, limit: int) -> str | None:
    if span is None or span[1] - span[0] > limit:
        return None
    try:
        return " ".join(data[span[0]:span[1]].decode("utf-8").split())
    except UnicodeDecodeError:
        return None


def attribute_class(data: bytes, span: Span) -> str:
    match = _ATTRIBUTE_PATH.match(data[span[0]:min(span[1], span[0] + 160)])
    if match is None:
        return "other"
    path = re.sub(rb"\s+", b"", match.group(1)).decode("ascii")
    return path if path in ("cfg", "cfg_attr", "derive") else "other"


def common_metadata() -> dict[str, Any]:
    return {"language": "rust", "dialect": DIALECT, "component_lock": LOCK_ID, "selection_rule": SELECTION_RULE}


def _observation(kind: str, path: str, lines: tuple[int, int], metadata: dict[str, Any],
                 name: str | None = None) -> RawObservation:
    return RawObservation(kind=kind, source_id=path, path=path, confidence="extracted", extractor=EXTRACTOR,
                          extractor_version=__version__, start_line=lines[0], end_line=lines[1], name=name,
                          metadata={**common_metadata(), **metadata})


def parse_observation(path: str, data: bytes, *, input_sha256: str, outcome: str, completeness: str,
                      item_list: str, build_script_name: bool, counts: dict[str, int]) -> RawObservation:
    index = LineIndex(data)
    return _observation("rust.parse", path, (1, max(1, index.count)), {
        "outcome": outcome, "completeness": completeness, "input_sha256": input_sha256,
        "input_bytes": len(data), "line_count": index.count, "errors": counts.get("errors", 0),
        "missing": counts.get("missing", 0), "items": counts.get("items", 0),
        "unsupported": counts.get("unsupported", 0), "item_list": item_list,
        "build_script_name": build_script_name,
    })


class _Tree:
    """Accepted items, rejection propagation, usability and pointers."""

    def __init__(self, data: bytes, decoded: DecodedParse) -> None:
        self.items = decoded.items
        self.names: dict[int, tuple[str, bool]] = {}
        self.rejected: dict[int, int] = {}
        for item in self.items:
            owner = item.parent
            if owner >= 0 and (owner in self.rejected):
                self.rejected[item.index] = self.rejected[owner]
                continue
            named = None if item.tag == 9 else decode_name(data, item.name)
            if item.tag != 9 and named is None:
                self.rejected[item.index] = owner
                continue
            if named is not None:
                self.names[item.index] = named
        self.usable: dict[int, bool] = {}
        self.depth: dict[int, int] = {}
        self.pointers: dict[int, str] = {}
        self.ambiguity: dict[int, int] = {}
        self.pointer_bytes = 0
        children: dict[int, list[ItemFrame]] = defaultdict(list)
        for item in self.items:
            if item.index in self.rejected:
                continue
            parent_ok = item.parent < 0 or self.usable[item.parent]
            self.usable[item.index] = parent_ok and not item.flags & FLAG_HAS_ERROR
            self.depth[item.index] = 1 if item.parent < 0 else self.depth[item.parent] + 1
            if self.depth[item.index] > MAX_SCOPE_DEPTH:
                raise ObservationBound("parent_output_bound")
            children[item.parent].append(item)
        for owner, members in children.items():
            self._assign(owner, members)

    def _assign(self, owner: int, members: list[ItemFrame]) -> None:
        base = ROOT_POINTER if owner < 0 else self.pointers[owner] + "/"
        keys = [(NAMESPACES[ITEM_KINDS[item.tag]], self.names[item.index][0]) for item in members
                if item.tag != 9]
        totals = Counter(keys)
        seen: Counter[tuple[str, str]] = Counter()
        impls = 0
        for item in members:
            kind = ITEM_KINDS[item.tag]
            if item.tag == 9:
                impls += 1
                step = f"impl:{impls}"
                self.ambiguity[item.index] = 0
            else:
                key = (NAMESPACES[kind], self.names[item.index][0])
                seen[key] += 1
                step = f"{kind}:{key[1]}"
                if totals[key] > 1:
                    step += f"@{seen[key]}"
                self.ambiguity[item.index] = totals[key] if totals[key] > 1 else 0
            size = len(base.encode("utf-8")) + len(step.encode("utf-8"))
            if size > MAX_POINTER_BYTES or self.pointer_bytes + size > MAX_SEMANTIC_BYTES:
                raise ObservationBound("parent_output_bound")
            self.pointer_bytes += size
            self.pointers[item.index] = base + step

    def scope_pointer(self, index: int) -> str:
        while index >= 0 and index in self.rejected:
            index = self.rejected[index]
        return ROOT_POINTER if index < 0 else self.pointers[index]


def _item_metadata(tree: _Tree, data: bytes, item: ItemFrame, macro_scopes: set[int],
                   truncated: bool) -> dict[str, Any]:
    kind = ITEM_KINDS[item.tag]
    classes = [attribute_class(data, span) for span in item.attributes]
    metadata: dict[str, Any] = {
        "item_kind": kind, "namespace": NAMESPACES[kind], "pointer": tree.pointers[item.index],
        "parent_pointer": tree.scope_pointer(item.parent), "start_byte": item.start, "end_byte": item.end,
        "usable_scope": tree.usable[item.index],
        "attributes": {"cfg": "cfg" in classes, "cfg_attr": "cfg_attr" in classes,
                       "derive": "derive" in classes, "other": classes.count("other")},
        "attribute_list": "truncated" if truncated else "complete",
        "conditional": True if "cfg" in classes or "cfg_attr" in classes else (None if truncated else False),
        "visibility": bounded_text(data, item.visibility, MAX_VISIBILITY_BYTES),
        "raw_identifier": tree.names.get(item.index, ("", False))[1],
        "name_ambiguity": tree.ambiguity[item.index],
    }
    if kind == "mod":
        metadata["body"] = "external_unresolved" if item.flags & FLAG_NO_BODY else "inline"
    if kind == "fn":
        metadata["has_body"] = not item.flags & FLAG_SIGNATURE
    if kind == "impl":
        metadata["self_type_text"] = bounded_text(data, item.self_type, MAX_TYPE_TEXT_BYTES)
        metadata["trait_text"] = bounded_text(data, item.trait_ref, MAX_TYPE_TEXT_BYTES)
    if item.tag in (1, 8, 9) and not item.flags & FLAG_NO_BODY:
        if item.flags & FLAG_HAS_ERROR:
            metadata["member_list"] = "error_incomplete"
        elif item.index in macro_scopes:
            metadata["member_list"] = "macro_incomplete"
        elif truncated or tree.depth[item.index] >= MAX_SCOPE_DEPTH:
            metadata["member_list"] = "truncated"
        else:
            metadata["member_list"] = "complete"
    return metadata


def classify(decoded: DecodedParse, usable_items: int, macro_scopes: set[int]) -> tuple[str, str, tuple[str, ...], str]:
    """Return (outcome, completeness, achieved, item_list) per spec 9."""

    result: tuple[str, str, tuple[str, ...]]
    if decoded.end.truncated:
        result = ("succeeded", "truncated", ("syntax.error_tolerant",))
    elif not decoded.end.root_error:
        result = ("succeeded", "complete", ("syntax.tree",))
    elif usable_items:
        result = ("succeeded", "partial", ("syntax.error_tolerant",))
    else:
        result = ("parse_rejected", "none", ())
    if -1 in macro_scopes:
        item_list = "macro_incomplete"
    else:
        item_list = "complete" if result[1] == "complete" else "partial"
    return (*result, item_list)


def build_file_observations(path: str, data: bytes, decoded: DecodedParse, *, input_sha256: str,
                            build_script_name: bool) -> FileObservations:
    """Build the file's ``rust.parse``, ``rust.item`` and ``rust.unsupported`` observations."""

    tree = _Tree(data, decoded)
    index = LineIndex(data)
    macro_scopes = {frame.scope for frame in decoded.unsupported if frame.tag == 1}
    accepted = [item for item in decoded.items if item.index not in tree.rejected]
    usable_items = sum(1 for item in accepted if tree.usable[item.index])
    outcome, completeness, achieved, item_list = classify(decoded, usable_items, macro_scopes)
    groups: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for frame in decoded.unsupported:
        groups[(tree.scope_pointer(frame.scope), UNSUPPORTED_CONSTRUCTS[frame.tag])].append((frame.start, frame.end))
    for item in decoded.items:
        if item.index in tree.rejected:
            groups[(tree.scope_pointer(item.parent), "name_rejected")].append((item.start, item.end))
    counts = {"errors": decoded.end.errors, "missing": decoded.end.missing, "items": len(accepted),
              "unsupported": sum(len(spans) for spans in groups.values())}
    result: list[RawObservation] = []
    emitted = _append_bounded(result, parse_observation(
        path, data, input_sha256=input_sha256, outcome=outcome, completeness=completeness,
        item_list=item_list, build_script_name=build_script_name, counts=counts), 0)
    for item in accepted:
        name = tree.names.get(item.index, (None, False))[0]
        emitted = _append_bounded(result, _observation(
            "rust.item", path, index.lines(item.start, item.end),
            _item_metadata(tree, data, item, macro_scopes, bool(decoded.end.truncated)), name=name), emitted)
    for (scope, construct), spans in sorted(groups.items()):
        first = min(spans)
        emitted = _append_bounded(result, _observation(
            "rust.unsupported", path, index.lines(*first),
            {"construct": construct, "count": len(spans), "scope_pointer": scope}), emitted)
    return FileObservations(outcome, completeness, achieved, item_list, usable_items, tuple(result))


def _append_bounded(result: list[RawObservation], observation: RawObservation, emitted: int) -> int:
    total = emitted + len(observation.to_json_line().encode("utf-8")) + 1
    if total > MAX_SEMANTIC_BYTES:
        raise ObservationBound("parent_output_bound")
    result.append(observation)
    return total
