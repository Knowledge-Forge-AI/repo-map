"""Conservative static CSS raw observation extraction."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.documents.css_support import (
    PARSER_MODE,
    PARSER_NAME,
    _CssDeclaration,
    _CssParseError,
    _CssReference,
    _CssRule,
    _ParseState,
    _custom_property_names,
    _element_names,
    _extract_url_values,
    _find_at_rule_delimiter,
    _find_matching_brace,
    _find_matching_delimiter,
    _find_matching_paren,
    _find_next_top_level_char,
    _font_family,
    _is_dynamic_value,
    _is_secret_name,
    _line_for_index,
    _next_pointer,
    _ordered_unique,
    _parse_declarations,
    _reference_observations_target_for_relative,
    _references_for_declaration,
    _references_for_declarations,
    _references_for_text,
    _resolve_repo_path,
    _safe_summary,
    _selector_kind,
    _selector_metadata,
    _skip_whitespace,
    _split_declaration_segments,
    _split_selectors,
    _strip_comments,
    _strip_css_string,
    _target_for_reference,
    _target_for_reference_in_path,
    _value_type,
)
from repomap_kg.graph.keys import (
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
)
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-css"


def extract_css_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    state = _ParseState(_strip_comments(content))
    _parse_rules(state, 0, len(state.content), parent_pointer=None)

    selector_count = sum(len(rule.selectors) for rule in state.rules)
    custom_properties = _custom_property_names(state.rules)
    reference_count = sum(len(rule.references) for rule in state.rules)
    observations: list[RawObservation] = [
        _document_observation(
            relative_path,
            rule_count=len(state.rules),
            selector_count=selector_count,
            custom_property_count=len(custom_properties),
            reference_count=reference_count,
            parse_error_count=len(state.errors),
        )
    ]
    for rule in state.rules:
        observations.append(_rule_observation(relative_path, rule))
        observations.extend(_selector_observations(relative_path, rule))
        observations.extend(_declaration_observations(relative_path, rule))
        observations.extend(_custom_property_observations(relative_path, rule))
        observations.extend(_reference_observations(relative_path, rule))
    for error in state.errors:
        observations.append(_parse_error_observation(relative_path, error))
    return tuple(observations)


def _parse_rules(
    state: _ParseState,
    start: int,
    end: int,
    *,
    parent_pointer: str | None,
) -> None:
    index = start
    counters: dict[str, int] = {}
    while index < end:
        index = _skip_whitespace(state.content, index, end)
        if index >= end:
            return
        if state.content[index] == "@":
            index = _parse_at_rule(state, index, end, parent_pointer, counters)
            continue
        index = _parse_style_rule(state, index, end, parent_pointer, counters)


def _parse_at_rule(
    state: _ParseState,
    index: int,
    end: int,
    parent_pointer: str | None,
    counters: dict[str, int],
) -> int:
    name_end = index + 1
    while name_end < end and (
        state.content[name_end].isalnum() or state.content[name_end] in "-_"
    ):
        name_end += 1
    at_name = state.content[index + 1 : name_end].lower() or "unknown"
    prelude_start = _skip_whitespace(state.content, name_end, end)
    delimiter_index, delimiter = _find_at_rule_delimiter(
        state.content, prelude_start, end
    )
    if delimiter_index is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-at-rule",
                message=f"unterminated @{at_name} rule",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    prelude = state.content[prelude_start:delimiter_index].strip()
    if delimiter == ";":
        if at_name == "import":
            pointer = _next_pointer(parent_pointer, "import", counters)
            rule = _CssRule(
                pointer=pointer,
                rule_type="import",
                at_rule_name=at_name,
                at_rule_prelude=prelude,
                start_index=index,
                start_line=_line_for_index(state.content, index),
                parent_pointer=parent_pointer,
            )
            rule.references.extend(
                _references_for_text(
                    prelude,
                    source_kind="import",
                    rule_pointer=pointer,
                    property_name=None,
                    line_number=rule.start_line,
                )
            )
            state.rules.append(rule)
        return delimiter_index + 1

    block_start = delimiter_index + 1
    block_end = _find_matching_brace(state.content, delimiter_index, end)
    if block_end is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-at-rule-block",
                message=f"unterminated @{at_name} block",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    if at_name in ("media", "supports"):
        pointer = _next_pointer(parent_pointer, at_name, counters)
        state.rules.append(
            _CssRule(
                pointer=pointer,
                rule_type=at_name,
                at_rule_name=at_name,
                at_rule_prelude=prelude,
                start_index=index,
                start_line=_line_for_index(state.content, index),
                parent_pointer=parent_pointer,
            )
        )
        _parse_rules(state, block_start, block_end, parent_pointer=pointer)
        return block_end + 1
    if at_name == "font-face":
        pointer = _next_pointer(parent_pointer, "font-face", counters)
        rule = _CssRule(
            pointer=pointer,
            rule_type="font-face",
            at_rule_name=at_name,
            at_rule_prelude=prelude,
            start_index=index,
            start_line=_line_for_index(state.content, index),
            parent_pointer=parent_pointer,
        )
        block = state.content[block_start:block_end]
        rule.declarations.extend(_parse_declarations(block, state.content, block_start))
        rule.references.extend(_references_for_declarations(rule))
        state.rules.append(rule)
        return block_end + 1
    pointer = _next_pointer(parent_pointer, "at-rule", counters)
    state.rules.append(
        _CssRule(
            pointer=pointer,
            rule_type="unknown-at-rule",
            at_rule_name=at_name,
            at_rule_prelude=prelude,
            start_index=index,
            start_line=_line_for_index(state.content, index),
            parent_pointer=parent_pointer,
        )
    )
    return block_end + 1


def _parse_style_rule(
    state: _ParseState,
    index: int,
    end: int,
    parent_pointer: str | None,
    counters: dict[str, int],
) -> int:
    brace_index = _find_next_top_level_char(state.content, "{", index, end)
    if brace_index is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-rule",
                message="style rule missing block",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    selector_text = state.content[index:brace_index].strip()
    if not selector_text:
        return brace_index + 1
    block_end = _find_matching_brace(state.content, brace_index, end)
    if block_end is None:
        state.errors.append(
            _CssParseError(
                error_kind="malformed-rule-block",
                message="unterminated style rule",
                line_number=_line_for_index(state.content, index),
                recovered=True,
            )
        )
        return end
    block = state.content[brace_index + 1 : block_end]
    pointer = _next_pointer(parent_pointer, "rule", counters)
    if "{" in block or "}" in block:
        state.errors.append(
            _CssParseError(
                error_kind="unsupported-nested-style-rule",
                message="nested style rules are not supported in CSS1",
                line_number=_line_for_index(state.content, brace_index + 1),
                recovered=True,
                rule_pointer=pointer,
            )
        )
        return block_end + 1
    rule = _CssRule(
        pointer=pointer,
        rule_type="style",
        selector_text=" ".join(selector_text.split()),
        selectors=_split_selectors(selector_text),
        start_index=index,
        start_line=_line_for_index(state.content, index),
        parent_pointer=parent_pointer,
    )
    rule.declarations.extend(_parse_declarations(block, state.content, brace_index + 1))
    rule.references.extend(_references_for_declarations(rule))
    state.rules.append(rule)
    return block_end + 1


def _document_observation(
    relative_path: str,
    *,
    rule_count: int,
    selector_count: int,
    custom_property_count: int,
    reference_count: int,
    parse_error_count: int,
) -> RawObservation:
    return RawObservation(
        kind="css.document",
        source_id=f"{relative_path}#css-document",
        path=relative_path,
        target=css_document_key(relative_path),
        confidence="extracted" if parse_error_count == 0 else "heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "source_kind": "file",
            "rule_count": rule_count,
            "selector_count": selector_count,
            "custom_property_count": custom_property_count,
            "reference_count": reference_count,
            "parse_error_count": parse_error_count,
        },
    )


def _rule_observation(relative_path: str, rule: _CssRule) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "css",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "rule_pointer": rule.pointer,
        "rule_type": rule.rule_type,
        "declaration_count": len(rule.declarations),
        "reference_count": len(rule.references),
        "identity_mode": "structural-document",
    }
    if rule.parent_pointer is not None:
        metadata["parent_rule_pointer"] = rule.parent_pointer
    if rule.selector_text is not None:
        metadata["selector_text"] = rule.selector_text
    if rule.at_rule_name is not None:
        metadata["at_rule_name"] = rule.at_rule_name
    if rule.at_rule_prelude:
        metadata["at_rule_prelude_summary"] = _safe_summary(rule.at_rule_prelude)
    custom_names = sorted(
        {declaration.property_name for declaration in rule.declarations if declaration.property_name.startswith("--")}
    )
    if custom_names:
        metadata["custom_property_names"] = custom_names
    font_family = _font_family(rule)
    if font_family is not None:
        metadata["font_family_summary"] = font_family
    return RawObservation(
        kind="css.rule",
        source_id=f"{relative_path}#css-rule:{rule.pointer}",
        path=relative_path,
        start_line=rule.start_line,
        end_line=rule.start_line,
        name=rule.pointer,
        target=css_rule_key(relative_path, rule.pointer),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _selector_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for index, selector in enumerate(rule.selectors, start=1):
        pointer = f"{rule.pointer}/selector:{index}"
        metadata = _selector_metadata(selector, rule.pointer, pointer, index)
        observations.append(
            RawObservation(
                kind="css.selector",
                source_id=f"{relative_path}#css-selector:{pointer}",
                path=relative_path,
                start_line=rule.start_line,
                end_line=rule.start_line,
                name=pointer,
                target=css_selector_key(relative_path, pointer),
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _declaration_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for index, declaration in enumerate(rule.declarations, start=1):
        references = _references_for_declaration(rule.pointer, declaration)
        reference_targets = [
            _target_for_reference_in_path(relative_path, reference.value)
            for reference in references
        ]
        redacted_for_data_url = any(
            target["reason"] == "data-url-redacted" for target in reference_targets
        )
        redacted = _is_secret_name(declaration.property_name) or _is_secret_name(
            declaration.value
        ) or redacted_for_data_url
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "rule_pointer": rule.pointer,
            "property_name": declaration.property_name,
            "value_type": _value_type(declaration.value),
            "important": declaration.important,
            "redacted": redacted,
        }
        if redacted_for_data_url:
            metadata["redaction_reason"] = "data-url-payload-redacted"
        elif redacted:
            metadata["redaction_reason"] = "secret-prone-css-declaration"
        else:
            summary = _safe_summary(declaration.value)
            if summary is not None:
                metadata["value_summary"] = summary
        if references:
            metadata["reference_targets"] = [
                target["target"] for target in reference_targets
            ]
        observations.append(
            RawObservation(
                kind="css.declaration",
                source_id=f"{relative_path}#css-declaration:{rule.pointer}:{index}",
                path=relative_path,
                start_line=declaration.start_line,
                end_line=declaration.start_line,
                name=declaration.property_name,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _custom_property_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    for declaration in rule.declarations:
        if not declaration.property_name.startswith("--"):
            continue
        references = _references_for_declaration(rule.pointer, declaration)
        reference_targets = [
            _target_for_reference_in_path(relative_path, reference.value)
            for reference in references
        ]
        redacted_for_data_url = any(
            target["reason"] == "data-url-redacted" for target in reference_targets
        )
        redacted = _is_secret_name(declaration.property_name) or _is_secret_name(
            declaration.value
        ) or redacted_for_data_url
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "property_name": declaration.property_name,
            "rule_pointer": rule.pointer,
            "definition_count": 1,
            "value_type": _value_type(declaration.value),
            "redacted": redacted,
        }
        if redacted_for_data_url:
            metadata["redaction_reason"] = "data-url-payload-redacted"
        elif redacted:
            metadata["redaction_reason"] = "secret-prone-css-custom-property"
        else:
            summary = _safe_summary(declaration.value)
            if summary is not None:
                metadata["value_summary"] = summary
        observations.append(
            RawObservation(
                kind="css.custom_property",
                source_id=(
                    f"{relative_path}#css-custom-property:"
                    f"{declaration.property_name}:{rule.pointer}"
                ),
                path=relative_path,
                start_line=declaration.start_line,
                end_line=declaration.start_line,
                name=declaration.property_name,
                target=css_custom_property_key(relative_path, declaration.property_name),
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _reference_observations(
    relative_path: str, rule: _CssRule
) -> tuple[RawObservation, ...]:
    observations = []
    source_key = css_rule_key(relative_path, rule.pointer)
    for index, reference in enumerate(rule.references, start=1):
        target = _target_for_reference_in_path(relative_path, reference.value)
        redacted = target["kind"] == "unknown" and target["reason"] == "data-url-redacted"
        metadata: dict[str, Any] = {
            "format": "css",
            "parser": PARSER_NAME,
            "parser_mode": PARSER_MODE,
            "reference_kind": target["kind"],
            "source_kind": reference.source_kind,
            "rule_pointer": reference.rule_pointer,
            "source_key": source_key,
            "resolution_reason": target["reason"],
            "redacted": redacted,
        }
        if reference.property_name is not None:
            metadata["property_name"] = reference.property_name
        if redacted:
            metadata["redaction_reason"] = "data-url-payload-redacted"
            metadata["raw_value_summary"] = "data-url-redacted"
        elif target.get("summary") is not None:
            metadata["raw_value_summary"] = target["summary"]
        observations.append(
            RawObservation(
                kind="css.reference",
                source_id=f"{relative_path}#css-reference:{rule.pointer}:{index}",
                path=relative_path,
                start_line=reference.start_line,
                end_line=reference.start_line,
                name=rule.pointer,
                target=target["target"],
                confidence="heuristic" if target["kind"] != "unknown" else "unknown",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _parse_error_observation(relative_path: str, error: _CssParseError) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "css",
        "parser": PARSER_NAME,
        "parser_mode": PARSER_MODE,
        "error_kind": error.error_kind,
        "message_summary": error.message[:120],
        "recovered": error.recovered,
        "line_number": error.line_number,
    }
    if error.rule_pointer is not None:
        metadata["rule_pointer"] = error.rule_pointer
    return RawObservation(
        kind="css.parse_error",
        source_id=f"{relative_path}#css-parse-error:{error.line_number}",
        path=relative_path,
        start_line=error.line_number,
        end_line=error.line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )
