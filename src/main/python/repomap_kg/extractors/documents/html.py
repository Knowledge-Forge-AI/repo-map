"""Conservative static HTML raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-html"
PARSER_NAME = "stdlib-htmlparser"
PARSER_MODE = "static-recovering-no-render-no-js"
MAX_HTML_STRUCTURAL_BYTES = 4 * 1024 * 1024
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
ASSET_ATTRIBUTES = {
    "img": ("src",),
    "script": ("src",),
    "iframe": ("src",),
    "source": ("src",),
    "audio": ("src",),
    "video": ("src", "poster"),
    "link": ("href",),
}
SECRET_PRONE_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
)
STABLE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
DYNAMIC_MARKERS = ("${", "$(", "{{", "}}", "*", "?", "~")
FORM_FIELD_TAGS = frozenset({"input", "select", "textarea", "button"})


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    pointer: str
    start_line: int
    parent: _HtmlNode | None = None
    children: list[_HtmlNode] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    child_tag_counts: dict[str, int] = field(default_factory=dict)


class _StaticHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[_HtmlNode] = []
        self.stack: list[_HtmlNode] = []
        self.root_tag_counts: dict[str, int] = {}
        self.doctype: str | None = None
        self.warnings: list[dict[str, Any]] = []

    def handle_decl(self, decl: str) -> None:
        if decl.strip():
            self.doctype = decl.strip()[:80]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start_node(tag, attrs, push=tag.lower() not in VOID_TAGS)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start_node(tag, attrs, push=False)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == normalized:
                del self.stack[index:]
                return
        self.warnings.append(
            {
                "error_kind": "recoverable-unmatched-end-tag",
                "tag": normalized,
                "line": self.getpos()[0],
            }
        )

    def handle_data(self, data: str) -> None:
        if self.stack and data:
            self.stack[-1].text_parts.append(data)

    def close(self) -> None:
        super().close()
        unclosed = [node.tag for node in self.stack]
        if unclosed:
            self.warnings.append(
                {
                    "error_kind": "recoverable-unclosed-elements",
                    "tags": unclosed,
                    "line": self.stack[-1].start_line,
                }
            )
        self.stack.clear()

    def _start_node(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        push: bool,
    ) -> _HtmlNode:
        normalized = tag.lower()
        attr_map = {
            name.lower(): value
            for name, value in attrs
            if name is not None and value is not None
        }
        parent = self.stack[-1] if self.stack else None
        segment = self._segment_for(parent, normalized)
        pointer = f"{parent.pointer}/{segment}" if parent else f"/{segment}"
        node = _HtmlNode(
            tag=normalized,
            attrs=attr_map,
            pointer=pointer,
            start_line=self.getpos()[0],
            parent=parent,
        )
        if parent is not None:
            parent.children.append(node)
        self.nodes.append(node)
        if push:
            self.stack.append(node)
        return node

    def _segment_for(self, parent: _HtmlNode | None, tag: str) -> str:
        counts = self.root_tag_counts if parent is None else parent.child_tag_counts
        counts[tag] = counts.get(tag, 0) + 1
        count = counts[tag]
        if count == 1:
            return tag
        return f"{tag}[{count}]"


def extract_html_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    if _content_exceeds_structural_limit(content):
        return _size_limited_observations(relative_path)

    parser = _StaticHtmlParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as error:  # pragma: no cover - HTMLParser rarely raises.
        return (
            _parse_error_observation(
                relative_path,
                error_kind="malformed-html",
                message=str(error),
                line_number=None,
                recovered=False,
            ),
        )

    id_counts = _id_counts(parser.nodes)
    observations: list[RawObservation] = [
        _document_observation(relative_path, parser, id_counts)
    ]
    for node in parser.nodes:
        observations.append(_element_observation(relative_path, node, id_counts))
    for node in parser.nodes:
        if node.tag in HEADING_TAGS:
            observations.append(_heading_observation(relative_path, node, id_counts))
        if node.tag == "a" and node.attrs.get("href"):
            observations.append(
                _reference_observation(
                    "html.link",
                    relative_path,
                    node,
                    attribute="href",
                    value=node.attrs["href"],
                    id_counts=id_counts,
                )
            )
        if node.tag in ASSET_ATTRIBUTES:
            for attribute in ASSET_ATTRIBUTES[node.tag]:
                value = node.attrs.get(attribute)
                if value:
                    observations.append(
                        _reference_observation(
                            "html.asset",
                            relative_path,
                            node,
                            attribute=attribute,
                            value=value,
                            id_counts=id_counts,
                        )
                    )
        if node.tag == "form":
            action = node.attrs.get("action")
            observations.append(
                _reference_observation(
                    "html.form",
                    relative_path,
                    node,
                    attribute="action",
                    value=action,
                    id_counts=id_counts,
                    extra_metadata={
                        "method": node.attrs.get("method", "get").lower(),
                        "field_count": _form_field_count(node),
                    },
                )
            )
    for warning in parser.warnings:
        observations.append(
            _parse_error_observation(
                relative_path,
                error_kind=warning["error_kind"],
                message=_warning_message(warning),
                line_number=warning.get("line"),
                recovered=True,
            )
        )
    return tuple(observations)


def _content_exceeds_structural_limit(content: str) -> bool:
    if len(content) > MAX_HTML_STRUCTURAL_BYTES:
        return True
    return len(content.encode("utf-8")) > MAX_HTML_STRUCTURAL_BYTES


def _size_limited_observations(relative_path: str) -> tuple[RawObservation, ...]:
    document = RawObservation(
        kind="html.document",
        source_id=f"{relative_path}#html-document",
        path=relative_path,
        target=html_document_key(relative_path),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": "html",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "parse_warning_count": 1,
            "element_count": 0,
            "anchor_count": 0,
            "extraction_policy": "size-limited",
            "structural_byte_limit": MAX_HTML_STRUCTURAL_BYTES,
        },
    )
    return (
        document,
        _parse_error_observation(
            relative_path,
            error_kind="document-size-limit",
            message=(
                "HTML structural extraction skipped because the document exceeds "
                f"the {MAX_HTML_STRUCTURAL_BYTES}-byte limit"
            ),
            line_number=None,
            recovered=False,
        ),
    )


def _document_observation(
    relative_path: str,
    parser: _StaticHtmlParser,
    id_counts: dict[str, int],
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "html",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "parse_warning_count": len(parser.warnings),
    }
    root = parser.nodes[0] if parser.nodes else None
    if root is not None:
        metadata["root_element"] = root.tag
    html_node = next((node for node in parser.nodes if node.tag == "html"), None)
    if html_node is not None and _safe_attr(html_node.attrs.get("lang")):
        metadata["language"] = html_node.attrs["lang"]
    title = _document_title(parser.nodes)
    if title is not None:
        metadata["title"] = title
    if parser.doctype is not None:
        metadata["doctype"] = parser.doctype
    metadata["element_count"] = len(parser.nodes)
    metadata["anchor_count"] = sum(1 for count in id_counts.values() if count == 1)
    return RawObservation(
        kind="html.document",
        source_id=f"{relative_path}#html-document",
        path=relative_path,
        target=html_document_key(relative_path),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _element_observation(
    relative_path: str,
    node: _HtmlNode,
    id_counts: dict[str, int],
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "html",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "tag": node.tag,
        "pointer": node.pointer,
        "attribute_count": len(node.attrs),
        "child_count": len(node.children),
        "structural_identity": "document-pointer-with-sibling-indexes",
    }
    node_id = node.attrs.get("id")
    if _safe_attr(node_id):
        metadata["id"] = node_id
        metadata["id_is_unique"] = id_counts.get(node_id, 0) == 1
    classes = _safe_classes(node.attrs.get("class"))
    if classes:
        metadata["classes"] = classes
    if node.tag == "script":
        metadata["content_policy"] = "not-executed"
        metadata["content_length"] = _text_length(node)
    elif node.tag == "style":
        metadata["content_policy"] = "not-parsed"
        metadata["content_length"] = _text_length(node)
    else:
        text_summary = _safe_text_summary(_node_text(node))
        if text_summary is not None and not _is_secret_node(node):
            metadata["text_summary"] = text_summary
    if _is_secret_node(node):
        metadata["redacted"] = True
        metadata["redaction_reason"] = "secret-prone-html-attribute"
    return RawObservation(
        kind="html.element",
        source_id=f"{relative_path}#html-element:{node.pointer}",
        path=relative_path,
        start_line=node.start_line,
        end_line=node.start_line,
        name=node.pointer,
        target=html_element_key(relative_path, node.pointer),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _heading_observation(
    relative_path: str,
    node: _HtmlNode,
    id_counts: dict[str, int],
) -> RawObservation:
    node_id = node.attrs.get("id")
    id_is_unique = _safe_attr(node_id) and id_counts.get(node_id, 0) == 1
    source_key = html_element_key(relative_path, node.pointer)
    target = html_anchor_key(relative_path, node_id) if id_is_unique else source_key
    metadata: dict[str, Any] = {
        "format": "html",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "heading_level": int(node.tag[1]),
        "source_element_pointer": node.pointer,
        "source_element_key": source_key,
        "id_is_unique": bool(id_is_unique),
    }
    if _safe_attr(node_id):
        metadata["id"] = node_id
    text_summary = _safe_text_summary(_node_text(node))
    if text_summary is not None and not _is_secret_node(node):
        metadata["text_summary"] = text_summary
    return RawObservation(
        kind="html.heading",
        source_id=f"{relative_path}#html-heading:{node.pointer}",
        path=relative_path,
        start_line=node.start_line,
        end_line=node.start_line,
        name=node.pointer,
        target=target,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _reference_observation(
    kind: str,
    relative_path: str,
    node: _HtmlNode,
    *,
    attribute: str,
    value: str | None,
    id_counts: dict[str, int],
    extra_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    source_key = html_element_key(relative_path, node.pointer)
    reference = _target_for_reference(relative_path, value, id_counts)
    metadata: dict[str, Any] = {
        "format": "html",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "tag": node.tag,
        "pointer": node.pointer,
        "source_key": source_key,
        "source_element_pointer": node.pointer,
        "attribute": attribute,
        "reference_kind": reference["kind"],
        "resolution_reason": reference["reason"],
        "redacted": _is_secret_name(attribute) or _is_secret_node(node),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    if not metadata["redacted"] and reference.get("summary") is not None:
        metadata["raw_value_summary"] = reference["summary"]
    if metadata["redacted"]:
        metadata["redaction_reason"] = "secret-prone-html-attribute"
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind}:{node.pointer}:{attribute}",
        path=relative_path,
        start_line=node.start_line,
        end_line=node.start_line,
        name=node.pointer,
        target=reference["target"],
        confidence="heuristic" if reference["kind"] != "unknown" else "unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _target_for_reference(
    relative_path: str,
    value: str | None,
    id_counts: dict[str, int],
) -> dict[str, Any]:
    if value is None or not value.strip():
        return {
            "kind": "unknown",
            "target": unknown_key("html.reference", "missing-target"),
            "reason": "missing-reference-target",
        }
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered.startswith("javascript:"):
        return {
            "kind": "dynamic",
            "target": dynamic_key("url", "javascript-url"),
            "reason": "javascript-url-not-executed",
        }
    if stripped.startswith("#"):
        fragment = stripped[1:]
        if _safe_attr(fragment) and id_counts.get(fragment, 0) == 1:
            return {
                "kind": "html.anchor",
                "target": html_anchor_key(relative_path, fragment),
                "reason": "same-document-fragment",
                "summary": f"#{fragment}",
            }
        return {
            "kind": "unknown",
            "target": unknown_key("html.anchor", "unresolved-fragment"),
            "reason": "unresolved-fragment",
        }
    parsed = urlsplit(stripped)
    if parsed.scheme in ("http", "https", "mailto"):
        return {
            "kind": "external.url",
            "target": external_url_key(stripped),
            "reason": "url-literal",
            "summary": stripped,
        }
    if parsed.scheme:
        return {
            "kind": "dynamic",
            "target": dynamic_key("url", "unsupported-url-scheme"),
            "reason": "unsupported-url-scheme",
        }
    if _is_dynamic_value(stripped):
        return {
            "kind": "dynamic",
            "target": dynamic_key("file", "html-reference-expanded-from-variable"),
            "reason": "dynamic-file-reference",
        }
    path_part = stripped.split("#", 1)[0].split("?", 1)[0]
    if path_part.startswith("/"):
        return {
            "kind": "external",
            "target": external_key("file", "absolute-config-reference"),
            "reason": "absolute-file-reference",
            "summary": path_part,
        }
    resolved = _resolve_repo_path(relative_path, path_part)
    if resolved is None:
        return {
            "kind": "unknown",
            "target": unknown_key("file", "repo-escaping-config-reference"),
            "reason": "repo-escaping-file-reference",
        }
    return {
        "kind": "file",
        "target": file_key(resolved),
        "reason": "relative-file-reference",
        "summary": path_part,
    }


def _id_counts(nodes: list[_HtmlNode]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        node_id = node.attrs.get("id")
        if _safe_attr(node_id):
            counts[node_id] = counts.get(node_id, 0) + 1
    return counts


def _document_title(nodes: list[_HtmlNode]) -> str | None:
    title = next((node for node in nodes if node.tag == "title"), None)
    if title is None:
        return None
    return _safe_text_summary(_node_text(title))


def _node_text(node: _HtmlNode) -> str:
    pieces = list(node.text_parts)
    for child in node.children:
        if child.tag not in ("script", "style"):
            pieces.append(_node_text(child))
    return " ".join(piece.strip() for piece in pieces if piece.strip())


def _text_length(node: _HtmlNode) -> int:
    return len("".join(node.text_parts))


def _safe_text_summary(value: str) -> str | None:
    summary = " ".join(value.split())
    if not summary or _is_secret_name(summary):
        return None
    if not summary.isprintable():
        return None
    return summary[:120]


def _safe_attr(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    if not STABLE_ID_PATTERN.match(value):
        return False
    return not _is_secret_name(value)


def _safe_classes(value: str | None) -> list[str]:
    if value is None:
        return []
    classes = []
    for class_name in value.split():
        if _safe_attr(class_name):
            classes.append(class_name)
    return classes


def _is_secret_node(node: _HtmlNode) -> bool:
    for key, value in node.attrs.items():
        if _is_secret_name(key) or _is_secret_name(value):
            return True
    return False


def _is_secret_name(value: str | None) -> bool:
    if value is None:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return any(marker in normalized for marker in SECRET_PRONE_MARKERS)


def _is_dynamic_value(value: str) -> bool:
    return any(marker in value for marker in DYNAMIC_MARKERS)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    if not value:
        return None
    base = PurePosixPath(relative_path).parent
    candidate = PurePosixPath(value)
    combined = base / candidate
    parts: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _form_field_count(node: _HtmlNode) -> int:
    return sum(1 for child in _walk_descendants(node) if child.tag in FORM_FIELD_TAGS)


def _walk_descendants(node: _HtmlNode) -> tuple[_HtmlNode, ...]:
    descendants: list[_HtmlNode] = []
    for child in node.children:
        descendants.append(child)
        descendants.extend(_walk_descendants(child))
    return tuple(descendants)


def _parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    line_number: int | None,
    recovered: bool,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "html",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "error_kind": error_kind,
        "message_summary": message[:120],
        "recovered": recovered,
    }
    if line_number is not None:
        metadata["line_number"] = line_number
    return RawObservation(
        kind="html.parse_error",
        source_id=f"{relative_path}#html-parse-error:{line_number or 'document'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _warning_message(warning: dict[str, Any]) -> str:
    if warning["error_kind"] == "recoverable-unclosed-elements":
        tags = warning.get("tags", [])
        return "unclosed elements: " + ", ".join(str(tag) for tag in tags[:8])
    tag = warning.get("tag")
    if tag:
        return f"unmatched end tag: {tag}"
    return str(warning["error_kind"])
