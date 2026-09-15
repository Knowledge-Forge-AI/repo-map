"""jQuery observation helpers for JavaScript extraction."""

from __future__ import annotations

import re

from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_observations import (
    _framework_observation,
    _parse_error,
)
from repomap_kg.extractors.languages.javascript_references import (
    _is_secret_prone,
    _safe_summary,
    _sanitize_url,
    _specifier_target,
)
from repomap_kg.extractors.languages.javascript_routes import _first_string_literal


MAX_SELECTOR_LENGTH = 120
MAX_URL_SUMMARY_LENGTH = 120
JQUERY_SELECTOR_RE = re.compile(
    r"""(?:\$|jQuery)\s*\(\s*(?P<quote>["'])(?P<selector>.*?)(?P=quote)\s*\)"""
)
JQUERY_EVENT_RE = re.compile(
    r"""(?:\$\([^)]*\)|jQuery\([^)]*\))\.(?P<event>on|click|submit|change|ready)\s*\((?P<args>.*)"""
)
JQUERY_AJAX_OBJECT_RE = re.compile(
    r"""\$\.ajax\s*\(\s*\{(?P<body>.*?)\}\s*\)"""
)
JQUERY_AJAX_CALL_RE = re.compile(
    r"""\$\.(?P<method>get|post)\s*\(\s*(?P<quote>["'])(?P<url>.*?)(?P=quote)"""
)
JQUERY_LOAD_RE = re.compile(
    r"""\.load\s*\(\s*(?P<quote>["'])(?P<url>.*?)(?P=quote)"""
)
JQUERY_PLUGIN_RE = re.compile(r"""\$\.fn\.(?P<name>[A-Za-z_$][\w$]*)\s*=""")


def _jquery_observations(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    line: str,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for match in JQUERY_SELECTOR_RE.finditer(line):
        selector = match.group("selector")
        if len(selector) > MAX_SELECTOR_LENGTH or _is_secret_prone(selector):
            observations.append(
                _parse_error(
                    relative_path,
                    js_format,
                    profile,
                    "framework-selector-limit",
                    "jQuery selector exceeded static scanner limit or redaction policy",
                    line_number,
                )
            )
            continue
        metadata = {"selector": selector, "selector_length": len(selector)}
        observations.append(
            _framework_observation(
                "jquery.selector",
                relative_path,
                js_format,
                "jquery",
                line_number,
                selector,
                source_key,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.dom_selector",
                relative_path,
                js_format,
                "jquery",
                line_number,
                selector,
                source_key,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for match in JQUERY_EVENT_RE.finditer(line):
        event_method = match.group("event")
        event_name = (
            _first_string_literal(match.group("args"))
            if event_method == "on"
            else event_method
        )
        if not event_name:
            event_name = event_method
        metadata = {"event_name": event_name, "event_method": event_method}
        observations.append(
            _framework_observation(
                "jquery.event",
                relative_path,
                js_format,
                "jquery",
                line_number,
                event_name,
                source_key,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.dom_event",
                relative_path,
                js_format,
                "jquery",
                line_number,
                event_name,
                source_key,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for ajax_method, raw_url in _jquery_ajax_calls(line):
        target, reason = _specifier_target(relative_path, raw_url, repository_paths)
        sanitized_url = _sanitize_url(raw_url)
        url_summary = _safe_summary(sanitized_url, max_length=MAX_URL_SUMMARY_LENGTH)
        metadata = {
            "ajax_method": ajax_method,
            "url_summary": url_summary,
            "target_key": target,
            "resolution_reason": reason,
            "not_fetched": True,
        }
        observations.append(
            _framework_observation(
                "jquery.ajax",
                relative_path,
                js_format,
                "jquery",
                line_number,
                ajax_method,
                source_key,
                target=target,
                metadata=metadata,
            )
        )
        observations.append(
            _framework_observation(
                "js.ajax_reference",
                relative_path,
                js_format,
                "jquery",
                line_number,
                ajax_method,
                source_key,
                target=target,
                metadata={**metadata, "framework": "jquery"},
            )
        )
    for match in JQUERY_PLUGIN_RE.finditer(line):
        plugin_name = match.group("name")
        observations.append(
            _framework_observation(
                "jquery.plugin_reference",
                relative_path,
                js_format,
                "jquery",
                line_number,
                plugin_name,
                source_key,
                metadata={"plugin_name": plugin_name, "not_executed": True},
            )
        )
    return tuple(observations)


def _jquery_ajax_calls(line: str) -> tuple[tuple[str, str], ...]:
    calls: list[tuple[str, str]] = []
    for match in JQUERY_AJAX_OBJECT_RE.finditer(line):
        url = _object_literal_string_value(match.group("body"), "url")
        if url is not None:
            calls.append(("ajax", url))
    for match in JQUERY_AJAX_CALL_RE.finditer(line):
        calls.append((match.group("method"), match.group("url")))
    for match in JQUERY_LOAD_RE.finditer(line):
        calls.append(("load", match.group("url")))
    return tuple(calls)


def _object_literal_string_value(body: str, key: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(key)}\s*:\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
        body,
    )
    if not match:
        return None
    return match.group("value")
