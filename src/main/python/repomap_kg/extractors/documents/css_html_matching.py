from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg import __version__
from repomap_kg.graph.keys import GraphKeyError, html_element_key, parse_key
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-css-html-matcher"
SCOPE = "local-html-css"
IDENTIFIER = r"-?[_a-zA-Z][_a-zA-Z0-9-]*"
SIMPLE_TOKEN_PATTERN = re.compile(
    rf"(?P<element>^[a-zA-Z][a-zA-Z0-9-]*)|(?P<class>\.({IDENTIFIER}))|(?P<id>#({IDENTIFIER}))"
)


@dataclass(frozen=True)
class _HtmlElement:
    path: str
    key: str
    pointer: str
    tag: str
    classes: tuple[str, ...]
    element_id: str | None
    id_is_unique: bool


@dataclass(frozen=True)
class _CssSelector:
    path: str
    key: str
    pointer: str
    text: str
    start_line: int | None
    end_line: int | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class _SelectorComponents:
    tag: str | None
    classes: tuple[str, ...]
    ids: tuple[str, ...]


def extract_css_selector_match_observations(
    observations: Sequence[RawObservation],
) -> tuple[RawObservation, ...]:
    stylesheet_pairs = _stylesheet_pairs(observations)
    if not stylesheet_pairs:
        return ()

    selectors_by_file = _css_selectors_by_file(observations)
    elements_by_file = _html_elements_by_file(observations)
    anchors_by_pointer = _html_anchors_by_pointer(observations)
    element_lookups_by_file: dict[str, dict[str, _HtmlElement]] = {}
    matches: list[RawObservation] = []

    for html_file, css_file, stylesheet_source in stylesheet_pairs:
        selectors = selectors_by_file.get(css_file, ())
        elements = elements_by_file.get(html_file, ())
        if html_file not in element_lookups_by_file:
            element_lookups_by_file[html_file] = {
                element.pointer: element for element in elements
            }
        anchors = anchors_by_pointer.get(html_file, {})
        for selector in selectors:
            matches.extend(
                _match_selector(
                    selector,
                    elements=elements,
                    elements_by_pointer=element_lookups_by_file[html_file],
                    anchors=anchors,
                    html_file=html_file,
                    stylesheet_source=stylesheet_source,
                )
            )

    return tuple(matches)


def _stylesheet_pairs(
    observations: Sequence[RawObservation],
) -> tuple[tuple[str, str, str], ...]:
    pairs = []
    seen = set()
    for observation in observations:
        if observation.kind != "html.asset":
            continue
        if observation.metadata.get("tag") != "link":
            continue
        if observation.metadata.get("attribute") != "href":
            continue
        target = observation.target
        if not isinstance(target, str):
            continue
        try:
            parsed = parse_key(target)
        except GraphKeyError:
            continue
        if parsed.namespace != "file" or parsed.path is None:
            continue
        css_file = parsed.path
        if not css_file.endswith(".css"):
            continue
        pair = (
            observation.path,
            css_file,
            f"{observation.path}#stylesheet-link:{css_file}",
        )
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return tuple(pairs)


def _css_selectors_by_file(
    observations: Sequence[RawObservation],
) -> dict[str, tuple[_CssSelector, ...]]:
    selectors: dict[str, list[_CssSelector]] = {}
    for observation in observations:
        if observation.kind != "css.selector":
            continue
        selector_key = observation.target
        pointer = _metadata_text(observation.metadata, "selector_pointer")
        selector_text = _metadata_text(observation.metadata, "selector_text")
        if selector_key is None or pointer is None or selector_text is None:
            continue
        try:
            parsed = parse_key(selector_key)
        except GraphKeyError:
            continue
        if parsed.namespace != "css.selector":
            continue
        selectors.setdefault(observation.path, []).append(
            _CssSelector(
                path=observation.path,
                key=selector_key,
                pointer=pointer,
                text=selector_text,
                start_line=observation.start_line,
                end_line=observation.end_line,
                metadata=observation.metadata,
            )
        )
    return {path: tuple(items) for path, items in selectors.items()}


def _html_elements_by_file(
    observations: Sequence[RawObservation],
) -> dict[str, tuple[_HtmlElement, ...]]:
    elements: dict[str, list[_HtmlElement]] = {}
    for observation in observations:
        if observation.kind != "html.element":
            continue
        pointer = _metadata_text(observation.metadata, "pointer")
        tag = _metadata_text(observation.metadata, "tag")
        if pointer is None or tag is None:
            continue
        target = observation.target or html_element_key(observation.path, pointer)
        classes = _string_tuple(observation.metadata.get("classes"))
        element_id = _metadata_text(observation.metadata, "id")
        id_is_unique = observation.metadata.get("id_is_unique") is True
        elements.setdefault(observation.path, []).append(
            _HtmlElement(
                path=observation.path,
                key=target,
                pointer=pointer,
                tag=tag.lower(),
                classes=classes,
                element_id=element_id,
                id_is_unique=id_is_unique,
            )
        )
    return {path: tuple(items) for path, items in elements.items()}


def _html_anchors_by_pointer(
    observations: Sequence[RawObservation],
) -> dict[str, dict[str, str]]:
    anchors: dict[str, dict[str, str]] = {}
    for observation in observations:
        if observation.kind != "html.heading":
            continue
        if observation.metadata.get("id_is_unique") is not True:
            continue
        source_pointer = _metadata_text(observation.metadata, "source_element_pointer")
        target = observation.target
        if source_pointer is None or target is None:
            continue
        try:
            parsed = parse_key(target)
        except GraphKeyError:
            continue
        if parsed.namespace != "html.anchor":
            continue
        anchors.setdefault(observation.path, {})[source_pointer] = target
    return anchors


def _match_selector(
    selector: _CssSelector,
    *,
    elements: Sequence[_HtmlElement],
    elements_by_pointer: Mapping[str, _HtmlElement],
    anchors: Mapping[str, str],
    html_file: str,
    stylesheet_source: str,
) -> tuple[RawObservation, ...]:
    if _unsupported_selector(selector.text, selector.metadata):
        return ()
    descendant_parts = selector.text.split()
    if len(descendant_parts) > 2:
        return ()
    if len(descendant_parts) == 2:
        ancestor = _parse_compound_selector(descendant_parts[0])
        descendant = _parse_compound_selector(descendant_parts[1])
        if ancestor is None or descendant is None:
            return ()
        return tuple(
            _match_observation(
                selector,
                element,
                target_key=anchors.get(element.pointer, element.key),
                match_kind="limited-descendant",
                matched_components=_matched_components(descendant)
                | {"ancestor": _matched_components(ancestor)},
                html_file=html_file,
                stylesheet_source=stylesheet_source,
            )
            for element in elements
            if _components_match(descendant, element)
            and _has_matching_ancestor(
                ancestor,
                element,
                elements_by_pointer,
            )
        )

    components = _parse_compound_selector(selector.text)
    if components is None:
        return ()
    match_kind = _match_kind(components)
    return tuple(
        _match_observation(
            selector,
            element,
            target_key=anchors.get(element.pointer, element.key)
            if components.ids
            else element.key,
            match_kind=match_kind,
            matched_components=_matched_components(components),
            html_file=html_file,
            stylesheet_source=stylesheet_source,
        )
        for element in elements
        if _components_match(components, element)
    )


def _match_observation(
    selector: _CssSelector,
    element: _HtmlElement,
    *,
    target_key: str,
    match_kind: str,
    matched_components: Mapping[str, Any],
    html_file: str,
    stylesheet_source: str,
) -> RawObservation:
    metadata = {
        "selector_key": selector.key,
        "selector_text": selector.text,
        "html_key": target_key,
        "html_pointer": element.pointer,
        "match_kind": match_kind,
        "matched_components": dict(matched_components),
        "css_file": selector.path,
        "html_file": html_file,
        "stylesheet_reference_source": stylesheet_source,
        "scope": SCOPE,
        "not_runtime_style": True,
        "limitations": [
            "static-source-match-only",
            "no-cascade",
            "no-computed-style",
            "no-rendering",
            "no-javascript",
            "no-url-fetching",
        ],
    }
    return RawObservation(
        kind="css.selector_match",
        source_id=(
            f"{selector.path}#css-selector-match:"
            f"{selector.pointer}:{html_file}:{element.pointer}"
        ),
        path=selector.path,
        start_line=selector.start_line,
        end_line=selector.end_line,
        name=selector.key,
        target=target_key,
        confidence=(
            "heuristic" if match_kind == "limited-descendant" else "extracted"
        ),
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _unsupported_selector(selector_text: str, metadata: Mapping[str, Any]) -> bool:
    if any(combinator in selector_text for combinator in (">", "+", "~")):
        return True
    if "[" in selector_text or "]" in selector_text:
        return True
    if metadata.get("pseudo_classes") or metadata.get("pseudo_elements"):
        return True
    return False


def _parse_compound_selector(selector_text: str) -> _SelectorComponents | None:
    cursor = 0
    tag: str | None = None
    classes: list[str] = []
    ids: list[str] = []
    text = selector_text.strip()
    while cursor < len(text):
        match = SIMPLE_TOKEN_PATTERN.match(text, cursor)
        if match is None:
            return None
        if match.group("element") is not None:
            if cursor != 0 or tag is not None:
                return None
            tag = match.group("element").lower()
        elif match.group("class") is not None:
            classes.append(match.group("class")[1:])
        elif match.group("id") is not None:
            ids.append(match.group("id")[1:])
        cursor = match.end()
    if tag is None and not classes and not ids:
        return None
    return _SelectorComponents(
        tag=tag,
        classes=tuple(dict.fromkeys(classes)),
        ids=tuple(dict.fromkeys(ids)),
    )


def _components_match(components: _SelectorComponents, element: _HtmlElement) -> bool:
    if components.tag is not None and components.tag != element.tag:
        return False
    if any(class_name not in element.classes for class_name in components.classes):
        return False
    if components.ids:
        if len(components.ids) != 1:
            return False
        if element.element_id != components.ids[0]:
            return False
        if not element.id_is_unique:
            return False
    return True


def _has_matching_ancestor(
    components: _SelectorComponents,
    element: _HtmlElement,
    elements_by_pointer: Mapping[str, _HtmlElement],
) -> bool:
    pointer = element.pointer
    while "/" in pointer.lstrip("/"):
        pointer = pointer.rsplit("/", 1)[0]
        ancestor = elements_by_pointer.get(pointer)
        if ancestor is not None and _components_match(components, ancestor):
            return True
    return False


def _match_kind(components: _SelectorComponents) -> str:
    populated = sum(
        (
            components.tag is not None,
            bool(components.classes),
            bool(components.ids),
        )
    )
    if populated > 1 or len(components.classes) > 1:
        return "compound"
    if components.ids:
        return "id"
    if components.classes:
        return "class"
    return "element"


def _matched_components(components: _SelectorComponents) -> dict[str, Any]:
    matched: dict[str, Any] = {}
    if components.tag is not None:
        matched["element"] = components.tag
    if components.classes:
        matched["classes"] = list(components.classes)
    if components.ids:
        matched["ids"] = list(components.ids)
    return matched


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())
